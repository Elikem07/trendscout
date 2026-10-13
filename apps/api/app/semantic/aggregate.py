"""Stage 4: niche_daily_signals — the one table everything downstream
reads (M2.T5). Idempotent per (niche, date)."""

import datetime
from typing import Any

from sqlalchemy import Date, cast, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.models import (
    Listing,
    ListingSnapshot,
    NicheDailySignal,
    NicheKeyword,
    SearchTrend,
    SocialSignal,
)
from app.db.partitions import ensure_monthly_partition

YOUNG_DAYS = 90


def _snapshot_deltas(session: Session, day: datetime.date) -> dict[Any, tuple[int, int]]:
    """Sum of (favorites, reviews) deltas vs the previous snapshot day,
    grouped by niche."""
    prev = day - datetime.timedelta(days=1)
    today_s = (
        select(
            Listing.niche_id.label("nid"),
            func.sum(func.coalesce(ListingSnapshot.favorites_count, 0)).label("fav"),
            func.sum(func.coalesce(ListingSnapshot.review_count, 0)).label("rev"),
        )
        .join(Listing, Listing.id == ListingSnapshot.listing_id)
        .where(ListingSnapshot.date == day, Listing.niche_id.is_not(None))
        .group_by(Listing.niche_id)
    ).subquery()
    prev_s = (
        select(
            Listing.niche_id.label("nid"),
            func.sum(func.coalesce(ListingSnapshot.favorites_count, 0)).label("fav"),
            func.sum(func.coalesce(ListingSnapshot.review_count, 0)).label("rev"),
        )
        .join(Listing, Listing.id == ListingSnapshot.listing_id)
        .where(ListingSnapshot.date == prev, Listing.niche_id.is_not(None))
        .group_by(Listing.niche_id)
    ).subquery()
    rows = session.execute(
        select(
            today_s.c.nid,
            today_s.c.fav - func.coalesce(prev_s.c.fav, 0),
            today_s.c.rev - func.coalesce(prev_s.c.rev, 0),
        ).join(prev_s, prev_s.c.nid == today_s.c.nid, isouter=True)
    ).all()
    return {r[0]: (int(r[1]), int(r[2])) for r in rows}


def compute_niche_daily_signals(session: Session, day: datetime.date | None = None) -> int:
    day = day or datetime.date.today()
    ensure_monthly_partition(session.connection(), "niche_daily_signals", day)
    deltas = _snapshot_deltas(session, day)

    base = session.execute(
        select(
            Listing.niche_id,
            func.count(Listing.id),
            func.count(Listing.id).filter(
                cast(Listing.listing_created_at, Date) > day - datetime.timedelta(days=YOUNG_DAYS)
            ),
            func.percentile_cont(0.5).within_group(Listing.price_usd),
            func.percentile_cont(0.75).within_group(Listing.price_usd)
            - func.percentile_cont(0.25).within_group(Listing.price_usd),
            func.count(Listing.id).filter(
                cast(Listing.listing_created_at, Date) == day  # created today = new listing
            ),
        )
        .where(Listing.niche_id.is_not(None), Listing.status == "active")
        .group_by(Listing.niche_id)
    ).all()

    rows: list[dict[str, Any]] = []
    for nid, active, young, med, iqr, new in base:
        # HHI over shop share of active listings (supply concentration proxy)
        shares = session.scalars(
            select(func.count(Listing.id))
            .where(Listing.niche_id == nid, Listing.status == "active")
            .group_by(Listing.shop_id)
        ).all()
        hhi = sum((s / active) ** 2 for s in shares) if active else None

        top20 = session.scalar(
            select(func.percentile_cont(0.5).within_group(Listing.favorites_count)).select_from(
                select(Listing.favorites_count)
                .where(Listing.niche_id == nid, Listing.favorites_count.is_not(None))
                .order_by(Listing.favorites_count.desc())
                .limit(20)
                .subquery()
            )
        )

        social = session.execute(
            select(
                func.coalesce(func.sum(SocialSignal.mentions), 0),
                func.coalesce(func.sum(SocialSignal.engagement), 0),
            ).where(SocialSignal.niche_id == nid, SocialSignal.date == day)
        ).one()

        interest = session.scalar(
            select(func.avg(SearchTrend.interest))
            .join(NicheKeyword, NicheKeyword.keyword_id == SearchTrend.keyword_id)
            .where(NicheKeyword.niche_id == nid, SearchTrend.date == day)
        )

        fav_delta, rev_delta = deltas.get(nid, (0, 0))
        rows.append(
            {
                "niche_id": nid,
                "date": day,
                "active_listings": int(active),
                "new_listings": int(new),
                "median_price": med,
                "price_iqr": iqr,
                "favorites_delta": fav_delta,
                "reviews_delta": rev_delta,
                "hhi": hhi,
                "top20_median_reviews": top20,
                "young_listing_share": (young / active) if active else None,
                "search_interest": float(interest) if interest is not None else None,
                "social_mentions": int(social[0]),
                "social_engagement": int(social[1]),
            }
        )

    if rows:
        stmt = pg_insert(NicheDailySignal).values(rows)
        session.execute(
            stmt.on_conflict_do_update(
                index_elements=["niche_id", "date"],
                set_={
                    c: getattr(stmt.excluded, c) for c in rows[0] if c not in ("niche_id", "date")
                },
            )
        )
        session.commit()
    return len(rows)
