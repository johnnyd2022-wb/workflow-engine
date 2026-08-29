"""Estimate ABV and apparent attenuation from original and final gravity.

abv_pct = (og_sg - fg_sg) * 131.25
apparent_attenuation_pct = (og_sg - fg_sg) / (og_sg - 1.0) * 100
"""

from __future__ import annotations

from app.features.compliant.tools.calculators._validate import required_number
from app.features.compliant.tools.errors import CalculatorValidationError

KEY = "abv_from_og_fg"
TITLE = "ABV from OG & FG"
CATEGORY = "beer"
SOURCES = ['Standard craft-brewing reference (Palmer, "How to Brew") — the ×131.25 approximation']
DISCLAIMER = "The ×131.25 approximation; for tax or label ABV use a measured method rather than a gravity estimate."

_ABV_FACTOR = 131.25


def solve(payload: dict) -> dict:
    og_sg = required_number(payload, "og_sg", exclusive_min=1.0, maximum=1.2)
    fg_sg = required_number(payload, "fg_sg", minimum=0.98, maximum=1.1)
    if og_sg <= fg_sg:
        raise CalculatorValidationError("og_sg must be greater than fg_sg")

    return {
        "abv_pct": (og_sg - fg_sg) * _ABV_FACTOR,
        "apparent_attenuation_pct": (og_sg - fg_sg) / (og_sg - 1.0) * 100.0,
        "og_sg": og_sg,
        "fg_sg": fg_sg,
        "disclaimer": DISCLAIMER,
        "sources": SOURCES,
    }
