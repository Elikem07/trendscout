"""Niche revenue estimates as ranges, never point values (M3.T6).

monthly_revenue ~= reviews_delta_30d / review_rate * median_price
Review rate band 0.20-0.25 (reviews per order, Etsy handmade heuristic;
documented uncertainty is the product's honesty contract). Returns None
when the inputs cannot support an estimate.
"""

from decimal import Decimal

REVIEW_RATE_LOW = Decimal("0.20")  # divisor high bound -> revenue high bound
REVIEW_RATE_HIGH = Decimal("0.25")


def revenue_range(
    reviews_delta_30d: int, median_price: Decimal | None
) -> tuple[Decimal, Decimal] | None:
    if median_price is None or median_price <= 0 or reviews_delta_30d <= 0:
        return None
    orders_low = Decimal(reviews_delta_30d) / REVIEW_RATE_HIGH
    orders_high = Decimal(reviews_delta_30d) / REVIEW_RATE_LOW
    low = (orders_low * median_price).quantize(Decimal("1"))
    high = (orders_high * median_price).quantize(Decimal("1"))
    return low, high
