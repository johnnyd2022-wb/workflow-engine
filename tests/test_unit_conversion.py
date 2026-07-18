"""Tests for server-side unit conversion (app/core/utils/unit_conversion.py).

Wastage and execution quantities are converted between units server-side before they touch
inventory (the wastage route calls are_units_compatible / convert_to_inventory_unit_decimal).
The JS side of conversion is tested; these seven server functions were not. Getting a factor
or a compatibility rule wrong here silently mis-states stock, so both the happy conversions
and the refusals matter.
"""

from decimal import Decimal

import pytest

from app.core.utils.unit_conversion import (
    are_units_compatible,
    convert_quantity,
    convert_quantity_decimal,
    convert_to_inventory_unit_decimal,
)

# --- compatibility --------------------------------------------------------------------


def test_same_category_units_are_compatible():
    assert are_units_compatible("kg", "g") is True
    assert are_units_compatible("L", "mL") is True
    assert are_units_compatible("m", "cm") is True


def test_units_are_matched_case_insensitively():
    assert are_units_compatible("KG", "g") is True


def test_different_categories_are_incompatible():
    assert are_units_compatible("kg", "L") is False
    assert are_units_compatible("m", "kg") is False


def test_count_units_must_match_exactly():
    assert are_units_compatible("units", "units") is True
    # Different count units are not interconvertible even though both are counts.
    assert are_units_compatible("units", "pcs") is False


# --- float conversion -----------------------------------------------------------------


def test_convert_quantity_mass_and_volume():
    assert convert_quantity(1, "kg", "g") == 1000.0
    assert convert_quantity(1000, "g", "kg") == 1.0
    assert convert_quantity(1, "L", "mL") == 1000.0


def test_convert_quantity_same_unit_is_identity():
    assert convert_quantity(5, "kg", "kg") == 5


def test_convert_quantity_incompatible_raises():
    with pytest.raises(ValueError, match="incompatible"):
        convert_quantity(1, "kg", "L")


# --- decimal conversion (storage-aligned) ---------------------------------------------


def test_convert_decimal_is_exact_and_quantized():
    # 1 kg -> g is exact; result is quantized to the 4dp storage precision.
    result = convert_quantity_decimal(Decimal("1"), "kg", "g")
    assert result == Decimal("1000")
    assert result.as_tuple().exponent == -4  # storage-aligned NUMERIC(18,4)


def test_convert_decimal_rounds_half_up_to_four_places():
    # 1 kg -> lb = 1 / 0.453592 = 2.204623..., quantized ROUND_HALF_UP to 4dp.
    assert convert_quantity_decimal(Decimal("1"), "kg", "lb") == Decimal("2.2046")


def test_convert_decimal_incompatible_raises():
    with pytest.raises(ValueError, match="incompatible"):
        convert_quantity_decimal(Decimal("1"), "mL", "g")


def test_convert_to_inventory_unit_decimal_delegates():
    # Convenience wrapper used by the wastage route: mL into an L-based inventory item.
    assert convert_to_inventory_unit_decimal(Decimal("500"), "mL", "L") == Decimal("0.5")
