"""Backtest harness (M3.T7): does 'emerging' actually lead demand?

Replays the scoring engine day by day over historical (or synthetic)
niche_daily_signals, then measures: of niches labeled emerging on day t,
what fraction saw their engagement proxy grow >= GROWTH_TARGET within
LOOKAHEAD days (hit rate), and how early the first emerging call came
relative to each niche's realized peak growth (lead time).

Run: make backtest (synthetic dataset; swap in real data by pointing at
a database with history). Output: JSON report to stdout.
"""

import datetime
import json
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.models import Niche, NicheDailySignal, Score
from app.db.partitions import ensure_monthly_partition
from app.ids import uuid7
from app.scoring.engine import compute_scores

LOOKAHEAD_DAYS = 14
GROWTH_TARGET = 0.30  # engagement +30% within lookahead = a hit


@dataclass
class BacktestResult:
    days_replayed: int
    emerging_calls: int
    hits: int
    hit_rate: float | None
    median_lead_days: float | None
    niches: int


def _engagement(session: Session, niche_id: Any, day: datetime.date) -> float:
    row = session.get(NicheDailySignal, (niche_id, day))
    if row is None or not row.active_listings:
        return 0.0
    return (row.favorites_delta + row.reviews_delta) / max(1, row.active_listings)


def replay(session: Session, start: datetime.date, end: datetime.date) -> BacktestResult:
    calls: list[tuple[Any, datetime.date]] = []
    day = start
    replayed = 0
    while day <= end:
        compute_scores(session, day)
        for s in session.scalars(
            select(Score).where(Score.date == day, Score.trend_label == "emerging")
        ):
            calls.append((s.niche_id, day))
        replayed += 1
        day += datetime.timedelta(days=1)

    hits = 0
    leads: list[int] = []
    first_call: dict[Any, datetime.date] = {}
    for niche_id, call_day in calls:
        first_call.setdefault(niche_id, call_day)
        base = _engagement(session, niche_id, call_day)
        horizon = call_day + datetime.timedelta(days=LOOKAHEAD_DAYS)
        future = _engagement(session, niche_id, min(horizon, end))
        if base > 0 and (future - base) / base >= GROWTH_TARGET:
            hits += 1
            leads.append((min(horizon, end) - call_day).days)

    n_niches = session.scalar(select(text("count(*)")).select_from(Niche)) or 0
    return BacktestResult(
        days_replayed=replayed,
        emerging_calls=len(calls),
        hits=hits,
        hit_rate=round(hits / len(calls), 3) if calls else None,
        median_lead_days=float(np.median(leads)) if leads else None,
        niches=int(n_niches),
    )


def seed_synthetic(session: Session, days: int = 45) -> None:
    """Three archetypes x3 replicas: true breakout (ramp that keeps
    going), false alarm (spike that fades), steady control."""
    today = datetime.date.today()
    start = today - datetime.timedelta(days=days - 1)
    ensure_monthly_partition(session.connection(), "niche_daily_signals", start)
    ensure_monthly_partition(session.connection(), "niche_daily_signals", today)
    rng = np.random.default_rng(7)

    def series(kind: str, i: int) -> list[float]:
        base = 8.0 + i
        if kind == "breakout":
            ramp_at = 20 + 2 * i
            return [base if d < ramp_at else base + 3.0 * (d - ramp_at) for d in range(days)]
        if kind == "false_alarm":
            spike_at = 22 + i
            return [base + (30.0 if spike_at <= d < spike_at + 3 else 0.0) for d in range(days)]
        return [base] * days

    for kind in ("breakout", "false_alarm", "steady"):
        for i in range(3):
            niche = Niche(id=uuid7(), label=f"{kind}-{i}", slug=f"{kind}-{i}", category="synthetic")
            session.add(niche)
            session.flush()
            for d, favs in enumerate(series(kind, i)):
                noisy = max(0, favs + rng.normal(0, 0.5))
                session.add(
                    NicheDailySignal(
                        niche_id=niche.id,
                        date=start + datetime.timedelta(days=d),
                        active_listings=50,
                        new_listings=0,
                        median_price=25.0,
                        price_iqr=8.0,
                        favorites_delta=int(noisy),
                        reviews_delta=int(noisy // 4),
                        hhi=0.1,
                        top20_median_reviews=60.0,
                        young_listing_share=0.3,
                        social_mentions=0,
                        social_engagement=0,
                    )
                )
    session.commit()


def main() -> int:
    from app.db.session import get_sessionmaker

    with get_sessionmaker()() as session:
        today = datetime.date.today()
        seed_synthetic(session, days=45)
        result = replay(session, today - datetime.timedelta(days=20), today)
    print(json.dumps(asdict(result), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
