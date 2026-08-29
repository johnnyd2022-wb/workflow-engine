"""NZ standard drinks <-> volume, given ABV.

standard_drinks = volume_ml * (abv_pct/100) * ETHANOL_DENSITY_20C_G_PER_ML
                  / NZ_STANDARD_DRINK_GRAMS_ETHANOL
"""

from __future__ import annotations

from app.features.compliant.modules.nz_alcohol.constants import (
    ETHANOL_DENSITY_20C_G_PER_ML,
    NZ_STANDARD_DRINK_GRAMS_ETHANOL,
)
from app.features.compliant.tools.calculators._validate import finalise, guarded, required_number, solve_target
from app.features.compliant.tools.errors import CalculatorValidationError

KEY = "standard_drinks"
TITLE = "Standard drinks"
CATEGORY = "general"
SOURCES = [
    "FSANZ Standard 2.7.1",
    "Health New Zealand — standard drink = 10 g ethanol",
]
DISCLAIMER = (
    "Verify and round label standard-drink statements per the Australia New Zealand "
    "Food Standards Code (Standard 2.7.1) before printing."
)


@guarded
def solve(payload: dict) -> dict:
    target = solve_target(payload, "solve_for", ["standard_drinks", "volume_ml"], "standard_drinks")

    if target == "standard_drinks":
        volume_ml = required_number(payload, "volume_ml", exclusive_min=0)
        abv_pct = required_number(payload, "abv_pct", minimum=0, maximum=100)
        standard_drinks = volume_ml * (abv_pct / 100.0) * ETHANOL_DENSITY_20C_G_PER_ML / NZ_STANDARD_DRINK_GRAMS_ETHANOL
    else:  # volume_ml
        standard_drinks = required_number(payload, "standard_drinks", minimum=0)
        abv_pct = required_number(payload, "abv_pct", minimum=0, maximum=100)
        if not abv_pct > 0:
            raise CalculatorValidationError("abv_pct must be greater than 0 to solve for volume_ml")
        volume_ml = standard_drinks * NZ_STANDARD_DRINK_GRAMS_ETHANOL / (ETHANOL_DENSITY_20C_G_PER_ML * abv_pct / 100.0)

    return finalise(
        {
            "solved_field": target,
            "volume_ml": volume_ml,
            "abv_pct": abv_pct,
            "standard_drinks": standard_drinks,
            "disclaimer": DISCLAIMER,
            "sources": SOURCES,
        }
    )
