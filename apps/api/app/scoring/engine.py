"""Score computation orchestration (M3): niche_daily_signals in,
scores + revenue_estimates out. Deterministic and versioned: rows carry
ALGO_VERSION, reruns for a (niche, date) overwrite in place.
"""

import datetime
from decimal import Decimal
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.models import Niche, NicheDailySignal, RevenueEstimate, Score
from app.db.partitions import ensure_monthly_partition
from app.scoring import ALGO_VERSION
from app.scoring.labels import trend_label
from app.scoring.opportunity import confidence, momentum_multiplier, opportunity
from app.scoring.preprocess import pct_growth, prepare
from app.scoring.revenue import revenue_range
from app.scoring.subscores import competition_scores, demand_scores

HISTORY_DAYS = 28
SIGNAL_FAMILIES = ("engagement", "search", "social")  # for confidence coverage


def _load_history(session: Session, day: datetime.date) -> pd.DataFrame:
    start = day - datetime.timedelta(days=HISTORY_DAYS - 1)
    rows = session.execute(
        select(NicheDailySignal).where(NicheDailySignal.date >= start, NicheDailySignal.date <= day)
    ).scalars()
    records = [
        {
            "niche_id": r.niche_id,
            "date": r.date,
            "active_listings": r.active_listings,
            "new_listings": r.new_listings,
            "median_price": float(r.median_price) if r.median_price is not None else None,
            "price_iqr": float(r.price_iqr) if r.price_iqr is not None else None,
            "favorites_delta": r.favorites_delta,
            "reviews_delta": r.reviews_delta,
            "hhi": r.hhi,
            "top20_median_reviews": r.top20_median_reviews,
            "young_listing_share": r.young_listing_share,
            "search_interest": r.search_interest,
            "social_mentions": r.social_mentions,
            "social_engagement": r.social_engagement,
        }
        for r in rows
    ]
    return pd.DataFrame.from_records(records)


def _series(group: pd.DataFrame, column: str) -> pd.Series:
    return group.sort_values("date")[column].astype(float).fillna(0.0)


def compute_scores(session: Session, day: datetime.date | None = None) -> int:
    """Score every niche with signals available at `day`. Returns rows
    written."""
    day = day or datetime.date.today()
    frame = _load_history(session, day)
    if frame.empty:
        return 0
    categories: dict[Any, str | None] = {
        nid: cat for nid, cat in session.execute(select(Niche.id, Niche.category))
    }
    frame["category"] = frame["niche_id"].map(categories)

    per_niche: list[dict[str, Any]] = []
    for niche_id, group in frame.groupby("niche_id"):
        latest = group.sort_values("date").iloc[-1]
        engagement_raw = (
            _series(group, "favorites_delta") + _series(group, "reviews_delta")
        ) / _series(group, "active_listings").clip(lower=1)
        engagement = prepare(engagement_raw)
        active = prepare(_series(group, "active_listings"))
        median_price = latest["median_price"]
        iqr = latest["price_iqr"]
        compression = (
            1.0 - min(1.0, (iqr / median_price))
            if median_price and iqr is not None and median_price > 0
            else None
        )
        g_demand = pct_growth(engagement)
        g_supply = pct_growth(active)
        non_null = sum(
            1
            for present in (
                engagement_raw.abs().sum() > 0,
                latest["search_interest"] is not None and not pd.isna(latest["search_interest"]),
                latest["social_engagement"] > 0,
            )
            if present
        ) / len(SIGNAL_FAMILIES)
        per_niche.append(
            {
                "niche_id": niche_id,
                "category": group["category"].iloc[0],
                "engagement_velocity": float(engagement.iloc[-1]),
                "search_interest": latest["search_interest"],
                "review_velocity": float(prepare(_series(group, "reviews_delta")).iloc[-1]),
                "social_engagement": latest["social_engagement"],
                "social_breadth": latest["social_mentions"],
                "demand_level": latest["top20_median_reviews"],
                "listing_count": latest["active_listings"],
                "young_listing_share": latest["young_listing_share"],
                "new_listing_velocity": float(prepare(_series(group, "new_listings")).iloc[-1]),
                "price_compression": compression,
                "concentration": latest["hhi"],
                "review_moat": latest["top20_median_reviews"],
                "momentum": momentum_multiplier(g_demand, g_supply),
                "confidence": confidence(len(group), non_null),
                "engagement_series": engagement,
                "reviews_delta_30d": int(group["reviews_delta"].sum()),
                "median_price": median_price,
            }
        )

    cross = pd.DataFrame(per_niche).set_index("niche_id")
    ensure_monthly_partition(session.connection(), "scores", day)
    ensure_monthly_partition(session.connection(), "revenue_estimates", day)

    written = 0
    for _, cat_frame in cross.groupby("category", dropna=False):
        demand, demand_pct = demand_scores(cat_frame)
        comp, comp_pct = competition_scores(cat_frame)
        for niche_id in cat_frame.index:
            d = float(demand.loc[niche_id]) if pd.notna(demand.loc[niche_id]) else 0.0
            c = float(comp.loc[niche_id]) if pd.notna(comp.loc[niche_id]) else 50.0
            row = cat_frame.loc[niche_id]
            label = trend_label(row["engagement_series"], d, c, row["momentum"])
            opp = opportunity(d, c, row["momentum"], row["confidence"])
            subscores = {
                "demand": {
                    k: (None if pd.isna(v) else round(float(v), 1))
                    for k, v in demand_pct.loc[niche_id].items()
                },
                "competition": {
                    k: (None if pd.isna(v) else round(float(v), 1))
                    for k, v in comp_pct.loc[niche_id].items()
                },
            }
            stmt = pg_insert(Score).values(
                niche_id=niche_id,
                date=day,
                demand=round(d, 2),
                competition=round(c, 2),
                opportunity=opp,
                momentum=round(float(row["momentum"]), 4),
                confidence=round(float(row["confidence"]), 4),
                trend_label=label,
                algo_version=ALGO_VERSION,
                subscores=subscores,
            )
            session.execute(
                stmt.on_conflict_do_update(
                    index_elements=["niche_id", "date"],
                    set_={
                        k: getattr(stmt.excluded, k)
                        for k in (
                            "demand",
                            "competition",
                            "opportunity",
                            "momentum",
                            "confidence",
                            "trend_label",
                            "algo_version",
                            "subscores",
                        )
                    },
                )
            )
            estimate = revenue_range(
                int(row["reviews_delta_30d"]),
                Decimal(str(row["median_price"])) if row["median_price"] else None,
            )
            if estimate is not None:
                rev = pg_insert(RevenueEstimate).values(
                    niche_id=niche_id,
                    date=day,
                    low_usd=estimate[0],
                    high_usd=estimate[1],
                    basis={
                        "reviews_delta_30d": int(row["reviews_delta_30d"]),
                        "median_price": float(row["median_price"]),
                        "review_rate_band": [0.20, 0.25],
                    },
                )
                session.execute(
                    rev.on_conflict_do_update(
                        index_elements=["niche_id", "date"],
                        set_={
                            "low_usd": rev.excluded.low_usd,
                            "high_usd": rev.excluded.high_usd,
                            "basis": rev.excluded.basis,
                        },
                    )
                )
            written += 1
    session.commit()
    return written
