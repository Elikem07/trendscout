"""Opportunity formula, momentum multiplier, confidence (M3.T4).

opportunity = 100 * (D/100)^0.6 * (1 - C/100)^0.4 * momentum * confidence

Geometric blend: strong demand cannot fully buy back brutal competition,
and empty niches with no demand stay low. Momentum rewards demand
outrunning supply, clamped so it can nudge, never dominate.
"""

DEMAND_EXP = 0.6
COMPETITION_EXP = 0.4
MOMENTUM_SENSITIVITY = 0.5
MOMENTUM_FLOOR, MOMENTUM_CEIL = 0.8, 1.3
CONFIDENCE_FLOOR = 0.75


def momentum_multiplier(demand_growth: float, supply_growth: float) -> float:
    raw = 1.0 + MOMENTUM_SENSITIVITY * (demand_growth - supply_growth)
    return max(MOMENTUM_FLOOR, min(MOMENTUM_CEIL, raw))


def confidence(days_of_history: int, non_null_signal_share: float) -> float:
    """0.75-1.0. Thin history or missing signal families cap the score's
    reach rather than silently pretending certainty."""
    history_term = min(days_of_history / 28.0, 1.0)
    coverage = 0.5 * history_term + 0.5 * max(0.0, min(1.0, non_null_signal_share))
    return CONFIDENCE_FLOOR + (1.0 - CONFIDENCE_FLOOR) * coverage


def opportunity(demand: float, competition: float, momentum: float, conf: float) -> float:
    d = max(0.0, min(100.0, demand)) / 100.0
    c = max(0.0, min(100.0, competition)) / 100.0
    base = 100.0 * (d**DEMAND_EXP) * ((1.0 - c) ** COMPETITION_EXP)
    return float(round(base * momentum * conf, 2))
