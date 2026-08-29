"""Vertical cylindrical tank volume, optionally with a cone bottom (apex down).

fill_height_m is measured from the very bottom (cone apex, or the flat base).
"""

from __future__ import annotations

import math

from app.features.compliant.tools.calculators._validate import is_absent, required_number
from app.features.compliant.tools.errors import CalculatorValidationError

KEY = "tank_volume"
TITLE = "Tank volume"
CATEGORY = "vessel"
SOURCES = ["Solid geometry (cylinder + right circular cone)"]
DISCLAIMER = "Nominal cylinder+cone geometry; ignores dished heads, wall thickness and fittings."

_M3_TO_L = 1000.0


def solve(payload: dict) -> dict:
    diameter_m = required_number(payload, "diameter_m", exclusive_min=0)
    cyl_height_m = required_number(payload, "cyl_height_m", exclusive_min=0)
    cone_height_m = 0.0 if is_absent(payload, "cone_height_m") else required_number(payload, "cone_height_m", minimum=0)
    fill_height_m = required_number(payload, "fill_height_m", minimum=0)

    r = diameter_m / 2.0
    cyl_full = math.pi * r**2 * cyl_height_m
    cone_full = (1.0 / 3.0) * math.pi * r**2 * cone_height_m
    capacity_l = (cyl_full + cone_full) * _M3_TO_L

    if fill_height_m > cone_height_m + cyl_height_m:
        raise CalculatorValidationError("fill_height_m exceeds tank height")

    if fill_height_m == 0.0:
        filled_l = 0.0
    elif cone_height_m == 0.0:
        filled_l = math.pi * r**2 * fill_height_m * _M3_TO_L
    elif fill_height_m <= cone_height_m:
        sub_r = r * fill_height_m / cone_height_m
        filled_l = (1.0 / 3.0) * math.pi * sub_r**2 * fill_height_m * _M3_TO_L
    else:
        filled_l = (cone_full + math.pi * r**2 * (fill_height_m - cone_height_m)) * _M3_TO_L

    return {
        "capacity_l": capacity_l,
        "filled_l": filled_l,
        "headspace_l": capacity_l - filled_l,
        "disclaimer": DISCLAIMER,
        "sources": SOURCES,
    }
