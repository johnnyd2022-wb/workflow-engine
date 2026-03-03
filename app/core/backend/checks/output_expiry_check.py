"""
Custom output expiry check: process step outputs with custom_expiry config
that have become expired or near-expiry based on execution step completed_at + expiry_days.
Uses existing metadata storage (step.outputs[].extra_data.custom_expiry); generates
risk signals only (no inventory modification). Findings appear in system banner and sourcemap.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session, joinedload

from app.core.backend.corechecks import CheckResult
from app.core.db.models.execution import Execution
from app.core.db.models.execution_step import ExecutionStep
from app.core.db.models.inventory_item import InventoryItem

_log = logging.getLogger(__name__)

# Severity when past expiry
SEVERITY_EXPIRED = "red"
# Severity when within warning window (e.g. 7 days before expiry)
SEVERITY_NEAR_EXPIRY = "amber"
# Default days before expiry to show amber when warning_days not set
DEFAULT_WARNING_DAYS = 7


def _normalize(s: str | None) -> str:
    return ((s or "").strip()).lower()


def _get_custom_expiry_config(output: dict) -> dict | None:
    """Return custom_expiry dict if enabled and valid, else None."""
    extra = output.get("extra_data") or {}
    ce = extra.get("custom_expiry")
    if not ce or not ce.get("enabled"):
        return None
    days = ce.get("expiry_days")
    if days is None or (isinstance(days, (int, float)) and int(days) <= 0):
        return None
    warning_days = ce.get("warning_days")
    if warning_days is not None and isinstance(warning_days, (int, float)):
        warning_days = max(0, int(warning_days))
    else:
        warning_days = DEFAULT_WARNING_DAYS
    return {
        "expiry_days": int(days),
        "expiry_prompt": (ce.get("expiry_prompt") or "").strip() or f"Use within {int(days)} days",
        "rule_type": ce.get("rule_type") or "custom_output_expiry",
        "warning_days": warning_days,
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
    seen_item_ids: set[str] = set()

    for es in execution_steps:
        if not es.step:
            continue
        step_outputs = getattr(es.step, "outputs", None) or []

        completed_at = es.completed_at
        if not completed_at:
            continue
        # Use date only for expiry calculation
        completed_date = completed_at.date() if hasattr(completed_at, "date") else completed_at

        for out_def in step_outputs:
            if not isinstance(out_def, dict):
                continue
            config = _get_custom_expiry_config(out_def)
            if not config:
                continue
            expiry_days = config["expiry_days"]
            expiry_prompt = config["expiry_prompt"]
            warning_days = config.get("warning_days", DEFAULT_WARNING_DAYS)
            out_name = (out_def.get("name") or "").strip()
            out_unit = (out_def.get("unit") or "").strip()
            if not out_name:
                continue

            # Inventory items produced by this execution step; filter by name/unit in Python
            items = (
                session.query(InventoryItem)
                .filter(InventoryItem.org_id == org_id)
                .filter(InventoryItem.source_execution_step_id == es.id)
                .all()
            )
            items = [
                i
                for i in items
                if _normalize(i.name or "") == _normalize(out_name) and (i.unit or "").strip() == out_unit
            ]

            expiry_date = completed_date + timedelta(days=expiry_days)
            today = date.today()

            for item in items:
                if str(item.id) in seen_item_ids:
                    continue
                try:
                    qty = float(item.quantity) if item.quantity is not None else 0
                except (TypeError, ValueError):
                    qty = 0
                if qty <= 0:
                    continue

                seen_item_ids.add(str(item.id))

                if today > expiry_date:
                    severity = SEVERITY_EXPIRED
                    message = f"Output '{out_name}' expired on {expiry_date.isoformat()}. {expiry_prompt}"
                elif today >= expiry_date - timedelta(days=warning_days):
                    severity = SEVERITY_NEAR_EXPIRY
                    message = f"Output '{out_name}' expires on {expiry_date.isoformat()}. {expiry_prompt}"
                else:
                    continue

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
                        "expiry_date": expiry_date.isoformat(),
                        "expiry_prompt": expiry_prompt,
                        "warning_days": warning_days,
                        "metadata": {"rule_type": config.get("rule_type", "custom_output_expiry")},
                    }
                )

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
