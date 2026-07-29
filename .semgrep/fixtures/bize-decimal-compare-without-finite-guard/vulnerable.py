"""Ordering-comparing a Decimal parsed inline from client input, with no finiteness guard."""

from decimal import Decimal


def check_quantity(raw):
    value = Decimal(str(raw))
    # Decimal("NaN") >= 0 raises InvalidOperation, which is NOT a ValueError — so a caller
    # that only catches ValueError returns an unlogged 500 instead of a 400.
    if value >= 0:
        return value
    raise ValueError("quantity must be non-negative")
