"""Series hygiene before any scoring math (M3.T1).

Robust z (MAD) outlier clipping, then 7 day rolling smoothing. STL
seasonal removal applies only when the series is long enough to support
it (>= 28 points); short series degrade gracefully to smoothing only.
Deterministic: same input, same output, no randomness.
"""

import numpy as np
import pandas as pd

MAD_Z_CLIP = 3.5
SMOOTH_WINDOW = 7
STL_MIN_POINTS = 28


def clip_outliers(series: pd.Series, z: float = MAD_Z_CLIP) -> pd.Series:
    """Clip points beyond `z` robust standard deviations (MAD based).
    A single crawler glitch day cannot move weekly momentum."""
    values = series.astype(float)
    median = values.median()
    mad = (values - median).abs().median()
    if mad == 0:
        # Degenerate MAD (majority constant). Regime changes are real
        # signal here, so fall back to generous IQR fences; only a truly
        # constant-with-spikes series collapses to the median.
        q25, q75 = values.quantile(0.25), values.quantile(0.75)
        iqr = q75 - q25
        if iqr == 0:
            return values.clip(lower=median, upper=median)
        return values.clip(lower=q25 - 3 * iqr, upper=q75 + 3 * iqr)
    robust_sigma = 1.4826 * mad
    lower, upper = median - z * robust_sigma, median + z * robust_sigma
    return values.clip(lower=lower, upper=upper)


def smooth(series: pd.Series, window: int = SMOOTH_WINDOW) -> pd.Series:
    return series.rolling(window=window, min_periods=1).mean()


def deseasonalize(series: pd.Series) -> pd.Series:
    """Remove weekly seasonality via STL when there is enough history."""
    if len(series) < STL_MIN_POINTS:
        return series
    from statsmodels.tsa.seasonal import STL

    result = STL(series.astype(float), period=7, robust=True).fit()
    out: pd.Series = series.astype(float) - result.seasonal
    return out


def prepare(series: pd.Series) -> pd.Series:
    """Full pipeline: clip -> deseasonalize -> smooth."""
    return smooth(deseasonalize(clip_outliers(series)))


def pct_growth(series: pd.Series, window: int = 7) -> float:
    """Relative growth of the last `window` mean vs the prior `window`
    mean. Returns 0.0 when there is not enough history or a zero base."""
    if len(series) < 2 * window:
        return 0.0
    recent = float(series.iloc[-window:].mean())
    prior = float(series.iloc[-2 * window : -window].mean())
    if prior == 0:
        return 0.0
    return (recent - prior) / abs(prior)


def percentile_rank(values: pd.Series) -> pd.Series:
    """0-100 percentile rank within the peer group (NaN safe)."""
    return values.rank(pct=True, na_option="keep") * 100


def log_scale(values: pd.Series) -> pd.Series:
    return np.log1p(values.clip(lower=0))
