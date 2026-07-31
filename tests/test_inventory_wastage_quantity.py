"""Unit tests for app/core/utils/inventory_wastage_quantity.py — pure parsing/hashing
helpers, no DB dependency.

`wastage_entries_payload_hash` is the idempotency contract (AC17): two submissions of the
same logical batch must hash identically regardless of entry order, or a client retry that
happens to reorder entries would be treated as a different payload and get a spurious 409
instead of a safe replay.
"""

from decimal import Decimal
from uuid import uuid4

from app.core.utils.inventory_wastage_quantity import (
    MAX_WASTAGE_MAGNITUDE,
    parse_wastage_quantity,
    parse_wastage_unit_field,
    quantize_wastage_quantity,
    wastage_entries_payload_hash,
)

# --- quantize_wastage_quantity --------------------------------------------------------------


def test_quantize_wastage_quantity_rounds_to_four_places():
    assert quantize_wastage_quantity(Decimal("1.23456")) == Decimal("1.2346")


# --- parse_wastage_unit_field ----------------------------------------------------------------


def test_parse_wastage_unit_field_none_is_none_no_error():
    unit, err = parse_wastage_unit_field(None)
    assert unit is None
    assert err is None


def test_parse_wastage_unit_field_normalizes_case_and_whitespace():
    unit, err = parse_wastage_unit_field("  KG  ")
    assert unit == "kg"
    assert err is None


def test_parse_wastage_unit_field_rejects_non_string():
    unit, err = parse_wastage_unit_field(123)
    assert unit is None
    assert err == "quantity_unit must be a string when provided"


def test_parse_wastage_unit_field_blank_string_becomes_none():
    unit, err = parse_wastage_unit_field("   ")
    assert unit is None
    assert err is None


# --- parse_wastage_quantity ------------------------------------------------------------------


def test_parse_wastage_quantity_accepts_positive_value():
    d, err = parse_wastage_quantity("3.5")
    assert err is None
    assert d == Decimal("3.5000")


def test_parse_wastage_quantity_rejects_non_numeric():
    d, err = parse_wastage_quantity("not-a-number")
    assert d is None
    assert err == "quantity_wasted must be a number"


def test_parse_wastage_quantity_rejects_non_finite():
    d, err = parse_wastage_quantity("NaN")
    assert d is None
    assert err == "quantity_wasted must be a finite number"


def test_parse_wastage_quantity_rejects_negative_zero():
    """Decimal("-0") is zero but signed — the explicit is_zero()+is_signed() check exists
    so a client sending "-0" gets the same positive-quantity rejection as "0", not a value
    that happens to compare equal to zero but slips past a naive `<= 0` check differently."""
    d, err = parse_wastage_quantity("-0")
    assert d is None
    assert err == "quantity_wasted must be positive"


def test_parse_wastage_quantity_rejects_zero():
    d, err = parse_wastage_quantity("0")
    assert d is None
    assert err == "quantity_wasted must be positive"


def test_parse_wastage_quantity_rejects_negative():
    d, err = parse_wastage_quantity("-5")
    assert d is None
    assert err == "quantity_wasted must be positive"


def test_parse_wastage_quantity_rejects_out_of_range_magnitude():
    too_big = str(MAX_WASTAGE_MAGNITUDE * 2)
    d, err = parse_wastage_quantity(too_big)
    assert d is None
    assert err == "quantity_wasted is out of allowed range"


def test_parse_wastage_quantity_accepts_value_at_the_boundary():
    d, err = parse_wastage_quantity(str(MAX_WASTAGE_MAGNITUDE))
    assert err is None
    assert d == MAX_WASTAGE_MAGNITUDE


# --- wastage_entries_payload_hash (AC17 idempotency contract) --------------------------------


def test_wastage_entries_payload_hash_is_stable_regardless_of_entry_order():
    item_a = str(uuid4())
    item_b = str(uuid4())
    entries_forward = [
        {"inventory_item_id": item_a, "quantity_wasted": Decimal("1"), "reason": "spill"},
        {"inventory_item_id": item_b, "quantity_wasted": Decimal("2"), "reason": "breakage"},
    ]
    entries_reversed = list(reversed(entries_forward))

    assert wastage_entries_payload_hash(entries_forward) == wastage_entries_payload_hash(entries_reversed)


def test_wastage_entries_payload_hash_differs_for_a_different_quantity():
    item_id = str(uuid4())
    base = [{"inventory_item_id": item_id, "quantity_wasted": Decimal("1"), "reason": "spill"}]
    changed = [{"inventory_item_id": item_id, "quantity_wasted": Decimal("2"), "reason": "spill"}]

    assert wastage_entries_payload_hash(base) != wastage_entries_payload_hash(changed)


def test_wastage_entries_payload_hash_accepts_non_decimal_quantity():
    """quantity_wasted arrives as a plain number/string from JSON, not always a Decimal
    instance — the hash must normalize it the same way either way."""
    item_id = str(uuid4())
    as_decimal = [{"inventory_item_id": item_id, "quantity_wasted": Decimal("1.5"), "reason": "x"}]
    as_string = [{"inventory_item_id": item_id, "quantity_wasted": "1.5", "reason": "x"}]

    assert wastage_entries_payload_hash(as_decimal) == wastage_entries_payload_hash(as_string)


def test_wastage_entries_payload_hash_normalizes_missing_quantity_unit():
    """Omitting quantity_unit and sending an empty one must hash identically — both mean
    'same unit as the inventory line'."""
    item_id = str(uuid4())
    without_unit = [{"inventory_item_id": item_id, "quantity_wasted": Decimal("1"), "reason": "x"}]
    with_empty_unit = [
        {"inventory_item_id": item_id, "quantity_wasted": Decimal("1"), "reason": "x", "quantity_unit": None}
    ]

    assert wastage_entries_payload_hash(without_unit) == wastage_entries_payload_hash(with_empty_unit)
