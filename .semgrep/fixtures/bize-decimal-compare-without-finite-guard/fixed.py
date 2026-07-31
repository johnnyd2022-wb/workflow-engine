"""is_finite() checked before any ordering comparison."""

from decimal import Decimal


def check_quantity(raw):
    value = Decimal(str(raw))
    if not value.is_finite():
        raise ValueError("quantity must be finite")
    if value >= 0:
        return value
    raise ValueError("quantity must be non-negative")
