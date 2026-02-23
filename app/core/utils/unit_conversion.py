"""Unit conversion utilities for inventory and execution quantities"""

from decimal import Decimal

# Unit conversion factors to base units
# Base units: kg (mass), L (volume), m (length), units (count)
# All keys are lowercase for case-insensitive matching
CONVERSION_FACTORS = {
    # Mass conversions (to kg)
    "kg": 1.0,
    "g": 0.001,
    "mg": 0.000001,
    "lb": 0.453592,
    "oz": 0.0283495,
    "ton": 1000.0,
    "tonne": 1000.0,
    # Volume conversions (to L)
    "l": 1.0,
    "ml": 0.001,
    "gal": 3.78541,
    "m3": 1000.0,
    "ft3": 28.3168,
    # Length conversions (to m)
    "m": 1.0,
    "cm": 0.01,
    "mm": 0.001,
    "ft": 0.3048,
    "in": 0.0254,
    # Count units (no conversion, must match exactly)
    "units": None,
    "pcs": None,
    "pieces": None,
    "boxes": None,
    "pallets": None,
    "containers": None,
}

# Display labels for UI (dropdowns, etc.). Keys must match CONVERSION_FACTORS.
# Single source of truth: add new units here and in CONVERSION_FACTORS together.
UNIT_DISPLAY_LABELS = {
    "kg": "Kilograms (kg)",
    "g": "Grams (g)",
    "mg": "Milligrams (mg)",
    "lb": "Pounds (lb)",
    "oz": "Ounces (oz)",
    "ton": "Ton (ton)",
    "tonne": "Tonne",
    "l": "Liters (L)",
    "ml": "Milliliters (mL)",
    "gal": "Gallons (gal)",
    "m3": "Cubic meters (m³)",
    "ft3": "Cubic feet (ft³)",
    "m": "Meters (m)",
    "cm": "Centimeters (cm)",
    "mm": "Millimeters (mm)",
    "ft": "Feet (ft)",
    "in": "Inches (in)",
    "units": "Units",
    "pcs": "Pieces",
    "pieces": "Pieces",
    "boxes": "Boxes",
    "pallets": "Pallets",
    "containers": "Containers",
}

# Ensure units and labels stay in sync (fail fast if someone adds a unit but forgets a label)
assert set(UNIT_DISPLAY_LABELS) == set(CONVERSION_FACTORS), (
    "UNIT_DISPLAY_LABELS and CONVERSION_FACTORS must have the same keys. "
    "Missing or extra keys in UNIT_DISPLAY_LABELS."
)

# Unit categories (all lowercase for case-insensitive matching)
MASS_UNITS = {"kg", "g", "mg", "lb", "oz", "ton", "tonne"}
VOLUME_UNITS = {"l", "ml", "gal", "m3", "ft3"}
LENGTH_UNITS = {"m", "cm", "mm", "ft", "in"}
COUNT_UNITS = {"units", "pcs", "pieces", "boxes", "pallets", "containers"}


def normalize_unit(unit: str) -> str:
    """Normalize unit string (lowercase, strip whitespace)"""
    if not unit:
        return ""
    return unit.strip().lower()


def are_units_compatible(unit1: str, unit2: str) -> bool:
    """Check if two units are compatible (can be converted between)"""
    u1 = normalize_unit(unit1)
    u2 = normalize_unit(unit2)

    if u1 == u2:
        return True

    # Check if both are in the same category
    if u1 in MASS_UNITS and u2 in MASS_UNITS:
        return True
    if u1 in VOLUME_UNITS and u2 in VOLUME_UNITS:
        return True
    if u1 in LENGTH_UNITS and u2 in LENGTH_UNITS:
        return True
    if u1 in COUNT_UNITS and u2 in COUNT_UNITS:
        # For count units, they must match exactly
        return u1 == u2

    return False


def convert_quantity(quantity: float, from_unit: str, to_unit: str) -> float:
    """
    Convert a quantity from one unit to another.

    Args:
        quantity: The quantity to convert
        from_unit: Source unit
        to_unit: Target unit

    Returns:
        Converted quantity

    Raises:
        ValueError: If units are not compatible or conversion is not possible
    """
    from_unit_norm = normalize_unit(from_unit)
    to_unit_norm = normalize_unit(to_unit)

    if from_unit_norm == to_unit_norm:
        return quantity

    # Check compatibility
    if not are_units_compatible(from_unit, to_unit):
        raise ValueError(f"Cannot convert between incompatible units: {from_unit} and {to_unit}")

    # Handle count units (must match exactly)
    if from_unit_norm in COUNT_UNITS:
        if from_unit_norm != to_unit_norm:
            raise ValueError(f"Count units must match exactly: {from_unit} != {to_unit}")
        return quantity

    # Get conversion factors
    from_factor = CONVERSION_FACTORS.get(from_unit_norm)
    to_factor = CONVERSION_FACTORS.get(to_unit_norm)

    if from_factor is None or to_factor is None:
        raise ValueError(f"Unknown unit(s): {from_unit} or {to_unit}")

    # Convert to base unit, then to target unit
    base_quantity = quantity * from_factor
    converted_quantity = base_quantity / to_factor

    return converted_quantity


def convert_to_inventory_unit(quantity: float, quantity_unit: str, inventory_unit: str) -> float:
    """
    Convert a quantity to match the inventory item's unit.
    This is a convenience function that handles the common case of converting
    execution quantities to inventory units.

    Args:
        quantity: The quantity to convert
        quantity_unit: Unit of the quantity
        inventory_unit: Unit of the inventory item

    Returns:
        Converted quantity in inventory_unit

    Raises:
        ValueError: If units are not compatible
    """
    return convert_quantity(quantity, quantity_unit, inventory_unit)


def convert_quantity_decimal(quantity: Decimal, from_unit: str, to_unit: str) -> Decimal:
    """
    Convert a quantity from one unit to another using Decimal-only math.
    Use this for reconciliation, compliance, and audited inventory to avoid
    floating-point boundary issues.

    Args:
        quantity: The quantity to convert (Decimal)
        from_unit: Source unit
        to_unit: Target unit

    Returns:
        Converted quantity (Decimal)

    Raises:
        ValueError: If units are not compatible or conversion is not possible
    """
    from_unit_norm = normalize_unit(from_unit)
    to_unit_norm = normalize_unit(to_unit)

    if from_unit_norm == to_unit_norm:
        return quantity

    if not are_units_compatible(from_unit, to_unit):
        raise ValueError(f"Cannot convert between incompatible units: {from_unit} and {to_unit}")

    if from_unit_norm in COUNT_UNITS:
        if from_unit_norm != to_unit_norm:
            raise ValueError(f"Count units must match exactly: {from_unit} != {to_unit}")
        return quantity

    from_factor = CONVERSION_FACTORS.get(from_unit_norm)
    to_factor = CONVERSION_FACTORS.get(to_unit_norm)
    if from_factor is None or to_factor is None:
        raise ValueError(f"Unknown unit(s): {from_unit} or {to_unit}")

    # Decimal-only path: factors as Decimal to avoid float boundary
    from_f = Decimal(str(from_factor))
    to_f = Decimal(str(to_factor))
    base_quantity = quantity * from_f
    converted_quantity = base_quantity / to_f
    return converted_quantity


def convert_to_inventory_unit_decimal(quantity: Decimal, quantity_unit: str, inventory_unit: str) -> Decimal:
    """
    Convert a quantity to the inventory item's unit using Decimal-only math.
    Use for reconciliation and anywhere precision must be preserved.

    Args:
        quantity: The quantity to convert (Decimal)
        quantity_unit: Unit of the quantity
        inventory_unit: Unit of the inventory item

    Returns:
        Converted quantity in inventory_unit (Decimal)

    Raises:
        ValueError: If units are not compatible
    """
    return convert_quantity_decimal(quantity, quantity_unit, inventory_unit)
