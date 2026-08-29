"""LAL (litres of absolute alcohol) <-> volume + ABV.

lal = volume_l * abv_pct / 100 ; solve whichever of the three is omitted.
"""

from __future__ import annotations

from app.features.compliant.tools.calculators._validate import (
    as_number,
    bounded,
    is_absent,
    one_omitted_of,
)
from app.features.compliant.tools.errors import CalculatorValidationError

KEY = "lal"
TITLE = "Litres of absolute alcohol (LAL)"
CATEGORY = "general"
SOURCES = ["NZ Customs — litres-of-alcohol basis for excise duty"]
DISCLAIMER = (
    "Operational estimate; confirm litres of alcohol for excise using NZ Customs' "
    "official method and your product's measured ABV."
)


def _num(payload: dict, field: str, **bounds) -> float:
    return bounded(as_number(payload[field], field), field, **bounds)


def solve(payload: dict) -> dict:
    target = one_omitted_of(payload, ["volume_l", "abv_pct", "lal"])

    volume_l = None if is_absent(payload, "volume_l") else _num(payload, "volume_l", exclusive_min=0)
    abv_pct = None if is_absent(payload, "abv_pct") else _num(payload, "abv_pct", minimum=0, maximum=100)
    lal = None if is_absent(payload, "lal") else _num(payload, "lal", minimum=0)

    if target == "lal":
        lal = volume_l * abv_pct / 100.0
    elif target == "volume_l":
        if not abv_pct > 0:
            raise CalculatorValidationError("abv_pct must be greater than 0 to solve for volume_l")
        volume_l = lal * 100.0 / abv_pct
    else:  # abv_pct
        if not volume_l > 0:
            raise CalculatorValidationError("volume_l must be greater than 0 to solve for abv_pct")
        abv_pct = lal * 100.0 / volume_l
        if not 0.0 <= abv_pct <= 100.0:
            raise CalculatorValidationError("solving for abv_pct produced a value outside 0-100 — check inputs")

    return {
        "solved_field": target,
        "volume_l": volume_l,
        "abv_pct": abv_pct,
        "lal": lal,
        "disclaimer": DISCLAIMER,
        "sources": SOURCES,
    }
