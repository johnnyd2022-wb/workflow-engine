"""
Untracked items check: inventory items with extra_data.untracked = True that still need reconciliation.
Uses the same criteria as the execution modal (matching-untracked): include if quantity > 0 OR
remaining_balance_to_reconcile > 0. Surfaces in banners, sourcemap "Check needed", and lists.
Uses InventoryRepository.get_untracked_items so canonical inventory state drives the check.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session, joinedload

from app.core.backend.corechecks import CheckResult
from app.core.db.models.execution import Execution
from app.core.db.models.execution_step import ExecutionStep
from app.core.db.models.inventory_item import InventoryItem
from app.core.db.repositories.inventory_repo import InventoryRepository
from app.core.db.repositories.process_repo import ProcessRepository
from app.observability import get_logger

_log = get_logger(__name__)


def _normalize(s: str | None) -> str:
    return ((s or "").strip()).lower()


def _find_producing_step(process: Any, item_name: str | None, item_unit: str | None) -> tuple[Any, str | None]:
    """Return (step_id, step_name) for the step that has an output matching (item_name, item_unit), or (None, None)."""
    if not process or not getattr(process, "steps", None):
        return (None, None)
    n_name = _normalize(item_name)
    n_unit = _normalize(item_unit)
    for step in process.steps:
        for out in step.outputs or []:
            if not isinstance(out, dict):
                continue
            if _normalize(out.get("name")) == n_name and _normalize(out.get("unit")) == n_unit:
                return (step.id, step.name)
    return (None, None)


# Fields from execution_data we exclude from execution_prompts (shown separately or internal)
_EXECUTION_PROMPTS_INTERNAL = {
    "completed_by",
    "completed_by_email",
    "completed_by_user_id",
    "completed_at",
    "execution_errors",
    "execution_warnings",
}


def _step_metadata_from_execution_data(ed: dict | None) -> dict[str, Any]:
    """Build source_step_completed_by and source_step_execution_prompts from execution_data."""
    if not ed:
        return {"source_step_completed_by": None, "source_step_execution_prompts": {}}
    return {
        "source_step_completed_by": ed.get("completed_by") or ed.get("completed_by_email"),
        "source_step_execution_prompts": {
            k: v for k, v in (ed or {}).items() if k not in _EXECUTION_PROMPTS_INTERNAL and v is not None and v != ""
        },
    }


def _batch_fetch_step_metadata(session: Session, org_id: UUID, step_ids: list[UUID]) -> dict[UUID, dict[str, Any]]:
    """Fetch process_name, step_name, and execution_data for multiple execution steps in one query.
    Returns step_id -> { process_name, step_name, source_step_completed_by, source_step_execution_prompts }.
    Same shape as execution modal card expand."""
    if not step_ids:
        return {}
    steps = (
        session.query(ExecutionStep)
        .join(Execution, ExecutionStep.execution_id == Execution.id)
        .filter(ExecutionStep.id.in_(step_ids), Execution.org_id == org_id)
        .options(
            joinedload(ExecutionStep.step),
            joinedload(ExecutionStep.execution).joinedload(Execution.process),
        )
        .all()
    )
    result: dict[UUID, dict[str, Any]] = {}
    for s in steps:
        ed_meta = _step_metadata_from_execution_data(s.execution_data)
        process = s.execution.process if s.execution and getattr(s.execution, "process", None) else None
        result[s.id] = {
            "process_id": str(s.execution.process_id) if s.execution else None,
            "process_name": process.name if process else None,
            "step_name": s.step.name if s.step else None,
            "source_step_completed_by": ed_meta["source_step_completed_by"],
            "source_step_execution_prompts": ed_meta["source_step_execution_prompts"],
        }
    return result


def _needs_reconciliation(item: InventoryItem) -> bool:
    """Same logic as execution modal: include if qty > 0 or remaining_balance_to_reconcile > 0."""
    from decimal import Decimal

    def _qty(v):
        try:
            return Decimal(str(v)) if v is not None else None
        except Exception:
            return None

    qty = _qty(item.quantity) or Decimal("0")
    if qty > 0:
        return True
    remaining = _qty((item.extra_data or {}).get("remaining_balance_to_reconcile")) or Decimal("0")
    return remaining > 0


def run_untracked_items_check(org_id: UUID, session: Session) -> CheckResult:
    """
    Find inventory items flagged as untracked that still need reconciliation (same criteria as
    execution modal: quantity > 0 OR remaining_balance_to_reconcile > 0).
    Uses InventoryRepository.get_untracked_items for canonical state; check remains projection only.
    """
    from decimal import Decimal

    def _qty(v):
        try:
            return Decimal(str(v)) if v is not None else None
        except Exception:
            return None

    try:
        # Fetch all untracked (qty 0 and qty > 0), then filter by same "needs reconciliation" rule as modal
        untracked_orm = InventoryRepository(session).get_untracked_items(
            org_id=org_id,
            quantity_gt_zero=False,
        )
        untracked_orm = [i for i in untracked_orm if _needs_reconciliation(i)]
    except Exception as e:
        _log.warning("get_untracked_items failed, falling back to direct query: %s", e)
        # Correctness fallback for a failed repo call, not a hot path — a LIMIT here would
        # silently drop items needing reconciliation rather than flag them.
        untracked_orm = (  # nosemgrep: sqlalchemy-all-without-limit
            session.query(InventoryItem)
            .filter(
                InventoryItem.org_id == org_id,
                InventoryItem.extra_data.isnot(None),
            )
            .all()
        )
        untracked_orm = [
            i for i in untracked_orm if (i.extra_data or {}).get("untracked") is True and _needs_reconciliation(i)
        ]

    # Batch fetch execution step metadata to avoid N+1 queries
    step_ids = list({i.source_execution_step_id for i in untracked_orm if i.source_execution_step_id})
    step_meta_by_id = _batch_fetch_step_metadata(session, org_id, step_ids)

    # Fallback: for items with source_execution_id but no process_id from step (e.g. step deleted), get process from execution
    execution_ids_fallback = set()
    for i in untracked_orm:
        if not i.source_execution_id:
            continue
        meta = step_meta_by_id.get(i.source_execution_step_id) if i.source_execution_step_id else None
        if not meta or not meta.get("process_id"):
            execution_ids_fallback.add(i.source_execution_id)
    execution_fallback: dict[str, dict[str, Any]] = {}
    if execution_ids_fallback:
        try:
            executions = (
                session.query(Execution)
                .filter(Execution.id.in_(execution_ids_fallback), Execution.org_id == org_id)
                .options(joinedload(Execution.process))
                .all()
            )
            for e in executions:
                execution_fallback[str(e.id)] = {
                    "process_id": str(e.process_id) if e.process_id else None,
                    "process_name": e.process.name if e.process else None,
                }
        except Exception as e:
            _log.debug("Execution fallback for untracked process_id failed: %s", e)

    # Resolve producing step (step that defines the output) per item for reconcile guidance
    process_ids_set = {
        step_meta.get("process_id") for step_meta in step_meta_by_id.values() if step_meta.get("process_id")
    }
    for meta in execution_fallback.values():
        if meta.get("process_id"):
            process_ids_set.add(meta["process_id"])
    process_ids = list(process_ids_set)
    process_repo = ProcessRepository(session)
    processes_by_id: dict[str, Any] = {}
    process_uuids = []
    for pid in process_ids:
        try:
            process_uuids.append(UUID(pid))
        except (ValueError, TypeError):
            pass
    if process_uuids:
        by_uuid = process_repo.get_processes_with_steps(process_uuids, org_id)
        processes_by_id = {str(uid): p for uid, p in by_uuid.items()}

    untracked_items: list[dict[str, Any]] = []
    for item in untracked_orm:
        extra = item.extra_data or {}
        remaining = extra.get("remaining_balance_to_reconcile")
        notes = extra.get("notes")
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
            "remaining_balance_to_reconcile": str(remaining) if remaining is not None else None,
            "notes": notes if notes is not None else None,
            "extra_data": extra,
            "check_reason": "Untracked inventory item",
            "reconciliation_required": True,
        }
        step_meta = step_meta_by_id.get(item.source_execution_step_id) or {
            "process_id": None,
            "process_name": None,
            "step_name": None,
            "source_step_completed_by": None,
            "source_step_execution_prompts": {},
        }
        base["process_id"] = step_meta.get("process_id")
        base["process_name"] = step_meta.get("process_name")
        if not base["process_id"] and item.source_execution_id:
            fallback = execution_fallback.get(str(item.source_execution_id)) or {}
            base["process_id"] = fallback.get("process_id")
            if not base["process_name"] and fallback.get("process_name"):
                base["process_name"] = fallback.get("process_name")
        base["step_name"] = step_meta.get("step_name")
        base["source_step_completed_by"] = step_meta["source_step_completed_by"]
        base["source_step_execution_prompts"] = step_meta["source_step_execution_prompts"]
        # Producing step = step that defines the output (for reconcile: "execute this step"); fallback to step_name
        producing_step_id: Any = None
        producing_step_name: str | None = None
        if base.get("process_id"):
            process = processes_by_id.get(base["process_id"])
            producing_step_id, producing_step_name = _find_producing_step(process, item.name, item.unit)
        base["producing_step_id"] = str(producing_step_id) if producing_step_id else None
        base["producing_step_name"] = producing_step_name
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
