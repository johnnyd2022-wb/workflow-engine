"""Convert between specific gravity, degrees Plato, degrees Brix and degrees Baume.

Provide exactly one unit; all four are returned. SG is the pivot.
SG -> Plato: ASBC cubic. Plato/Brix -> SG: bisection on the cubic. Baume: modulus 145.
Per the "bounds constrain caller-provided values only" rule, a derived output may fall
outside another unit's input range and that is not an error.
"""

from __future__ import annotations

from app.features.compliant.tools.calculators._validate import as_number, bounded, finalise, guarded, one_provided_of
from app.features.compliant.tools.errors import CalculatorValidationError

KEY = "gravity_convert"
TITLE = "Gravity unit converter"
CATEGORY = "beer"
SOURCES = [
    "ASBC Methods of Analysis (SG↔°Plato cubic)",
    "Standard hydrometry (Baumé, modulus 145)",
]
DISCLAIMER = (
    "°Brix is treated as equal to °Plato (an approximation diverging ~0.3 at high "
    "gravity); SG↔°Plato uses the ASBC cubic."
)

_BISECTION_ITERATIONS = 60
_SG_LO, _SG_HI = 1.000, 1.150


def _plato_from_sg(sg: float) -> float:
    return -616.868 + 1111.14 * sg - 630.272 * sg**2 + 135.997 * sg**3


def _sg_from_plato(plato: float) -> float:
    lo, hi = _SG_LO, _SG_HI
    if not _plato_from_sg(lo) <= plato <= _plato_from_sg(hi):
        raise CalculatorValidationError("value not representable")
    for _ in range(_BISECTION_ITERATIONS):
        mid = (lo + hi) / 2.0
        if _plato_from_sg(mid) < plato:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


@guarded
def solve(payload: dict) -> dict:
    given = one_provided_of(payload, ["sg", "plato", "brix", "baume"])

    if given == "sg":
        sg = bounded(as_number(payload["sg"], "sg"), "sg", minimum=1.0, maximum=1.15)
    elif given in ("plato", "brix"):
        value = bounded(as_number(payload[given], given), given, minimum=0, maximum=33)
        sg = _sg_from_plato(value)
    else:  # baume
        baume_in = bounded(as_number(payload["baume"], "baume"), "baume", minimum=0, maximum=18)
        sg = 145.0 / (145.0 - baume_in)

    plato = _plato_from_sg(sg)
    return finalise(
        {
            "sg": sg,
            "plato": plato,
            "brix": plato,
            "baume": 145.0 - 145.0 / sg,
            "disclaimer": DISCLAIMER,
            "sources": SOURCES,
        }
    )
