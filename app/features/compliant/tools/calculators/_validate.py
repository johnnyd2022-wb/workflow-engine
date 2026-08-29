"""Shared input-validation helpers for the calculator solvers.

These enforce the "Shared solver rules" in .agents/specs/compliant_tools.md: finite
non-bool numbers, missing-required messages, and the `solve` shapes
(`one_omitted_of` / `one_provided_of` / explicit `solve_for`).
"""

from __future__ import annotations

import functools
import math
from collections.abc import Callable, Iterable
from typing import Any

from app.features.compliant.tools.errors import CalculatorValidationError

_MISSING = object()

_OUT_OF_RANGE_MSG = "input magnitudes produced a result outside the representable range — check your values"


def finalise(result: dict) -> dict:
    """Last-line guard: reject a result carrying any non-finite number (inf/nan).

    Individual inputs are range-checked, but a product/quotient of two in-range extremes
    can still overflow to inf or underflow a divisor to 0. Every solver pipes its return
    dict through this so such a case surfaces as a clean 400, never an ``Infinity`` in the
    JSON body or a 500 from a downstream ``int()`` / ``math.ceil``.
    """

    def _check(value: Any) -> None:
        if isinstance(value, bool):
            return
        if isinstance(value, (int, float)) and not math.isfinite(value):
            raise CalculatorValidationError(_OUT_OF_RANGE_MSG)
        if isinstance(value, list):
            for item in value:
                _check(item)
        elif isinstance(value, dict):
            for item in value.values():
                _check(item)

    _check(result)
    return result


def guarded(solve: Callable[[dict], dict]) -> Callable[[dict], dict]:
    """Decorator: turn an arithmetic blow-up on extreme-but-finite inputs into a clean
    ``CalculatorValidationError`` so the solver contract ("raises CalculatorValidationError")
    holds even when a product overflows or a divisor underflows to zero mid-calculation.
    """

    @functools.wraps(solve)
    def _wrapped(payload: dict) -> dict:
        try:
            return solve(payload)
        except (OverflowError, ZeroDivisionError):
            raise CalculatorValidationError(_OUT_OF_RANGE_MSG) from None

    return _wrapped


def as_number(value: Any, field: str) -> float:
    """Coerce to float, rejecting bool / non-numeric / non-finite. `None` is a caller bug."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CalculatorValidationError(f"'{field}' must be a number")
    if not math.isfinite(value):
        raise CalculatorValidationError(f"'{field}' must be a finite number")
    return float(value)


def is_absent(payload: dict, field: str) -> bool:
    """A key that is missing entirely or explicitly JSON null counts as absent."""
    return payload.get(field, _MISSING) is _MISSING or payload.get(field) is None


def required_number(
    payload: dict,
    field: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
    exclusive_min: float | None = None,
    exclusive_max: float | None = None,
) -> float:
    if is_absent(payload, field):
        raise CalculatorValidationError(f"'{field}' is required")
    return bounded(
        as_number(payload[field], field),
        field,
        minimum=minimum,
        maximum=maximum,
        exclusive_min=exclusive_min,
        exclusive_max=exclusive_max,
    )


def bounded(
    value: float,
    field: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
    exclusive_min: float | None = None,
    exclusive_max: float | None = None,
) -> float:
    if minimum is not None and value < minimum:
        raise CalculatorValidationError(f"'{field}' must be at least {minimum}")
    if maximum is not None and value > maximum:
        raise CalculatorValidationError(f"'{field}' must be at most {maximum}")
    if exclusive_min is not None and value <= exclusive_min:
        raise CalculatorValidationError(f"'{field}' must be greater than {exclusive_min}")
    if exclusive_max is not None and value >= exclusive_max:
        raise CalculatorValidationError(f"'{field}' must be less than {exclusive_max}")
    return value


def one_omitted_of(payload: dict, fields: list[str]) -> str:
    """Exactly one of `fields` absent, the rest present. Return the absent (solved) one."""
    present = [f for f in fields if not is_absent(payload, f)]
    if len(present) != len(fields) - 1:
        raise CalculatorValidationError(f"provide exactly {len(fields) - 1} of: {', '.join(fields)}")
    return next(f for f in fields if is_absent(payload, f))


def one_provided_of(payload: dict, fields: list[str]) -> str:
    """Exactly one of `fields` present, the rest absent. Return the present one."""
    present = [f for f in fields if not is_absent(payload, f)]
    if len(present) != 1:
        raise CalculatorValidationError(f"provide exactly one of: {', '.join(fields)}")
    return present[0]


def solve_target(payload: dict, field: str, enum: Iterable[str], default: str) -> str:
    """Resolve an explicit `solve_for` field; the named target must be absent/null."""
    enum = list(enum)
    raw = payload.get(field, _MISSING)
    if raw is _MISSING or raw is None:
        target = default
    elif raw in enum:
        target = raw
    else:
        raise CalculatorValidationError(f"{field} must be one of: {', '.join(enum)}")
    if not is_absent(payload, target):
        raise CalculatorValidationError(f"'{target}' must be omitted when solving for it")
    return target
