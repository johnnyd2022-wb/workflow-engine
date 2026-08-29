"""How many full kegs a finished volume yields, accounting for per-fill loss.

Source draw per full keg = keg_size_l * (1 + fill_loss_pct/100).
"""

from __future__ import annotations

import math

from app.features.compliant.tools.calculators._validate import is_absent, required_number

KEY = "keg_fill"
TITLE = "Keg fill"
CATEGORY = "vessel"
SOURCES = ["Arithmetic (integer packaging with proportional fill loss)"]
DISCLAIMER = "Estimate; real fill loss depends on line length, foaming and temperature."


def solve(payload: dict) -> dict:
    available_l = required_number(payload, "available_l", exclusive_min=0)
    keg_size_l = required_number(payload, "keg_size_l", exclusive_min=0)
    fill_loss_pct = (
        0.0 if is_absent(payload, "fill_loss_pct") else required_number(payload, "fill_loss_pct", minimum=0, maximum=50)
    )

    per_keg_draw = keg_size_l * (1.0 + fill_loss_pct / 100.0)
    full_kegs = math.floor(available_l / per_keg_draw)
    packaged_l = full_kegs * keg_size_l
    loss_l = full_kegs * keg_size_l * fill_loss_pct / 100.0

    return {
        "full_kegs": full_kegs,
        "packaged_l": packaged_l,
        "loss_l": loss_l,
        "remainder_l": available_l - packaged_l - loss_l,
        "disclaimer": DISCLAIMER,
        "sources": SOURCES,
    }
