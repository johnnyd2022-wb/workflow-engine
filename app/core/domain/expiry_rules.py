"""
Single source of truth for custom output expiry rules.

Invariant: warning_delta <= expiry_delta

Used by:
- Execution save validator (backend complete-step)
- Tests
- Future UI validator

Keeps save-time validation and any runtime/display logic from drifting.
"""

from __future__ import annotations

from datetime import timedelta

VALID_EXPIRY_UNITS = {"hours", "days", "weeks", "months"}


def duration_to_timedelta(value: int | float, unit: str) -> timedelta:
    """Convert duration value + unit to timedelta (months approximated as 30 days)."""
    u = (unit or "days").strip().lower()
    if u not in VALID_EXPIRY_UNITS:
        u = "days"
    v = int(value) if value is not None else 0
    if u == "hours":
        return timedelta(hours=v)
    if u == "days":
        return timedelta(days=v)
    if u == "weeks":
        return timedelta(weeks=v)
    if u == "months":
        return timedelta(days=v * 30)
    return timedelta(days=v)


def assert_warning_within_expiry(
    output_name: str,
    duration_value: int | None,
    duration_unit: str,
    warning_value: int | None,
    warning_unit: str,
) -> list[str]:
    """
    Enforce invariant: warning period must not exceed expiry period.

    Returns a list of error messages (one element if invalid, else empty).
    Call from execution save validator, tests, and future UI validator.
    """
    if duration_value is None or warning_value is None:
        return []
    du = (duration_unit or "days").strip().lower()
    wu = (warning_unit or "days").strip().lower()
    if du not in VALID_EXPIRY_UNITS or wu not in VALID_EXPIRY_UNITS:
        return []
    expiry_delta = duration_to_timedelta(duration_value, du)
    warning_delta = duration_to_timedelta(warning_value, wu)
    if warning_delta > expiry_delta:
        return [f"Output '{output_name}': warning period cannot exceed expiry period."]
    return []
