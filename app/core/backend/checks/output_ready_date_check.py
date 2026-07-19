"""
Output ready date check: process step outputs with ready_date config
where the current date is before the ready date (output not yet usable), or
within a "warn before ready" window (amber). Supports fixed_duration (ready
= completed_at + duration) and set_at_execution (date from item.extra_data.ready_date_actual).

Duration math and units come from app.core.domain.ready_date_rules (single source of truth).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session, joinedload

from app.core.backend.corechecks import CheckResult
from app.core.db.models.execution import Execution
from app.core.db.models.execution_step import ExecutionStep
from app.core.db.models.inventory_item import InventoryItem
from app.core.db.models.step import Step
from app.core.domain.ready_date_rules import (
    READINESS_STATE_NEAR_READY,
    READINESS_STATE_NOT_READY,
    VALID_READY_DATE_UNITS,
    duration_to_timedelta,
)
from app.core.utils.internal_counters import inc_counter
from app.observability import get_logger

_log = get_logger(__name__)

CHECK_ID = "output_ready_date"
RULE_TYPE_READY_DATE = "custom_ready_date"
SEVERITY_BEFORE_READY = "red"
SEVERITY_NEAR_READY = "amber"
DEFAULT_WARNING_VALUE = 1
DEFAULT_WARNING_UNIT = "days"
MAX_READY_DATE_ITEMS = 500

# JSONPath to detect step.outputs[] with extra_data.ready_date.enabled == true (DB-level filter).
_READY_DATE_JSONB_PATH = "$[*].extra_data.ready_date ? (@.enabled == true)"


def _as_int(val: Any, default: int | None = None) -> int | None:
    try:
        if val is None:
            return default
        return int(val)
    except Exception:
        return default


def _normalize_dt(val: Any) -> datetime | None:
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


def _add_duration(dt: datetime, value: int, unit: str) -> datetime:
    """Add duration to datetime using domain duration_to_timedelta (months ≈ 30d, years ≈ 365d)."""
    delta = duration_to_timedelta(value, unit)
    return dt + delta


def _normalize(s: str | None) -> str:
    return ((s or "").strip()).lower()


def _get_ready_date_config(output: dict) -> dict | None:
    """Return ready_date config if enabled and valid. Supports fixed_duration, set_at_execution, and legacy single 'date'."""
    extra = output.get("extra_data") or {}
    rd = extra.get("ready_date")
    if not rd or not rd.get("enabled"):
        return None
    mode = (rd.get("mode") or "").strip()
    # Legacy: had only "date" (single date)
    if not mode and rd.get("date"):
        ready_dt = _normalize_dt(rd.get("date"))
        if ready_dt:
            return {
                "mode": "fixed_duration",
                "ready_dt": ready_dt,
                "warning_value": _as_int(rd.get("warning_value"), DEFAULT_WARNING_VALUE) or 0,
                "warning_unit": (rd.get("warning_unit") or DEFAULT_WARNING_UNIT).strip().lower() or "days",
                "rule_type": rd.get("rule_type") or RULE_TYPE_READY_DATE,
            }
        return None
    if mode not in {"fixed_duration", "set_at_execution"}:
        return None
    if mode == "fixed_duration":
        dv = _as_int(rd.get("duration_value"), None)
        du = (rd.get("duration_unit") or "days").strip().lower() or "days"
        if dv is None or dv <= 0 or du not in VALID_READY_DATE_UNITS:
            return None
        return {
            "mode": mode,
            "duration_value": dv,
            "duration_unit": du,
            "warning_value": _as_int(rd.get("warning_value"), DEFAULT_WARNING_VALUE) or 0,
            "warning_unit": (rd.get("warning_unit") or DEFAULT_WARNING_UNIT).strip().lower() or "days",
            "rule_type": rd.get("rule_type") or "custom_ready_date",
        }
    return {
        "mode": mode,
        "rule_type": rd.get("rule_type") or "custom_ready_date",
    }


def _step_has_ready_date_output(step: Any) -> bool:
    """True if step has at least one output with ready_date config (enabled). Used to restrict inventory query."""
    if not step:
        return False
    outputs = getattr(step, "outputs", None) or []
    for out in outputs:
        if isinstance(out, dict) and _get_ready_date_config(out):
            return True
    return False


def is_inventory_item_ready_for_consumption(
    session: Session, item: InventoryItem, now: datetime | None = None
) -> tuple[bool, str | None]:
    """
    Execution consumption guard: return (True, None) if the item can be consumed (no ready date or ready_dt <= now),
    else (False, error_message). Used by complete_step to block consuming not-ready inventory when API is called directly.

    Invariant (locked): now < ready_dt → not ready; now >= ready_dt → ready (inclusive).
    """
    if now is None:
        now = datetime.now(UTC)
    extra = (item.extra_data or {}) if isinstance(item.extra_data, dict) else {}
    # Set-at-execution: ready date stored on item (dict with date, or ISO string)
    actual = extra.get("ready_date_actual")
    if isinstance(actual, dict) and actual.get("date"):
        ready_dt = _normalize_dt(actual.get("date"))
    elif isinstance(actual, str) and actual.strip():
        ready_dt = _normalize_dt(actual.strip())
    else:
        ready_dt = None
    if ready_dt is not None:
        # now < ready_dt → not ready; now >= ready_dt → ready (inclusive)
        if ready_dt and now < ready_dt:
            return (
                False,
                f"Item '{item.name or 'Unknown'}' is not ready for use until {ready_dt.date().isoformat()}. "
                "Complete the step from the UI and confirm if you intend to use it anyway.",
            )
        return (True, None)

    # Fixed duration: need source execution step and step definition to compute ready_dt
    step_id = getattr(item, "source_execution_step_id", None)
    if not step_id:
        return (True, None)
    execution_step = (
        session.query(ExecutionStep).filter(ExecutionStep.id == step_id).options(joinedload(ExecutionStep.step)).first()
    )
    if not execution_step or not execution_step.step or not execution_step.completed_at:
        return (True, None)
    step_outputs = getattr(execution_step.step, "outputs", None) or []
    completed_dt = _normalize_dt(execution_step.completed_at)
    if not completed_dt:
        return (True, None)
    item_name_norm = _normalize(item.name or "")
    item_unit = (item.unit or "").strip()
    for out_def in step_outputs:
        if not isinstance(out_def, dict):
            continue
        if _normalize(out_def.get("name") or "") != item_name_norm:
            continue
        if (out_def.get("unit") or "").strip() != item_unit:
            continue
        config = _get_ready_date_config(out_def)
        if not config:
            return (True, None)
        ready_dt, _ = _compute_ready_and_warn(config, completed_dt, item)
        # now < ready_dt → not ready; now >= ready_dt → ready (inclusive)
        if ready_dt and now < ready_dt:
            return (
                False,
                f"Item '{item.name or 'Unknown'}' is not ready for use until {ready_dt.date().isoformat()}. "
                "Complete the step from the UI and confirm if you intend to use it anyway.",
            )
        return (True, None)
    return (True, None)


def get_operator_ready_instant_for_item(
    session: Session,
    item: InventoryItem,
    *,
    execution_step: ExecutionStep | None = None,
) -> datetime | None:
    """When the item becomes usable under ready-date rules: stored date (set_at_execution) or computed fixed-duration instant.

    Pass ``execution_step`` when already loaded (e.g. batch inventory API) to avoid per-item queries.
    """
    extra = (item.extra_data or {}) if isinstance(item.extra_data, dict) else {}
    actual = extra.get("ready_date_actual")
    if isinstance(actual, dict) and actual.get("date"):
        dt = _normalize_dt(actual.get("date"))
        if dt:
            return dt
    if isinstance(actual, str) and actual.strip():
        raw_s = actual.strip()
        dt = _normalize_dt(raw_s)
        if dt:
            return dt
        inc_counter("ready_date_parse_failures")
        _log.debug(
            "ready_date_actual string did not parse (expect ISO-8601): %.120s",
            raw_s,
        )

    step_id = getattr(item, "source_execution_step_id", None)
    if not step_id:
        return None
    es = execution_step
    if es is None:
        es = (
            session.query(ExecutionStep)
            .filter(ExecutionStep.id == step_id)
            .options(joinedload(ExecutionStep.step))
            .first()
        )
    if not es or not es.step or not es.completed_at:
        return None
    step_outputs = getattr(es.step, "outputs", None) or []
    completed_dt = _normalize_dt(es.completed_at)
    if not completed_dt:
        return None
    item_name_norm = _normalize(item.name or "")
    item_unit = (item.unit or "").strip()
    for out_def in step_outputs:
        if not isinstance(out_def, dict):
            continue
        if _normalize(out_def.get("name") or "") != item_name_norm:
            continue
        if (out_def.get("unit") or "").strip() != item_unit:
            continue
        config = _get_ready_date_config(out_def)
        if not config:
            return None
        ready_dt, _ = _compute_ready_and_warn(config, completed_dt, item)
        return ready_dt
    return None


def _compute_ready_and_warn(
    config: dict, completed_dt: datetime, item: InventoryItem
) -> tuple[datetime | None, datetime | None]:
    """Return (ready_dt, warn_dt). warn_dt = ready_dt - warning_duration (when to start showing amber)."""
    mode = config.get("mode")
    if mode == "fixed_duration":
        dv = config.get("duration_value")
        du = config.get("duration_unit") or "days"
        if dv is None or dv <= 0:
            return None, None
        ready_dt = _add_duration(completed_dt, dv, du)
    elif mode == "set_at_execution":
        actual = (item.extra_data or {}).get("ready_date_actual") if isinstance(item.extra_data, dict) else None
        if not isinstance(actual, dict) or not actual.get("date"):
            return None, None
        ready_dt = _normalize_dt(actual.get("date"))
        if not ready_dt:
            return None, None
    elif config.get("ready_dt"):
        ready_dt = config["ready_dt"]
    else:
        return None, None
    warn_val = config.get("warning_value", DEFAULT_WARNING_VALUE) or 0
    warn_unit = (config.get("warning_unit") or DEFAULT_WARNING_UNIT).strip().lower() or "days"
    if warn_val <= 0 or warn_unit not in VALID_READY_DATE_UNITS:
        return ready_dt, ready_dt
    warn_delta = duration_to_timedelta(-warn_val, warn_unit)
    warn_dt = ready_dt + warn_delta
    return ready_dt, warn_dt


def run_output_ready_date_check(org_id: UUID, session: Session) -> CheckResult:
    """
    Find inventory items produced by steps with ready_date config that are
    not yet usable (red) or within the warn-before-ready window (amber).

    Performance: uses a DB-side JSONB filter to get execution_step IDs that have
    ready_date enabled (jsonb_path_exists on steps.outputs), then loads only those
    execution_steps and their inventory. Avoids loading all org execution_steps
    and all org inventory when most steps do not use ready date (scales for large orgs).
    """
    now = datetime.now(UTC)
    ready_date_items: list[dict[str, Any]] = []
    seen_item_ids: set[UUID] = set()

    # 1) DB-level filter: only execution_step IDs whose step has ready_date in outputs (no Python scan).
    step_ids_with_ready_date = [
        row[0]
        for row in (  # nosemgrep: sqlalchemy-all-without-limit — DB-side jsonb_path_exists filter already scopes this to the small subset of steps that use ready_date; a LIMIT would silently drop qualifying items from a correctness check
            session.query(ExecutionStep.id)
            .join(Execution, ExecutionStep.execution_id == Execution.id)
            .join(Step, ExecutionStep.step_id == Step.id)
            .filter(Execution.org_id == org_id)
            .filter(ExecutionStep.completed_at.isnot(None))
            .filter(text("jsonb_path_exists(steps.outputs, :path)").bindparams(path=_READY_DATE_JSONB_PATH))
            .all()
        )
    ]
    if not step_ids_with_ready_date:
        _log.debug(
            "output_ready_date check org_id=%s count_flagged=0 (no steps with ready_date)",
            org_id,
            extra={"org_id": str(org_id), "count_flagged_items": 0},
        )
        return CheckResult(
            check_id=CHECK_ID,
            flagged=False,
            message=None,
            data={"output_ready_date_items": []},
        )

    # 2) Load only those execution_steps (with step + execution.process for config and names).
    execution_steps = (
        session.query(ExecutionStep)
        .filter(ExecutionStep.id.in_(step_ids_with_ready_date))
        .options(
            joinedload(ExecutionStep.step),
            joinedload(ExecutionStep.execution).joinedload(Execution.process),
        )
        .all()
    )

    # 3) Load only inventory items produced by those steps (not all org inventory).
    inventory_items = (
        session.query(InventoryItem)
        .filter(InventoryItem.org_id == org_id)
        .filter(InventoryItem.source_execution_step_id.in_(step_ids_with_ready_date))
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
            config = _get_ready_date_config(out_def)
            if not config:
                continue
            out_name = (out_def.get("name") or "").strip()
            out_unit = (out_def.get("unit") or "").strip()
            if not out_name:
                continue

            if len(ready_date_items) >= MAX_READY_DATE_ITEMS:
                break

            items = inventory_map.get((es.id, _normalize(out_name), out_unit.strip()), [])

            for item in items:
                if item.id in seen_item_ids:
                    continue
                try:
                    qty = float(item.quantity) if item.quantity is not None else 0
                except (TypeError, ValueError):
                    qty = 0
                if qty <= 0:
                    continue

                # Legacy: config may have precomputed ready_dt
                if config.get("ready_dt"):
                    ready_dt = config["ready_dt"]
                    wv = config.get("warning_value") or 0
                    wu = (config.get("warning_unit") or "days").strip().lower() or "days"
                    if wv > 0 and wu in VALID_READY_DATE_UNITS:
                        warn_delta = duration_to_timedelta(-wv, wu)
                        warn_dt = ready_dt + warn_delta
                    else:
                        warn_dt = ready_dt
                else:
                    ready_dt, warn_dt = _compute_ready_and_warn(config, completed_dt, item)
                if not ready_dt:
                    continue

                # Invariant: now < ready_dt → not ready; now >= ready_dt → ready (inclusive). Skip if already ready.
                if now >= ready_dt:
                    continue

                seen_item_ids.add(item.id)
                if now < warn_dt:
                    severity = SEVERITY_BEFORE_READY
                    state_label = READINESS_STATE_NOT_READY
                    detail = f"Output '{out_name}' cannot be used until {ready_dt.isoformat()}."
                else:
                    severity = SEVERITY_NEAR_READY
                    state_label = READINESS_STATE_NEAR_READY
                    detail = f"Output '{out_name}' will be ready on {ready_dt.isoformat()}."

                process_name = es.execution.process.name if es.execution and es.execution.process else None
                step_name = es.step.name if es.step else None

                ready_date_items.append(
                    {
                        "type": "ready_date",
                        "severity": severity,
                        "state": state_label,
                        "message": detail,
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
                        "ready_date": ready_dt.isoformat(),
                        "metadata": {
                            "rule_type": config.get("rule_type", RULE_TYPE_READY_DATE),
                            "evaluated_at": now.isoformat(),
                            "rule_version": "1.0",
                        },
                    }
                )
        if len(ready_date_items) >= MAX_READY_DATE_ITEMS:
            break

    flagged = len(ready_date_items) > 0
    message = None
    if flagged:
        message = f"Output ready date: {len(ready_date_items)} output(s) not yet usable or nearing ready."

    _log.debug(
        "output_ready_date check org_id=%s count_flagged=%s",
        org_id,
        len(ready_date_items),
        extra={"org_id": str(org_id), "count_flagged_items": len(ready_date_items)},
    )
    return CheckResult(
        check_id=CHECK_ID,
        flagged=flagged,
        message=message,
        data={"output_ready_date_items": ready_date_items},
    )
