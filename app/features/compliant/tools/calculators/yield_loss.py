"""Packaged volume and cumulative loss across ordered production steps.

Each step supplies exactly one of loss_pct / loss_l; all steps in one request use the
same key. Losses apply sequentially to a running volume.
"""

from __future__ import annotations

from app.features.compliant.tools.calculators._validate import (
    as_number,
    bounded,
    finalise,
    guarded,
    is_absent,
    required_number,
)
from app.features.compliant.tools.errors import CalculatorValidationError

KEY = "yield_loss"
TITLE = "Production yield & loss"
CATEGORY = "vessel"
SOURCES = ["Arithmetic (sequential proportional / absolute loss)"]
DISCLAIMER = "Planning estimate; actual losses vary by process and equipment."

_MAX_STEPS = 50
_ITEM_FIELDS = {"name", "loss_pct", "loss_l"}


def _step_name(raw, index: int) -> str:
    if not isinstance(raw, str) or not raw.strip() or len(raw) > 80:
        raise CalculatorValidationError(f"step {index}: 'name' must be a non-empty string of at most 80 characters")
    return raw.strip()


@guarded
def solve(payload: dict) -> dict:
    start_volume_l = required_number(payload, "start_volume_l", exclusive_min=0)

    steps = payload.get("steps")
    if not isinstance(steps, list):
        raise CalculatorValidationError("'steps' must be a list")
    if not 1 <= len(steps) <= _MAX_STEPS:
        raise CalculatorValidationError(f"'steps' must have between 1 and {_MAX_STEPS} items")

    mode: str | None = None
    parsed: list[tuple[str, str, float]] = []
    for i, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            raise CalculatorValidationError(f"each steps item must be an object (item {i})")
        unknown = set(step) - _ITEM_FIELDS
        if unknown:
            raise CalculatorValidationError(f"unexpected field '{sorted(unknown)[0]}' in steps item {i}")
        name = _step_name(step.get("name"), i)
        has_pct = not is_absent(step, "loss_pct")
        has_abs = not is_absent(step, "loss_l")
        if has_pct == has_abs:
            raise CalculatorValidationError(f"step {i}: exactly one of loss_pct or loss_l is required")
        key = "loss_pct" if has_pct else "loss_l"
        if mode is None:
            mode = key
        elif mode != key:
            raise CalculatorValidationError("steps must all use loss_pct or all use loss_l")
        if key == "loss_pct":
            value = bounded(as_number(step["loss_pct"], "loss_pct"), "loss_pct", minimum=0, exclusive_max=100)
        else:
            value = bounded(as_number(step["loss_l"], "loss_l"), "loss_l", minimum=0)
        parsed.append((name, key, value))

    remaining = start_volume_l
    per_step = []
    for name, key, value in parsed:
        # `remaining * (value / 100)` not `remaining * value / 100` — the latter overflows
        # its intermediate product for a very large `remaining` before the divide.
        remaining = remaining - (remaining * (value / 100.0) if key == "loss_pct" else value)
        if remaining < 0.0:
            raise CalculatorValidationError("cumulative loss exceeds available volume")
        per_step.append({"name": name, "remaining_l": remaining})

    return finalise(
        {
            "start_volume_l": start_volume_l,
            "final_volume_l": remaining,
            "total_loss_l": start_volume_l - remaining,
            "effective_yield_pct": remaining / start_volume_l * 100.0,
            "per_step": per_step,
            "disclaimer": DISCLAIMER,
            "sources": SOURCES,
        }
    )
