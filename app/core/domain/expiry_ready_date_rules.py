"""
Shared invariant: when both expiry and ready date are set, expiry cannot be before ready date.

Invariant: ready_date <= expiry_date (i.e. expiry must be on or after the ready date).

Used by:
- Step modal validation (fixed duration vs fixed duration)
- Execution modal / complete_step (when both values are present: durations or dates)
- Tests

Single source of truth so both flows stay consistent.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.core.domain.expiry_rules import duration_to_timedelta as expiry_duration_to_timedelta
from app.core.domain.ready_date_rules import (
    VALID_READY_DATE_UNITS,
    duration_to_timedelta as ready_duration_to_timedelta,
)


def _parse_iso(s: str | None) -> datetime | None:
    if not s or not isinstance(s, str) or not s.strip():
        return None
    try:
        dt = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def assert_expiry_after_ready_duration(
    output_name: str,
    ready_value: int | float,
    ready_unit: str,
    expiry_value: int | float,
    expiry_unit: str,
) -> list[str]:
    """
    When both ready date and expiry use fixed duration (from step completion),
    require ready_duration <= expiry_duration so that for any completion time
    ready_dt <= expiry_dt.

    Returns a list of error messages (one element if invalid, else empty).
    """
    ru = (ready_unit or "days").strip().lower()
    eu = (expiry_unit or "days").strip().lower()
    if ru not in VALID_READY_DATE_UNITS:
        return []
    try:
        ready_delta = ready_duration_to_timedelta(ready_value, ru)
        expiry_delta = expiry_duration_to_timedelta(expiry_value, eu)
    except Exception:
        return []
    if ready_delta > expiry_delta:
        return [
            f"Output '{output_name}': expiry must be on or after the ready date. "
            "Increase the expiry period or reduce the ready period so that the product is usable for at least one day."
        ]
    return []


def assert_expiry_after_ready_dates(
    output_name: str,
    ready_iso: str | None,
    expiry_iso: str | None,
) -> list[str]:
    """
    When both ready and expiry are actual dates (e.g. set at execution),
    require ready_date <= expiry_date.

    Returns a list of error messages (one element if invalid, else empty).
    """
    if not ready_iso or not expiry_iso:
        return []
    ready_dt = _parse_iso(ready_iso)
    expiry_dt = _parse_iso(expiry_iso)
    if not ready_dt or not expiry_dt:
        return []
    if ready_dt > expiry_dt:
        return [
            f"Output '{output_name}': expiry date cannot be before the ready date. "
            "Set an expiry date on or after the date when the output can be used."
        ]
    return []
