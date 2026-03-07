"""
Single source of truth for output ready date rules.

Invariants (lock these for compliance; do not change semantics without explicit change control):

1. Readiness: A product is usable when current_time >= ready_time (inclusive).
   So the product is not usable when current_time < ready_time.
   Equality (current_time == ready_time) counts as ready.

2. Warn-before-ready: warning_delta <= ready_delta
   (i.e. "warn before ready" period must not exceed the ready period).

Used by:
- output_ready_date_check (duration math and unit validation)
- Step save / execution validators if they validate ready date config
- Tests

Keeps check logic and any save-time/UI validation from drifting.
"""

from __future__ import annotations

from datetime import timedelta

VALID_READY_DATE_UNITS = {"days", "weeks", "months", "years"}

# Readiness state labels for UI and checks (single source of truth for copy).
# Derive all UI text from these to avoid drift.
READINESS_STATE_NOT_READY = "Not ready"
READINESS_STATE_NEAR_READY = "Nearing ready"
READINESS_STATE_READY = "Ready"
READINESS_STATES = (
    READINESS_STATE_NOT_READY,
    READINESS_STATE_NEAR_READY,
    READINESS_STATE_READY,
)


def duration_to_timedelta(value: int | float, unit: str) -> timedelta:
    """Convert duration value + unit to timedelta (months ≈ 30 days, years ≈ 365 days)."""
    u = (unit or "days").strip().lower()
    if u not in VALID_READY_DATE_UNITS:
        u = "days"
    v = int(value) if value is not None else 0
    if u == "days":
        return timedelta(days=v)
    if u == "weeks":
        return timedelta(weeks=v)
    if u == "months":
        return timedelta(days=v * 30)
    if u == "years":
        return timedelta(days=v * 365)
    return timedelta(days=v)


def assert_warning_within_ready_period(
    output_name: str,
    duration_value: int | None,
    duration_unit: str,
    warning_value: int | None,
    warning_unit: str,
) -> list[str]:
    """
    Enforce invariant: warn-before-ready period must not exceed the ready period.

    Returns a list of error messages (one element if invalid, else empty).
    Call from step/execution validators and tests.
    """
    if duration_value is None or warning_value is None:
        return []
    du = (duration_unit or "days").strip().lower()
    wu = (warning_unit or "days").strip().lower()
    if du not in VALID_READY_DATE_UNITS or wu not in VALID_READY_DATE_UNITS:
        return []
    ready_delta = duration_to_timedelta(duration_value, du)
    warning_delta = duration_to_timedelta(warning_value, wu)
    if warning_delta > ready_delta:
        return [f"Output '{output_name}': warn-before-ready period cannot exceed the ready period."]
    return []
