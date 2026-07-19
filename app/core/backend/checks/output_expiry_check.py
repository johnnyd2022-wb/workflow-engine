"""
Custom output expiry check: process step outputs with custom_expiry config
that have become expired or near-expiry based on execution step completed_at + expiry_days.
Uses existing metadata storage (step.outputs[].extra_data.custom_expiry); generates
risk signals only (no inventory modification). Findings appear in system banner and sourcemap.
"""

from __future__ import annotations

import calendar
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session, joinedload

from app.core.backend.corechecks import CheckResult
from app.core.db.models.execution import Execution
from app.core.db.models.execution_step import ExecutionStep
from app.core.db.models.inventory_item import InventoryItem
from app.observability import get_logger

_log = get_logger(__name__)

# Severity when past expiry
SEVERITY_EXPIRED = "red"
# Severity when within warning window (e.g. 7 days before expiry)
SEVERITY_NEAR_EXPIRY = "amber"
# Default warning threshold when not configured
DEFAULT_WARNING_VALUE = 7
DEFAULT_WARNING_UNIT = "days"

_ALLOWED_UNITS = {"hours", "days", "weeks", "months"}

# Buffer to reduce false-positives from clock skew / delayed commits
CLOCK_SKEW_BUFFER_HOURS = 0.5

# Cap number of expiry items returned to avoid huge API responses
MAX_EXPIRY_ITEMS = 500


def _as_int(val: Any, default: int | None = None) -> int | None:
    try:
        if val is None:
            return default
        return int(val)
    except Exception:
        return default


def _normalize_dt(val: Any) -> datetime | None:
    """Parse ISO datetime strings and normalize to UTC-aware datetime if possible."""
    if val is None:
        return None
    if isinstance(val, int | float):
        try:
            return datetime.fromtimestamp(val, tz=UTC)
        except Exception:
            return None
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=UTC)
        return val.astimezone(UTC)
    if isinstance(val, str) and val.strip():
        s = val.strip()
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt.astimezone(UTC)
        except Exception:
            return None
    return None


def _add_months(dt: datetime, months: int) -> datetime:
    """Add months to datetime, clamping day to end-of-month when needed."""
    months = int(months)
    y = dt.year + (dt.month - 1 + months) // 12
    m = (dt.month - 1 + months) % 12 + 1
    last_day = calendar.monthrange(y, m)[1]
    d = min(dt.day, last_day)
    return dt.replace(year=y, month=m, day=d)


def _add_duration(dt: datetime, value: int, unit: str) -> datetime:
    unit = (unit or "").strip().lower()
    if unit not in _ALLOWED_UNITS:
        unit = "days"
    if unit == "hours":
        return dt + timedelta(hours=value)
    if unit == "days":
        return dt + timedelta(days=value)
    if unit == "weeks":
        return dt + timedelta(weeks=value)
    if unit == "months":
        return _add_months(dt, value)
    return dt + timedelta(days=value)


def _normalize(s: str | None) -> str:
    return ((s or "").strip()).lower()


def _get_custom_expiry_config(output: dict) -> dict | None:
    """Return custom_expiry config dict if enabled and valid, else None.

    Supported schemas:
    - New: { enabled, mode, duration_value, duration_unit, warning_value, warning_unit }
    - Legacy: { enabled, expiry_days, warning_days }
    """
    extra = output.get("extra_data") or {}
    ce = extra.get("custom_expiry")
    if not ce or not ce.get("enabled"):
        return None
    mode = (ce.get("mode") or "").strip()
    if mode not in {"fixed_duration", "set_at_execution"}:
        return None

    duration_value = _as_int(ce.get("duration_value"), None)
    duration_unit = (ce.get("duration_unit") or "").strip().lower() or "days"

    warning_value = _as_int(ce.get("warning_value"), None)
    warning_unit = (ce.get("warning_unit") or "").strip().lower() or DEFAULT_WARNING_UNIT

    if warning_unit not in _ALLOWED_UNITS:
        warning_unit = DEFAULT_WARNING_UNIT
    if warning_value is None:
        warning_value = DEFAULT_WARNING_VALUE
    elif warning_value < 0:
        warning_value = DEFAULT_WARNING_VALUE

    if mode == "fixed_duration":
        if duration_value is None or duration_value <= 0:
            return None
        if duration_unit not in _ALLOWED_UNITS:
            duration_unit = "days"

    return {
        "mode": mode,
        "duration_value": duration_value,
        "duration_unit": duration_unit,
        "warning_value": warning_value,
        "warning_unit": warning_unit,
        "rule_type": ce.get("rule_type") or "custom_output_expiry",
    }


def run_output_expiry_check(org_id: UUID, session: Session) -> CheckResult:
    """
    Find inventory items produced by steps with custom expiry that are expired or near-expiry.
    Traverses completed execution steps, reads step.outputs[].extra_data.custom_expiry,
    matches items by source_execution_step_id and output name/unit, evaluates expiry date.
    """
    # Completed execution steps with step (for outputs) and execution (for process_id)
    execution_steps = (
        session.query(ExecutionStep)
        .join(Execution, ExecutionStep.execution_id == Execution.id)
        .filter(Execution.org_id == org_id)
        .filter(ExecutionStep.completed_at.isnot(None))
        .options(
            joinedload(ExecutionStep.step),
            joinedload(ExecutionStep.execution).joinedload(Execution.process),
        )
        .all()
    )

    output_expiry_items: list[dict[str, Any]] = []
    seen_item_ids: set[UUID] = set()

    # Load all inventory for these execution steps once to avoid N+1
    step_ids = [es.id for es in execution_steps if es.id]
    inventory_items = (
        session.query(InventoryItem)
        .filter(InventoryItem.org_id == org_id)
        .filter(InventoryItem.source_execution_step_id.in_(step_ids))
        .all()
    )
    inventory_map: dict[tuple[UUID, str, str], list[InventoryItem]] = {}
    for item in inventory_items:
        key = (
            item.source_execution_step_id,
            _normalize(item.name or ""),
            (item.unit or "").strip(),
        )
        inventory_map.setdefault(key, []).append(item)

    for es in execution_steps:
        if not es.step:
            continue
        step_outputs = getattr(es.step, "outputs", None) or []

        completed_at = es.completed_at
        if not completed_at:
            continue
        completed_dt = _normalize_dt(completed_at)
        if not completed_dt:
            continue

        for out_def in step_outputs:
            if not isinstance(out_def, dict):
                continue
            config = _get_custom_expiry_config(out_def)
            if not config:
                continue
            mode = config.get("mode")
            out_name = (out_def.get("name") or "").strip()
            out_unit = (out_def.get("unit") or "").strip()
            if not out_name:
                continue

            if len(output_expiry_items) >= MAX_EXPIRY_ITEMS:
                break

            # Look up inventory from preloaded map (step_id, normalized_name, trimmed unit)
            items = inventory_map.get((es.id, _normalize(out_name), out_unit.strip()), [])

            now = datetime.now(UTC) - timedelta(hours=CLOCK_SKEW_BUFFER_HOURS)

            for item in items:
                if item.id in seen_item_ids:
                    continue
                try:
                    qty = float(item.quantity) if item.quantity is not None else 0
                except (TypeError, ValueError):
                    qty = 0
                if qty <= 0:
                    continue

                seen_item_ids.add(item.id)

                expiry_at: datetime | None = None
                warning_value = config.get("warning_value", DEFAULT_WARNING_VALUE)
                warning_unit = config.get("warning_unit", DEFAULT_WARNING_UNIT)
                prompt_text = None

                if mode == "fixed_duration":
                    dv = config.get("duration_value")
                    du = config.get("duration_unit") or "days"
                    if isinstance(dv, int) and dv > 0:
                        expiry_at = _add_duration(completed_dt, dv, du)
                        prompt_text = f"Output must be consumed in {dv} {du}."
                elif mode == "set_at_execution":
                    actual = (
                        (item.extra_data or {}).get("custom_expiry_actual")
                        if isinstance(item.extra_data, dict)
                        else None
                    )
                    if isinstance(actual, dict):
                        a_mode = actual.get("mode")
                        # Allow per-item warning overrides
                        warning_value = _as_int(actual.get("warning_value"), warning_value) or warning_value
                        warning_unit = (
                            (actual.get("warning_unit") or warning_unit or DEFAULT_WARNING_UNIT).strip().lower()
                        )
                        if warning_unit not in _ALLOWED_UNITS:
                            warning_unit = DEFAULT_WARNING_UNIT
                        if a_mode == "datetime":
                            expiry_at = _normalize_dt(actual.get("expiry_at"))
                            prompt_text = "Output has an operator-set expiry date/time."
                        elif a_mode == "duration":
                            dv = _as_int(actual.get("duration_value"), None)
                            du = (actual.get("duration_unit") or "days").strip().lower()
                            if dv is not None and dv > 0:
                                expiry_at = _add_duration(completed_dt, dv, du)
                                prompt_text = f"Output must be consumed in {dv} {du}."

                if not expiry_at:
                    continue

                warn_at = (
                    _add_duration(expiry_at, -int(warning_value), warning_unit) if int(warning_value) > 0 else expiry_at
                )

                if now > expiry_at:
                    severity = SEVERITY_EXPIRED
                    message = f"Output '{out_name}' expired on {expiry_at.isoformat()}."
                elif now >= warn_at:
                    severity = SEVERITY_NEAR_EXPIRY
                    message = f"Output '{out_name}' expires on {expiry_at.isoformat()}."
                else:
                    continue
                if prompt_text:
                    message = f"{message} {prompt_text}"

                process_name = es.execution.process.name if es.execution and es.execution.process else None
                step_name = es.step.name if es.step else None

                output_expiry_items.append(
                    {
                        "type": "expiry",
                        "severity": severity,
                        "message": message,
                        "execution_id": str(es.execution_id),
                        "process_id": str(es.execution.process_id) if es.execution else None,
                        "step_id": str(es.step_id),
                        "process_name": process_name,
                        "step_name": step_name,
                        "inventory_item_id": str(item.id),
                        "item_name": item.name,
                        "unit": item.unit,
                        # Stable trigger timestamp for notifications: when this output was produced.
                        "detected_at": completed_dt.isoformat(),
                        "expiry_at": expiry_at.isoformat(),
                        "warning_value": int(warning_value),
                        "warning_unit": warning_unit,
                        "config_mode": mode,
                        "metadata": {"rule_type": config.get("rule_type", "custom_output_expiry")},
                    }
                )
        if len(output_expiry_items) >= MAX_EXPIRY_ITEMS:
            break

    flagged = len(output_expiry_items) > 0
    message = None
    if flagged:
        expired_count = sum(1 for x in output_expiry_items if x.get("severity") == SEVERITY_EXPIRED)
        near_count = len(output_expiry_items) - expired_count
        parts = []
        if expired_count:
            parts.append(f"{expired_count} expired")
        if near_count:
            parts.append(f"{near_count} near expiry")
        message = f"Custom output expiry: {'; '.join(parts)}."

    return CheckResult(
        check_id="output_expiry",
        flagged=flagged,
        message=message,
        data={
            "output_expiry_items": output_expiry_items,
        },
    )
