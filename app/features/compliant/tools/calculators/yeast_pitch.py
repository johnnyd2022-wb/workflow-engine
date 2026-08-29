"""Yeast cells required and pack count for a target pitching rate.

cells_required_billion = pitch_rate_m_per_ml_per_p * volume_l * gravity_plato
  (rate is million cells / mL / °P; volume_l * 1000 mL, then / 1000 to billions)
packs = ceil(cells_required_billion / pack_billion)
"""

from __future__ import annotations

import math

from app.features.compliant.tools.calculators._validate import finalise, guarded, is_absent, required_number

KEY = "yeast_pitch"
TITLE = "Yeast pitch rate"
CATEGORY = "beer"
SOURCES = ['White & Zainasheff, "Yeast" (pitching-rate model)']
DISCLAIMER = "Assumes 100% viability; adjust for yeast age and a starter."

_DEFAULT_PACK_BILLION = 100.0


@guarded
def solve(payload: dict) -> dict:
    volume_l = required_number(payload, "volume_l", exclusive_min=0)
    gravity_plato = required_number(payload, "gravity_plato", exclusive_min=0, maximum=40)
    pitch_rate = required_number(payload, "pitch_rate_m_per_ml_per_p", exclusive_min=0, maximum=5)
    pack_billion = (
        _DEFAULT_PACK_BILLION
        if is_absent(payload, "pack_billion")
        else required_number(payload, "pack_billion", exclusive_min=0)
    )

    cells_required_billion = pitch_rate * volume_l * gravity_plato
    return finalise(
        {
            "cells_required_billion": cells_required_billion,
            "packs": math.ceil(cells_required_billion / pack_billion),
            "pack_billion": pack_billion,
            "disclaimer": DISCLAIMER,
            "sources": SOURCES,
        }
    )
