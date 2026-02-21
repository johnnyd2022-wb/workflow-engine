"""
Untracked items check: inventory items with extra_data.untracked = True and quantity > 0
(recorded in-flow without full upstream traceability). Surfaces in banners, sourcemap
"Check needed", and execution dropdowns. Uses InventoryRepository.get_untracked_items
so canonical inventory state drives the check (projection layer only).
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.backend.corechecks import CheckResult
from app.core.db.models.execution import Execution
from app.core.db.models.execution_step import ExecutionStep
from app.core.db.models.inventory_item import InventoryItem
from app.core.db.repositories.inventory_repo import InventoryRepository

_log = logging.getLogger(__name__)

# Fields from execution_data we exclude from execution_prompts (shown separately or internal)
_EXECUTION_PROMPTS_INTERNAL = {
    "completed_by",
    "completed_by_email",
    "completed_by_user_id",
    "completed_at",
    "execution_errors",
    "execution_warnings",
}


def _enrich_untracked_with_step_metadata(session: Session, org_id: UUID, item: InventoryItem) -> dict[str, Any]:
    """Attach completed_by and user execution metadata from the source execution step."""
    out = {
        "source_step_completed_by": None,
        "source_step_execution_prompts": {},
    }
    step_id = item.source_execution_step_id
    if not step_id:
        return out
    step = (
        session.query(ExecutionStep)
        .join(Execution, ExecutionStep.execution_id == Execution.id)
        .filter(ExecutionStep.id == step_id, Execution.org_id == org_id)
        .first()
    )
    if not step or not step.execution_data:
        return out
    ed = step.execution_data
    out["source_step_completed_by"] = ed.get("completed_by") or ed.get("completed_by_email")
    out["source_step_execution_prompts"] = {
        k: v for k, v in (ed or {}).items() if k not in _EXECUTION_PROMPTS_INTERNAL and v is not None and v != ""
    }
    return out


def run_untracked_items_check(org_id: UUID, session: Session) -> CheckResult:
    """
    Find inventory items flagged as untracked with quantity > 0 (reconciliation required).
    Uses InventoryRepository.get_untracked_items for canonical state; check remains projection only.
    """
    try:
        untracked_orm = InventoryRepository(session).get_untracked_items(
            org_id=org_id,
            quantity_gt_zero=True,
        )
    except Exception as e:
        _log.warning("get_untracked_items failed, falling back to direct query: %s", e)
        untracked_orm = (
            session.query(InventoryItem)
            .filter(
                InventoryItem.org_id == org_id,
                InventoryItem.extra_data.isnot(None),
            )
            .all()
        )
        from decimal import Decimal

        def _qty(v):
            try:
                return Decimal(str(v)) if v is not None else None
            except Exception:
                return None

        untracked_orm = [
            i
            for i in untracked_orm
            if (i.extra_data or {}).get("untracked") is True and (_qty(i.quantity) or Decimal("0")) > 0
        ]

    untracked_items: list[dict[str, Any]] = []
    for item in untracked_orm:
        base = {
            "id": str(item.id),
            "name": item.name,
            "quantity": item.quantity,
            "unit": item.unit,
            "inventory_type": item.inventory_type,
            "supplier": item.supplier,
            "purchase_date": item.purchase_date.isoformat() if item.purchase_date else None,
            "supplier_batch_number": item.supplier_batch_number,
            "expiry_date": item.expiry_date.isoformat() if item.expiry_date else None,
            "source_execution_id": str(item.source_execution_id) if item.source_execution_id else None,
            "source_execution_step_id": str(item.source_execution_step_id) if item.source_execution_step_id else None,
            "created_at": item.created_at.isoformat() if item.created_at else None,
            "extra_data": item.extra_data if item.extra_data else {},
            "check_reason": "Untracked inventory item",
            "reconciliation_required": True,
        }
        step_meta = _enrich_untracked_with_step_metadata(session, org_id, item)
        base["source_step_completed_by"] = step_meta["source_step_completed_by"]
        base["source_step_execution_prompts"] = step_meta["source_step_execution_prompts"]
        untracked_items.append(base)

    flagged = len(untracked_items) > 0
    message = None
    if flagged:
        message = f"{len(untracked_items)} untracked item(s) — reconciliation required."

    return CheckResult(
        check_id="untracked_items",
        flagged=flagged,
        message=message,
        data={
            "untracked_items": untracked_items,
            "connections": [],  # Optional: forward connections to downstream steps
        },
    )
