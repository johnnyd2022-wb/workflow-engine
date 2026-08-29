"""Dilution calculator: solve any one of (starting ABV, starting volume, final ABV,
final volume) given the other three, plus how much water to actually pour in.

Relocated verbatim from app/features/dilution_calculator/services/dilution_service.py —
maths, validation, error messages and payload are unchanged (see
.agents/specs/dilution_calculator.md "Calculation model"). Only the module location and
the exception base class changed (now a `CalculatorValidationError` so the shared tools
dispatch route handles it uniformly); `DilutionValidationError` remains as an alias and
every message is byte-identical to the pre-move service.

Two distinct pieces of physics live here, and they must not be conflated:

1. The (a, b, c, d) relationship itself is an *exact* identity
   (`starting_abv * starting_volume_ml = final_abv * final_volume_ml`), a direct
   consequence of ethanol mass conservation and the standard %ABV(v/v) definition. No
   density/contraction model enters it — any attempt to "correct" it with one is a bug.
2. `water_to_add_ml` — how much water, measured on its own, must be poured in — is where
   contraction genuinely applies, via mass balance over an approximate mixture-density
   model.
"""

from __future__ import annotations

import math

from app.features.compliant.tools.errors import CalculatorValidationError

KEY = "dilution"
TITLE = "Dilution / proofing down"
CATEGORY = "general"
SOURCES = ["Dilution calculator spec (.agents/specs/dilution_calculator.md), Calculation model"]

ABV_FIELDS = frozenset({"starting_abv", "final_abv"})
VOLUME_FIELDS = frozenset({"starting_volume_ml", "final_volume_ml"})
FIELD_NAMES = ABV_FIELDS | VOLUME_FIELDS

_BISECTION_ITERATIONS = 60  # fixed and deterministic — far beyond float64 precision

DISCLAIMER = (
    "water_to_add_ml uses an approximate ethanol-water mixture density model (not "
    "OIML-certified legal-metrology data). Verify against a hydrometer before relying "
    "on it for regulatory label ABV compliance."
)


class DilutionValidationError(CalculatorValidationError):
    """Backwards-compatible alias; message text is unchanged from the pre-move service."""


def _is_finite_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _mixture_density(mass_fraction: float) -> float:
    """rho_mix(w) in g/mL, w = ethanol mass fraction. Engineering approximation, 20C
    reference — see the spec's Calculation model for the source and caveats.
    """
    return 1.0 - 0.207 * mass_fraction - 0.005 * mass_fraction * mass_fraction


_RHO_ETHANOL_PURE = _mixture_density(1.0)  # self-consistent reference, not an external constant
_RHO_WATER_PURE = _mixture_density(0.0)


def _abv_from_mass_fraction(w: float) -> float:
    return 100.0 * w * _mixture_density(w) / _RHO_ETHANOL_PURE


def _mass_fraction_for_abv(abv_pct: float) -> float:
    """Invert _abv_from_mass_fraction via bisection. Exact at the boundaries so the
    solver never runs at abv_pct == 0 or 100.
    """
    if abv_pct <= 0.0:
        return 0.0
    if abv_pct >= 100.0:
        return 1.0

    lo, hi = 0.0, 1.0
    for _ in range(_BISECTION_ITERATIONS):
        mid = (lo + hi) / 2.0
        if _abv_from_mass_fraction(mid) < abv_pct:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def _validate_and_extract(payload: dict) -> tuple[str, dict[str, float]]:
    if not isinstance(payload, dict):
        raise DilutionValidationError("Request body must be a JSON object")

    solve_for = payload.get("solve_for")
    if not isinstance(solve_for, str) or solve_for not in FIELD_NAMES:
        raise DilutionValidationError(f"solve_for must be one of: {', '.join(sorted(FIELD_NAMES))}")

    if payload.get(solve_for) is not None:
        raise DilutionValidationError(f"'{solve_for}' must be omitted or null — it is the value being solved for")

    given: dict[str, float] = {}
    for field in FIELD_NAMES - {solve_for}:
        value = payload.get(field)
        if value is None:
            raise DilutionValidationError(f"'{field}' is required")
        if not _is_finite_number(value):
            raise DilutionValidationError(f"'{field}' must be a finite number")
        value = float(value)
        if field in ABV_FIELDS and not (0.0 <= value <= 100.0):
            raise DilutionValidationError(f"'{field}' must be between 0 and 100")
        if field in VOLUME_FIELDS and not (value > 0.0):
            raise DilutionValidationError(f"'{field}' must be greater than 0")
        given[field] = value

    return solve_for, given


def _check_dilution_direction(solve_for: str, given: dict[str, float]) -> None:
    """AC5: one rule, checked on whichever pair is fully known pre-solve. Adding water can
    only lower ABV and raise volume, so a request implying otherwise is rejected before
    any division happens.
    """
    if solve_for in VOLUME_FIELDS:
        if given["final_abv"] >= given["starting_abv"]:
            raise DilutionValidationError("final_abv must be less than starting_abv")
        if solve_for == "final_volume_ml" and given["final_abv"] == 0.0:
            raise DilutionValidationError("final_abv must be greater than 0 to solve for final_volume_ml")
    else:
        if given["final_volume_ml"] <= given["starting_volume_ml"]:
            raise DilutionValidationError("final_volume_ml must be greater than starting_volume_ml")


def _solve_value(solve_for: str, given: dict[str, float]) -> float:
    if solve_for == "final_volume_ml":
        return given["starting_abv"] * given["starting_volume_ml"] / given["final_abv"]
    if solve_for == "final_abv":
        return given["starting_abv"] * given["starting_volume_ml"] / given["final_volume_ml"]
    if solve_for == "starting_volume_ml":
        return given["final_abv"] * given["final_volume_ml"] / given["starting_abv"]
    return given["final_abv"] * given["final_volume_ml"] / given["starting_volume_ml"]  # starting_abv


def solve(payload: dict) -> dict:
    """Validate `payload` and return the full result dict, or raise DilutionValidationError."""
    solve_for, given = _validate_and_extract(payload)
    _check_dilution_direction(solve_for, given)

    solved_value = _solve_value(solve_for, given)

    if not math.isfinite(solved_value):
        raise DilutionValidationError(f"solving for '{solve_for}' produced a non-finite value — check inputs")
    if solve_for in ABV_FIELDS and not (0.0 <= solved_value <= 100.0):
        raise DilutionValidationError(f"solving for '{solve_for}' produced a value outside 0-100 — check inputs")
    if solve_for in VOLUME_FIELDS and not (solved_value > 0.0):
        raise DilutionValidationError(f"solving for '{solve_for}' produced a non-positive volume — check inputs")

    resolved = dict(given)
    resolved[solve_for] = solved_value

    w_start = _mass_fraction_for_abv(resolved["starting_abv"])
    w_final = _mass_fraction_for_abv(resolved["final_abv"])
    mass_start_g = resolved["starting_volume_ml"] * _mixture_density(w_start)
    mass_final_g = resolved["final_volume_ml"] * _mixture_density(w_final)
    water_to_add_ml = (mass_final_g - mass_start_g) / _RHO_WATER_PURE
    water_to_add_naive_ml = resolved["final_volume_ml"] - resolved["starting_volume_ml"]

    return {
        "solved_field": solve_for,
        "solved_value": solved_value,
        "starting_abv": resolved["starting_abv"],
        "starting_volume_ml": resolved["starting_volume_ml"],
        "final_abv": resolved["final_abv"],
        "final_volume_ml": resolved["final_volume_ml"],
        "water_to_add_ml": water_to_add_ml,
        "water_to_add_naive_ml": water_to_add_naive_ml,
        "disclaimer": DISCLAIMER,
    }


# Backwards-compatible name used by the pre-move API route and its tests.
solve_dilution = solve
