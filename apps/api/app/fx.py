"""Currency conversion to USD. Static table at MVP (refreshed manually);
the interface stays stable when a live FX source replaces it. Decimal in,
Decimal out: money never touches binary floats."""

from decimal import Decimal

RATES_TO_USD: dict[str, Decimal] = {
    "USD": Decimal("1.0"),
    "EUR": Decimal("1.09"),
    "GBP": Decimal("1.27"),
    "CAD": Decimal("0.73"),
    "AUD": Decimal("0.66"),
    "JPY": Decimal("0.0067"),
    "MXN": Decimal("0.055"),
    "INR": Decimal("0.012"),
}


def to_usd(amount: Decimal, currency: str) -> Decimal | None:
    rate = RATES_TO_USD.get(currency.upper())
    if rate is None:
        return None
    return (amount * rate).quantize(Decimal("0.01"))
