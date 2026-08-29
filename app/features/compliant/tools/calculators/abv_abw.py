"""Alcohol by volume <-> alcohol by weight, given the solution's specific gravity.

abw_pct = abv_pct * ETHANOL_DENSITY_20C_G_PER_ML / solution_sg
abv_pct = abw_pct * solution_sg / ETHANOL_DENSITY_20C_G_PER_ML
"""

from __future__ import annotations

from app.features.compliant.modules.nz_alcohol.constants import ETHANOL_DENSITY_20C_G_PER_ML
from app.features.compliant.tools.calculators._validate import required_number, solve_target
from app.features.compliant.tools.errors import CalculatorValidationError

KEY = "abv_abw"
TITLE = "ABV ↔ ABW"
CATEGORY = "general"
SOURCES = ["Standard alcoholometry (mass/volume fraction; OIML R22 density basis)"]
DISCLAIMER = "First-order density relation; use a measured method for tax or label ABV rather than this conversion."


def solve(payload: dict) -> dict:
    target = solve_target(payload, "solve_for", ["abw_pct", "abv_pct"], "abw_pct")
    solution_sg = required_number(payload, "solution_sg", exclusive_min=0.7, exclusive_max=1.1)

    if target == "abw_pct":
        abv_pct = required_number(payload, "abv_pct", minimum=0, maximum=100)
        abw_pct = abv_pct * ETHANOL_DENSITY_20C_G_PER_ML / solution_sg
        if not 0.0 <= abw_pct <= 100.0:
            raise CalculatorValidationError("solving for abw_pct produced a value outside 0-100 — check inputs")
    else:  # abv_pct
        abw_pct = required_number(payload, "abw_pct", minimum=0, maximum=100)
        abv_pct = abw_pct * solution_sg / ETHANOL_DENSITY_20C_G_PER_ML
        if not 0.0 <= abv_pct <= 100.0:
            raise CalculatorValidationError("solving for abv_pct produced a value outside 0-100 — check inputs")

    return {
        "solved_field": target,
        "abv_pct": abv_pct,
        "abw_pct": abw_pct,
        "solution_sg": solution_sg,
        "disclaimer": DISCLAIMER,
        "sources": SOURCES,
    }
