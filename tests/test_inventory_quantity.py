"""Unit tests for app/core/utils/inventory_quantity.py — pure Decimal helpers with no DB
dependency. `quantity_to_api_str` is what every route serializes on-hand quantity through,
and `assert_movement_unit_matches_item_canonical` is the last-line check that stops a
ledger row from drifting onto a different unit than its item — both need their edge
branches proven, not just the happy path already exercised indirectly elsewhere.
"""

from decimal import Decimal

import pytest

from app.core.utils.inventory_quantity import (
    assert_movement_unit_matches_item_canonical,
    coerce_stored_quantity,
    parse_stored_quantity_to_decimal,
    quantity_to_api_str,
)

# --- coerce_stored_quantity ---------------------------------------------------------------


def test_coerce_stored_quantity_none_becomes_zero():
    assert coerce_stored_quantity(None) == Decimal("0")


def test_coerce_stored_quantity_quantizes_to_four_places():
    assert coerce_stored_quantity("1.23456") == Decimal("1.2346")


def test_coerce_stored_quantity_rejects_non_finite():
    with pytest.raises(ValueError):
        coerce_stored_quantity("NaN")
    with pytest.raises(ValueError):
        coerce_stored_quantity("Infinity")


def test_coerce_stored_quantity_rejects_huge_exponent():
    """A finite value that cannot be quantized to 4dp within the default context raises
    ValueError rather than letting InvalidOperation escape as an unhandled 500."""
    with pytest.raises(ValueError):
        coerce_stored_quantity("1e400")


# --- quantity_to_api_str -------------------------------------------------------------------


def test_quantity_to_api_str_none_is_zero_string():
    assert quantity_to_api_str(None) == "0"


def test_quantity_to_api_str_trims_trailing_zeros():
    assert quantity_to_api_str(Decimal("1.2300")) == "1.23"


def test_quantity_to_api_str_whole_number_drops_decimal_point():
    assert quantity_to_api_str(Decimal("1.0000")) == "1"


def test_quantity_to_api_str_zero_stays_zero():
    assert quantity_to_api_str(Decimal("0.0000")) == "0"


def test_quantity_to_api_str_non_finite_falls_back_to_zero():
    assert quantity_to_api_str(Decimal("NaN")) == "0"
    assert quantity_to_api_str(Decimal("Infinity")) == "0"


def test_quantity_to_api_str_unparseable_value_falls_back_to_zero():
    assert quantity_to_api_str("not-a-number") == "0"


# --- assert_movement_unit_matches_item_canonical -------------------------------------------


def test_assert_movement_unit_matches_item_canonical_passes_when_equal():
    # Must not raise.
    assert_movement_unit_matches_item_canonical("kg", "kg")


def test_assert_movement_unit_matches_item_canonical_is_case_and_whitespace_normalized():
    assert_movement_unit_matches_item_canonical(" KG ", "kg")


def test_assert_movement_unit_matches_item_canonical_raises_on_mismatch():
    with pytest.raises(ValueError, match="Ledger unit must match"):
        assert_movement_unit_matches_item_canonical("g", "kg")


# --- parse_stored_quantity_to_decimal -------------------------------------------------------


def test_parse_stored_quantity_to_decimal_none_is_zero():
    assert parse_stored_quantity_to_decimal(None) == Decimal("0")


def test_parse_stored_quantity_to_decimal_passes_through_decimal():
    d = Decimal("3.5")
    assert parse_stored_quantity_to_decimal(d) is d


def test_parse_stored_quantity_to_decimal_parses_legacy_string():
    assert parse_stored_quantity_to_decimal("7.25") == Decimal("7.25")


def test_parse_stored_quantity_to_decimal_unparseable_string_is_zero():
    assert parse_stored_quantity_to_decimal("garbage") == Decimal("0")


def test_parse_stored_quantity_to_decimal_non_finite_string_is_zero():
    """The finite check only runs on the parse-from-string path — an already-Decimal value
    is returned as-is (see the isinstance branch above), so this must be exercised via a
    string, not a pre-built Decimal("NaN")."""
    assert parse_stored_quantity_to_decimal("NaN") == Decimal("0")
    assert parse_stored_quantity_to_decimal("Infinity") == Decimal("0")
