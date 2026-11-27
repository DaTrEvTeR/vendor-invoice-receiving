"""Decimal precision shared by storage and parsing.

SQLite stores DECIMAL columns with NUMERIC affinity, which means REAL, and Django
reads them back with 15 significant digits. Capping every decimal column at
15 digits (6 of them after the point) makes each stored value round-trip exactly.
Anything that does not fit is rejected before it reaches the database, because
Django would otherwise round it silently.
"""

from decimal import Decimal, InvalidOperation

MAX_DIGITS = 15
DECIMAL_PLACES = 6

_QUANTUM = Decimal(1).scaleb(-DECIMAL_PLACES)
_LIMIT = Decimal(10) ** (MAX_DIGITS - DECIMAL_PLACES)


def fits_storage(value: Decimal) -> bool:
    """True when `value` can be stored without any rounding."""
    if not value.is_finite() or abs(value) >= _LIMIT:
        return False
    try:
        return value == value.quantize(_QUANTUM)
    except InvalidOperation:
        return False


def plain(value: Decimal) -> str:
    """Plain decimal text without exponent or trailing zeros: 6, 370, 38.879346, -92.5."""
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def money(value: Decimal) -> str:
    """Money for messages: at least two decimals (4200.00), more only when present (1866.208608)."""
    cents = value.quantize(Decimal("0.01"))
    return format(cents, "f") if cents == value else plain(value)
