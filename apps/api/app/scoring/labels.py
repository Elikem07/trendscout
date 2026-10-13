"""Trend labels via change point detection (M3.T5 + amendment A1).

Labels: emerging | rising | declining | flat | saturated.
Priority: saturated -> emerging -> rising/declining -> flat.
- emerging: PELT change point within EMERGING_WINDOW days AND momentum
  multiplier > 1.1 (demand inflected upward recently, supply lagging)
- saturated: demand >= 60, momentum < 0.9, competition > 75
- rising/declining: smoothed demand proxy moved >15% over 14 days
"""

import numpy as np
import pandas as pd
import ruptures as rpt

EMERGING_WINDOW_DAYS = 21
SLOPE_WINDOW_DAYS = 14
SLOPE_THRESHOLD = 0.15
PELT_PENALTY = 3.0
PELT_MIN_SIZE = 5


def last_change_point_age(series: pd.Series) -> int | None:
    """Days since the most recent PELT change point; None if none found
    or series too short."""
    if len(series) < 2 * PELT_MIN_SIZE:
        return None
    values = series.astype(float).to_numpy().reshape(-1, 1)
    algo = rpt.Pelt(model="rbf", min_size=PELT_MIN_SIZE).fit(values)
    breaks = algo.predict(pen=PELT_PENALTY)
    internal = [b for b in breaks if b < len(series)]  # drop the end marker
    if not internal:
        return None
    return int(len(series) - internal[-1])


def slope_pct(series: pd.Series, window: int = SLOPE_WINDOW_DAYS) -> float:
    """Relative change across the trailing window of the smoothed series."""
    if len(series) < window:
        return 0.0
    windowed = series.iloc[-window:].astype(float)
    start, end = float(windowed.iloc[0]), float(windowed.iloc[-1])
    if start == 0:
        return 0.0 if end == 0 else np.inf
    return (end - start) / abs(start)


def trend_label(
    demand_series_smoothed: pd.Series,
    demand: float,
    competition: float,
    momentum: float,
) -> str:
    if demand >= 60 and momentum < 0.9 and competition > 75:
        return "saturated"
    cp_age = last_change_point_age(demand_series_smoothed)
    if cp_age is not None and cp_age <= EMERGING_WINDOW_DAYS and momentum > 1.1:
        return "emerging"
    s = slope_pct(demand_series_smoothed)
    if s > SLOPE_THRESHOLD:
        return "rising"
    if s < -SLOPE_THRESHOLD:
        return "declining"
    return "flat"
