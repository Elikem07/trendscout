"""Demand and competition subscores (M3.T2, M3.T3).

Everything operates on a per category cross section: one row per niche,
columns of raw metrics for a given day (already smoothed where noted).
Normalization is percentile rank WITHIN the category so scores answer
"relative to its peers", never absolute magnitudes. Count-like metrics
pass through log1p first so one mega niche cannot flatten the field.
Weights are fixed constants of the algo version; changing them means a
new ALGO_VERSION.
"""

import pandas as pd

from app.scoring.preprocess import log_scale, percentile_rank

DEMAND_WEIGHTS = {
    "engagement_velocity": 0.25,  # (favorites+reviews delta)/active listing, smoothed
    "search_interest": 0.20,
    "review_velocity": 0.20,
    "social_engagement": 0.15,
    "social_breadth": 0.10,  # distinct mention volume
    "demand_level": 0.10,  # top20 median favorites: proven appetite
}

COMPETITION_WEIGHTS = {
    "listing_count": 0.25,
    "young_listing_share": 0.20,  # rivals racing in
    "new_listing_velocity": 0.20,
    "price_compression": 0.15,  # low IQR/median = commoditized
    "concentration": 0.10,  # high HHI = entrenched incumbents
    "review_moat": 0.10,  # top listings' review head start
}

LOG_SCALED = {
    "engagement_velocity",
    "review_velocity",
    "social_engagement",
    "social_breadth",
    "demand_level",
    "listing_count",
    "new_listing_velocity",
    "review_moat",
}


def _weighted_percentiles(
    raw: pd.DataFrame, weights: dict[str, float]
) -> tuple[pd.Series, pd.DataFrame]:
    """Returns (composite 0-100, per metric percentile frame). Missing
    metrics redistribute their weight across present ones per row."""
    pct = pd.DataFrame(index=raw.index)
    for metric in weights:
        col = raw[metric] if metric in raw else pd.Series(index=raw.index, dtype=float)
        scaled = log_scale(col) if metric in LOG_SCALED else col
        pct[metric] = percentile_rank(scaled)

    weight_row = pd.Series(weights)
    present = pct.notna()
    effective = present.mul(weight_row, axis=1)
    denom = effective.sum(axis=1)
    composite = (pct.fillna(0) * effective).sum(axis=1) / denom.replace(0, pd.NA)
    return composite.astype(float), pct


def demand_scores(raw: pd.DataFrame) -> tuple[pd.Series, pd.DataFrame]:
    return _weighted_percentiles(raw, DEMAND_WEIGHTS)


def competition_scores(raw: pd.DataFrame) -> tuple[pd.Series, pd.DataFrame]:
    return _weighted_percentiles(raw, COMPETITION_WEIGHTS)
