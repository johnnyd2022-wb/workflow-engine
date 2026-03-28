"""Inventory on-hand quantity: DB type alignment (NUMERIC), API strings, coercion."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

# Matches PostgreSQL inventory_items.quantity NUMERIC(18,4).
# Rounding policy: half-up at four decimal places (same as convert_quantity_decimal after unit conversion).
STORAGE_QUANTIZE_EXP = Decimal("0.0001")


def coerce_stored_quantity(value: object) -> Decimal:
    """Parse API/user input into a Decimal quantized for NUMERIC(18,4)."""
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        d = value
    else:
        try:
            d = Decimal(str(value).strip())
        except (InvalidOperation, ValueError, TypeError) as e:
            raise ValueError(f"Invalid quantity: {value!r}") from e
    if not d.is_finite():
        raise ValueError("Quantity must be finite")
    return d.quantize(STORAGE_QUANTIZE_EXP, rounding=ROUND_HALF_UP)


def quantity_to_api_str(value: object | None) -> str:
    """Serialize quantity for JSON APIs (avoid Decimal jsonify issues).

    Contract: values are full-precision Decimals/NUMERIC in memory and in the DB; JSON strings trim
    trailing zeros after fixed-point formatting (e.g. 1.2300 → "1.23", 1.0000 → "1"). Callers must
    not infer storage precision from the number of decimal digits in the string alone.
    """
    if value is None:
        return "0"
    try:
        if isinstance(value, Decimal):
            d = value
        else:
            d = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        return "0"
    if not d.is_finite():
        return "0"
    s = format(d, "f").rstrip("0").rstrip(".")
    return s if s else "0"


def parse_stored_quantity_to_decimal(value: object | None) -> Decimal:
    """Read DB/API value as Decimal (handles Decimal or string legacy)."""
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    try:
        d = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")
    return d if d.is_finite() else Decimal("0")
