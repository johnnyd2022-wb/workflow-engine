"""Calculator registry + catalogue for the Compliant Tools suite.

``CALCULATORS`` maps a calculator key to its solver module. ``CATALOGUE`` is the exact
JSON payload served at ``GET /api/compliant/tools`` — loaded from ``catalogue.json``
(the canonical copy of the spec's Appendix A). Import-time checks keep the two in sync:
every catalogue key must have a solver module and vice versa.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable

from app.features.compliant.tools.calculators import (
    abv_abw,
    abv_from_og_fg,
    dilution,
    gravity_convert,
    keg_fill,
    lal,
    standard_drinks,
    tank_volume,
    yeast_pitch,
    yield_loss,
)

_MODULES = (
    dilution,
    lal,
    standard_drinks,
    abv_abw,
    gravity_convert,
    abv_from_og_fg,
    tank_volume,
    yield_loss,
    yeast_pitch,
    keg_fill,
)

CALCULATORS: dict[str, Callable[[dict], dict]] = {m.KEY: m.solve for m in _MODULES}

_CATALOGUE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "catalogue.json")
with open(_CATALOGUE_PATH, encoding="utf-8") as _fh:
    CATALOGUE: dict = json.load(_fh)

_catalogue_keys = [entry["key"] for entry in CATALOGUE["calculators"]]
if set(_catalogue_keys) != set(CALCULATORS):
    raise RuntimeError(
        f"catalogue.json keys {sorted(_catalogue_keys)} do not match solver modules {sorted(CALCULATORS)}"
    )
