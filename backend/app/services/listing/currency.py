"""
Multi-currency support — P1-6.

Supported currencies: JOD, SAR, AED.
All internal prices stored in listing's native currency cents.
Exchange rates are approximate fixed rates for the GCC/Jordan corridor
(updated via admin or external API in production).

JOD is the base currency. Rates express how many units of target
currency equal 1 JOD:
  1 JOD ≈ 5.15 SAR
  1 JOD ≈ 5.19 AED
"""

from __future__ import annotations

import logging
from decimal import Decimal, ROUND_HALF_UP

logger = logging.getLogger(__name__)

# Fixed exchange rates: 1 JOD = X units of target currency
# These should be updated periodically from a rate provider
_RATES_FROM_JOD: dict[str, Decimal] = {
    "JOD": Decimal("1.000"),
    "SAR": Decimal("5.150"),
    "AED": Decimal("5.190"),
}


def get_exchange_rate(from_currency: str, to_currency: str) -> Decimal:
    """Get exchange rate from one currency to another.

    Returns the multiplier: amount_in_from * rate = amount_in_to.
    """
    from_currency = from_currency.upper()
    to_currency = to_currency.upper()

    if from_currency == to_currency:
        return Decimal("1.000")

    # Convert via JOD as base
    from_to_jod = Decimal("1") / _RATES_FROM_JOD[from_currency]
    jod_to_target = _RATES_FROM_JOD[to_currency]
    return (from_to_jod * jod_to_target).quantize(Decimal("0.000001"))


def convert_amount(
    amount: int,
    from_currency: str,
    to_currency: str,
) -> int:
    """Convert an amount in cents from one currency to another.

    Returns amount in cents of the target currency, rounded to nearest integer.
    """
    if from_currency == to_currency:
        return amount

    rate = get_exchange_rate(from_currency, to_currency)
    converted = Decimal(amount) * rate
    return int(converted.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def convert_to_jod(amount: int, currency: str) -> int:
    """Convenience: convert any supported currency amount to JOD cents."""
    return convert_amount(amount, currency, "JOD")


def format_currency(amount_cents: int, currency: str) -> str:
    """Format cents amount for display (e.g., 1500 JOD -> '1.500 JOD')."""
    currency = currency.upper()
    # JOD uses 3 decimal places (fils), SAR/AED use 2 (halalah/fils)
    if currency == "JOD":
        formatted = f"{amount_cents / 1000:.3f}"
    else:
        formatted = f"{amount_cents / 100:.2f}"
    return f"{formatted} {currency}"


def get_supported_currencies() -> list[dict]:
    """Return list of supported currencies with metadata."""
    return [
        {
            "code": "JOD",
            "name_en": "Jordanian Dinar",
            "name_ar": "دينار أردني",
            "symbol": "د.ا",
            "decimal_places": 3,
            "subunit": 1000,
        },
        {
            "code": "SAR",
            "name_en": "Saudi Riyal",
            "name_ar": "ريال سعودي",
            "symbol": "ر.س",
            "decimal_places": 2,
            "subunit": 100,
        },
        {
            "code": "AED",
            "name_en": "UAE Dirham",
            "name_ar": "درهم إماراتي",
            "symbol": "د.إ",
            "decimal_places": 2,
            "subunit": 100,
        },
    ]
