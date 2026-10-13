"""M3 scoring engine: pure function goldens, engine end to end with four
persona niches, feed membership."""

import datetime

import pandas as pd
import pytest
from sqlalchemy import select, text

from app.db.models import Niche, NicheDailySignal, RevenueEstimate, Score
from app.db.partitions import ensure_monthly_partition
from app.db.session import get_engine, get_sessionmaker
from app.ids import uuid7
from app.scoring import ALGO_VERSION
from app.scoring.engine import compute_scores
from app.scoring.feeds import feed
from app.scoring.labels import last_change_point_age, trend_label
from app.scoring.opportunity import confidence, momentum_multiplier, opportunity
from app.scoring.preprocess import clip_outliers, pct_growth, prepare
from app.scoring.revenue import revenue_range

TODAY = datetime.date.today()
DAYS = 28


# ---------- pure function goldens ----------


def test_outlier_clip_tames_single_spike() -> None:
    s = pd.Series([10.0] * 20 + [500.0] + [10.0] * 7)
    clipped = clip_outliers(s)
    assert clipped.max() == pytest.approx(10.0)  # spike fully clipped to band


def test_pct_growth_windows() -> None:
    s = pd.Series([10.0] * 7 + [20.0] * 7)
    assert pct_growth(s) == pytest.approx(1.0)
    assert pct_growth(pd.Series([5.0] * 3)) == 0.0  # too short


def test_momentum_multiplier_clamps() -> None:
    assert momentum_multiplier(0.2, 0.0) == pytest.approx(1.1)
    assert momentum_multiplier(5.0, 0.0) == 1.3
    assert momentum_multiplier(-5.0, 0.0) == 0.8
    assert momentum_multiplier(0.1, 0.1) == pytest.approx(1.0)


def test_opportunity_golden_values() -> None:
    assert opportunity(100, 0, 1.0, 1.0) == 100.0
    assert opportunity(0, 0, 1.0, 1.0) == 0.0
    # D=80, C=40: 100 * .8^.6 * .6^.4 = 71.30
    assert opportunity(80, 40, 1.0, 1.0) == pytest.approx(71.30, abs=0.01)
    assert opportunity(80, 40, 1.2, 1.0) == pytest.approx(85.57, abs=0.01)


def test_confidence_bounds() -> None:
    assert confidence(0, 0.0) == 0.75
    assert confidence(28, 1.0) == 1.0
    assert confidence(14, 0.5) == pytest.approx(0.875)


def test_revenue_range_golden_and_refusal() -> None:
    from decimal import Decimal

    r = revenue_range(60, Decimal("25.00"))
    assert r is not None
    low, high = r
    assert low == Decimal("6000")  # 60/0.25*25
    assert high == Decimal("7500")  # 60/0.20*25
    assert revenue_range(0, Decimal("25.00")) is None
    assert revenue_range(60, None) is None


def test_change_point_detects_recent_inflection() -> None:
    flat = [10.0] * 20
    ramp = [10.0 + 6 * i for i in range(1, 9)]
    age = last_change_point_age(pd.Series(flat + ramp))
    assert age is not None and age <= 21


def test_trend_label_priorities() -> None:
    ramp = prepare(pd.Series([10.0] * 20 + [10.0 + 6 * i for i in range(1, 9)]))
    assert trend_label(ramp, 50, 30, 1.2) == "emerging"
    assert trend_label(ramp, 70, 80, 0.85) == "saturated"  # saturation wins
    flat = prepare(pd.Series([10.0] * 28))
    assert trend_label(flat, 50, 50, 1.0) == "flat"
    rising = prepare(pd.Series([float(10 + i) for i in range(28)]))
    assert trend_label(rising, 50, 50, 1.05) == "rising"


# ---------- engine end to end ----------


@pytest.fixture
def clean() -> None:
    with get_engine().begin() as conn:
        conn.execute(
            text("TRUNCATE scores, revenue_estimates, niche_daily_signals, niches CASCADE")
        )


def seed_niche(label: str, series: list[dict[str, object]]) -> object:
    with get_sessionmaker()() as s:
        niche = Niche(id=uuid7(), label=label, slug=label, category="home_decor")
        s.add(niche)
        s.flush()
        ensure_monthly_partition(s.connection(), "niche_daily_signals", TODAY)
        ensure_monthly_partition(
            s.connection(), "niche_daily_signals", TODAY - datetime.timedelta(days=DAYS)
        )
        for i, row in enumerate(series):
            s.add(
                NicheDailySignal(
                    niche_id=niche.id,
                    date=TODAY - datetime.timedelta(days=DAYS - 1 - i),
                    **row,
                )
            )
        s.commit()
        return niche.id


def days(
    active: list[int],
    favs: list[int],
    price: float = 30.0,
    young: float = 0.3,
    hhi: float = 0.1,
    top20: float = 50.0,
    reviews: list[int] | None = None,
) -> list[dict[str, object]]:
    reviews = reviews or [max(1, f // 4) for f in favs]
    return [
        {
            "active_listings": active[i],
            "new_listings": max(0, active[i] - active[i - 1]) if i else 0,
            "median_price": price,
            "price_iqr": price * 0.4,
            "favorites_delta": favs[i],
            "reviews_delta": reviews[i],
            "hhi": hhi,
            "top20_median_reviews": top20,
            "young_listing_share": young,
            "search_interest": None,
            "social_mentions": 0,
            "social_engagement": 0,
        }
        for i in range(DAYS)
    ]


def four_personas() -> dict[str, object]:
    # A emerging: modest supply, engagement inflects up hard at day 18
    a = seed_niche(
        "emerging-a",
        days(
            active=[40] * DAYS,
            favs=[8] * 18 + [8 + 14 * i for i in range(1, 11)],
        ),
    )
    # B saturated: huge crowded supply growing fast, high absolute engagement
    # but decaying, crowded young listings
    b = seed_niche(
        "saturated-b",
        days(
            active=[400 + 12 * i for i in range(DAYS)],
            favs=[400 - 8 * i for i in range(DAYS)],
            young=0.8,
            hhi=0.02,
            top20=900.0,
            price=18.0,
        ),
    )
    # C flat: mid everything
    c = seed_niche("flat-c", days(active=[100] * DAYS, favs=[30] * DAYS))
    # D hot: strong steady engagement, supply stable, low-mid competition
    d = seed_niche(
        "hot-d",
        days(
            active=[60] * DAYS,
            favs=[150 + 2 * i for i in range(DAYS)],
            top20=400.0,
            young=0.2,
        ),
    )
    return {"a": a, "b": b, "c": c, "d": d}


def test_engine_scores_personas_and_feeds(clean: None) -> None:
    ids = four_personas()
    with get_sessionmaker()() as s:
        written = compute_scores(s, TODAY)
        assert written == 4
        rows = {r.niche_id: r for r in s.scalars(select(Score).where(Score.date == TODAY)).all()}
        a, b, c, d = (rows[ids[k]] for k in "abcd")

        assert all(r.algo_version == ALGO_VERSION for r in rows.values())
        assert a.trend_label == "emerging"
        assert a.momentum > 1.1
        assert b.competition > c.competition  # crowded beats mid
        assert b.momentum < 1.0  # demand decaying vs supply growth
        assert a.opportunity > c.opportunity  # inflecting beats flat
        assert d.demand >= 70  # strong engagement percentile
        assert 0.75 <= a.confidence <= 1.0
        assert a.subscores["demand"]["engagement_velocity"] is not None

        # feeds (A1)
        emerging_ids = {r.niche_id for r in feed(s, "emerging", TODAY)}
        assert ids["a"] in emerging_ids
        trending_ids = {r.niche_id for r in feed(s, "trending", TODAY)}
        assert ids["a"] in trending_ids
        hot_ids = {r.niche_id for r in feed(s, "hot_now", TODAY)}
        assert ids["d"] in hot_ids
        assert ids["b"] not in hot_ids
        with pytest.raises(ValueError, match="unknown feed"):
            feed(s, "nope", TODAY)

        # revenue estimates exist with low < high
        rev = s.get(RevenueEstimate, (ids["d"], TODAY))
        assert rev is not None and float(rev.low_usd) < float(rev.high_usd)


def test_engine_rerun_is_idempotent_overwrite(clean: None) -> None:
    four_personas()
    with get_sessionmaker()() as s:
        assert compute_scores(s, TODAY) == 4
        assert compute_scores(s, TODAY) == 4
        n = s.execute(text("SELECT count(*) FROM scores WHERE date = :d"), {"d": TODAY}).scalar()
        assert n == 4


def test_backtest_harness_on_synthetic(clean: None) -> None:
    """Breakout archetypes must be caught; harness math must hold."""
    from app.scoring.backtest import replay, seed_synthetic

    with get_sessionmaker()() as s:
        seed_synthetic(s, days=45)
        result = replay(s, TODAY - datetime.timedelta(days=14), TODAY - datetime.timedelta(days=7))
    assert result.days_replayed == 8
    assert result.niches == 9
    assert result.emerging_calls > 0  # breakouts get called
    assert result.hits <= result.emerging_calls
    if result.hit_rate is not None:
        assert 0.0 <= result.hit_rate <= 1.0
