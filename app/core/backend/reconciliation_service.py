"""
Untracked inventory reconciliation service.

Implements Path A (reconcile via Add to Inventory) and Path B (reconcile via
Map to Execution Output). New code only; does not modify existing inventory
or execution flows. All actions are audited in extra_data.reconciliation_history.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.db.models.execution_step import ExecutionStep
from app.core.db.models.inventory_item import InventoryType
from app.core.db.repositories.execution_repo import ExecutionRepository
from app.core.db.repositories.inventory_repo import InventoryRepository
from app.core.db.repositories.process_repo import ProcessRepository
from app.core.utils.unit_conversion import are_units_compatible, convert_to_inventory_unit

_log = logging.getLogger(__name__)


def _normalize_str(s: str | None) -> str:
    return ((s or "").strip()).lower()


def _find_producing_step(process: Any, item_name: str | None, item_unit: str | None) -> tuple[Any, str | None]:
    """Return (step_id, step_name) for the step that has an output matching (item_name, item_unit), or (None, None)."""
    if not process or not getattr(process, "steps", None):
        return (None, None)
    n_name = _normalize_str(item_name)
    n_unit = _normalize_str(item_unit)
    for step in process.steps:
        for out in step.outputs or []:
            if not isinstance(out, dict):
                continue
            if _normalize_str(out.get("name")) == n_name and _normalize_str(out.get("unit")) == n_unit:
                return (step.id, step.name)
    return (None, None)

_UNTRACKED_FILTER = {"untracked": True}

# Keys from execution_data we exclude from source_step_execution_prompts (internal only)
_EXECUTION_PROMPTS_INTERNAL = {
    "completed_by",
    "completed_by_email",
    "completed_by_user_id",
    "completed_at",
    "execution_errors",
    "execution_warnings",
}


def _parse_quantity(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _normalize_item_id(value: Any) -> str:
    """Normalize inventory_item_id for comparison (UUID string, lowercase)."""
    if value is None:
        return ""
    s = str(value).strip()
    try:
        return str(UUID(s)).lower()
    except (ValueError, TypeError):
        return s.lower()


def _quantity_consumed_from_inputs_list(
    inputs_list: list[dict[str, Any]],
    inventory_item_id: UUID,
    ref_unit: str,
) -> Decimal:
    """Sum quantity consumed from the given item in a single step's actual_inputs."""
    ref_unit = (ref_unit or "").strip()
    item_id_norm = _normalize_item_id(inventory_item_id)
    total = Decimal("0")
    for inp in inputs_list or []:
        if _normalize_item_id(inp.get("inventory_item_id")) != item_id_norm:
            continue
        q = _parse_quantity(inp.get("quantity"))
        if q is None or q <= 0:
            continue
        inp_unit = (inp.get("unit") or "").strip()
        if inp_unit and ref_unit and inp_unit != ref_unit:
            if are_units_compatible(inp_unit, ref_unit):
                try:
                    q = Decimal(str(convert_to_inventory_unit(float(q), inp_unit, ref_unit)))
                except (ValueError, TypeError):
                    pass
            else:
                continue
        total += q
    return total


def _quantity_consumed_from_item_in_execution(
    session: Session,
    execution_id: UUID,
    inventory_item_id: UUID,
    ref_unit: str,
    current_step_actual_inputs: list[dict[str, Any]] | None = None,
    current_step_id: UUID | None = None,
) -> Decimal:
    """
    Sum quantity consumed from the given inventory item across all steps of this execution.
    If current_step_actual_inputs is provided, its consumption is counted first (so we don't
    rely on the DB reflecting the just-committed step). Other steps are read from the DB;
    current_step_id is excluded when summing from DB to avoid double-counting.
    """
    total = Decimal("0")
    if current_step_actual_inputs:
        total += _quantity_consumed_from_inputs_list(current_step_actual_inputs, inventory_item_id, ref_unit)
    steps = (
        session.query(ExecutionStep)
        .filter(ExecutionStep.execution_id == execution_id, ExecutionStep.actual_inputs.isnot(None))
        .all()
    )
    ref_unit = (ref_unit or "").strip()
    item_id_norm = _normalize_item_id(inventory_item_id)
    for step in steps:
        if current_step_id is not None and step.id == current_step_id:
            continue
        for inp in step.actual_inputs or []:
            if _normalize_item_id(inp.get("inventory_item_id")) != item_id_norm:
                continue
            q = _parse_quantity(inp.get("quantity"))
            if q is None or q <= 0:
                continue
            inp_unit = (inp.get("unit") or "").strip()
            if inp_unit and ref_unit and inp_unit != ref_unit:
                if are_units_compatible(inp_unit, ref_unit):
                    try:
                        q = Decimal(str(convert_to_inventory_unit(float(q), inp_unit, ref_unit)))
                    except (ValueError, TypeError):
                        pass
                else:
                    continue
            total += q
    return total


def _untracked_item_to_dict(item: Any) -> dict[str, Any]:
    """Convert InventoryItem (untracked) to API-style dict with created_at, remaining_balance_to_reconcile, and notes."""
    if not hasattr(item, "id"):
        return {}
    extra = item.extra_data or {}
    remaining = extra.get("remaining_balance_to_reconcile")
    notes = extra.get("notes")
    return {
        "id": str(item.id),
        "name": item.name,
        "quantity": item.quantity,
        "unit": item.unit,
        "inventory_type": getattr(item, "inventory_type", None),
        "supplier": getattr(item, "supplier", None),
        "purchase_date": item.purchase_date.isoformat() if getattr(item, "purchase_date", None) else None,
        "source_execution_id": str(item.source_execution_id) if getattr(item, "source_execution_id", None) else None,
        "source_execution_step_id": str(item.source_execution_step_id)
        if getattr(item, "source_execution_step_id", None)
        else None,
        "created_at": item.created_at.isoformat() if getattr(item, "created_at", None) else None,
        "remaining_balance_to_reconcile": str(remaining) if remaining is not None else None,
        "notes": notes if notes is not None else None,
        "extra_data": extra,
    }


def _enrich_matching_untracked_with_step_metadata(
    session: Session, org_id: UUID, matching: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Add process_name, step_name, source_step_completed_by, source_step_execution_prompts to each item."""
    from app.core.db.models.execution import Execution

    step_ids = []
    for m in matching:
        sid = m.get("source_execution_step_id")
        if sid:
            try:
                step_ids.append(UUID(sid))
            except (ValueError, TypeError):
                pass
    if not step_ids:
        for m in matching:
            m.setdefault("process_name", None)
            m.setdefault("step_name", None)
            m.setdefault("source_step_completed_by", None)
            m.setdefault("source_step_execution_prompts", {})
        return matching

    from sqlalchemy.orm import joinedload

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
    meta_by_id: dict[UUID, dict[str, Any]] = {}
    for es in steps:
        ed = es.execution_data or {}
        meta_by_id[es.id] = {
            "process_id": str(es.execution.process_id) if es.execution else None,
            "process_name": es.execution.process.name
            if es.execution and getattr(es.execution, "process", None)
            else None,
            "step_name": es.step.name if es.step else None,
            "source_step_completed_by": ed.get("completed_by") or ed.get("completed_by_email"),
            "source_step_execution_prompts": {
                k: v for k, v in ed.items() if k not in _EXECUTION_PROMPTS_INTERNAL and v is not None and v != ""
            },
        }
    for m in matching:
        sid = m.get("source_execution_step_id")
        if sid:
            try:
                meta = meta_by_id.get(UUID(sid)) or {}
            except (ValueError, TypeError):
                meta = {}
        else:
            meta = {}
        m["process_id"] = meta.get("process_id")
        m["process_name"] = meta.get("process_name")
        m["step_name"] = meta.get("step_name")
        m["source_step_completed_by"] = meta.get("source_step_completed_by")
        m["source_step_execution_prompts"] = meta.get("source_step_execution_prompts") or {}
    return matching


def _enrich_producing_step_name(
    session: Session, org_id: UUID, matching: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Set producing_step_name (step that defines the output) for reconcile guidance; fallback to step_name."""
    if not matching:
        return matching
    process_ids = list({m.get("process_id") for m in matching if m.get("process_id")})
    process_repo = ProcessRepository(session)
    processes_by_id: dict[str, Any] = {}
    for pid in process_ids:
        try:
            p = process_repo.get_process_with_steps(UUID(pid), org_id)
            if p:
                processes_by_id[pid] = p
        except Exception:
            pass
    for m in matching:
        pid = m.get("process_id")
        process = processes_by_id.get(pid) if pid else None
        producing_step_id, producing_step_name = _find_producing_step(
            process, m.get("name"), m.get("unit")
        )
        m["producing_step_id"] = str(producing_step_id) if producing_step_id else None
        m["producing_step_name"] = producing_step_name
    return matching


def get_matching_untracked(
    org_id: UUID,
    session: Session,
    name: str,
    unit: str,
    process_id: UUID | None = None,
    execution_id: UUID | None = None,
) -> list[dict[str, Any]]:
    """
    Return untracked inventory items matching name and unit (and optionally process scope).
    Uses InventoryRepository.get_untracked_items (canonical inventory state). By default
    only includes items with quantity > 0. When execution_id is set, also includes items
    with quantity 0 that were consumed in that execution (so user can reconcile the
    producing step to the same untracked item).
    """
    inv_repo = InventoryRepository(session)
    quantity_gt_zero = execution_id is None
    items = inv_repo.get_untracked_items(
        org_id=org_id,
        name=name.strip() if name else None,
        unit=unit.strip() if unit else None,
        process_id=process_id,
        quantity_gt_zero=quantity_gt_zero,
    )
    unit_clean = (unit or "").strip()

    matching = []
    for item in items:
        # Repo already filtered by name/unit; only filter by qty, execution consumption, process
        qty = _parse_quantity(item.quantity)
        if qty is None or qty < 0:
            continue
        if qty <= 0 and execution_id:
            # Include qty 0 when: consumed in this execution, OR still has remaining_balance_to_reconcile (e.g. partial reconcile)
            remaining = _parse_quantity((item.extra_data or {}).get("remaining_balance_to_reconcile"))
            if remaining is not None and remaining > 0:
                pass  # include
            else:
                consumed = _quantity_consumed_from_item_in_execution(session, execution_id, item.id, unit_clean)
                if not consumed or consumed <= 0:
                    continue
        elif qty <= 0:
            continue
        if process_id:
            if not item.source_execution_id:
                continue
            from app.core.db.models.execution import Execution

            ex = (
                session.query(Execution)
                .filter(
                    Execution.id == item.source_execution_id,
                    Execution.org_id == org_id,
                    Execution.process_id == process_id,
                )
                .first()
            )
            if not ex:
                continue
        matching.append(_untracked_item_to_dict(item))

    # Enrich with process name, step name, and step metadata (completed_by, execution_prompts)
    matching = _enrich_matching_untracked_with_step_metadata(session, org_id, matching)
    # Producing step = step that defines the output (for "execute this step" in reconcile guidance)
    matching = _enrich_producing_step_name(session, org_id, matching)
    return matching


def reconcile_via_addition(
    org_id: UUID,
    session: Session,
    user_id: str | None,
    user_email: str | None,
    name: str,
    quantity: str | float,
    unit: str,
    inventory_type: str,
    untracked_item_id: UUID | None,
    purchase_date: str | None = None,
    supplier: str | None = None,
    supplier_batch_number: str | None = None,
    expiry_date: str | None = None,
) -> dict[str, Any]:
    """
    Path A: Add to Inventory with optional mapping to an untracked item.
    Runs in a single atomic transaction with row-level lock on untracked item when mapping.
    Does not auto-clear untracked flag; sets resolved/resolved_at for audit lineage.
    """
    from datetime import date as date_type

    inv_repo = InventoryRepository(session)
    added_qty = _parse_quantity(quantity)
    if added_qty is None or added_qty <= 0:
        return {"error": "Invalid or non-positive quantity"}

    reconciled_amount = Decimal("0")
    surplus = added_qty
    remaining_untracked_balance = "0"

    try:
        if untracked_item_id:
            untracked = inv_repo.get_inventory_item_by_id_for_update(untracked_item_id, org_id)
            if not untracked:
                return {"error": "Untracked item not found"}
            if (untracked.extra_data or {}).get("untracked") is not True:
                return {"error": "Item is not an untracked item"}
            untracked_balance = _parse_quantity(untracked.quantity) or Decimal("0")
            if untracked_balance <= 0:
                return {"error": "Untracked item has no balance to reconcile"}
            if (unit or "").strip() != (untracked.unit or "").strip():
                return {"error": "Unit mismatch: cannot reconcile with different unit"}

            reconciliation_amount = min(added_qty, untracked_balance)
            new_untracked_qty = untracked_balance - reconciliation_amount
            reconciled_amount = reconciliation_amount
            surplus = added_qty - reconciliation_amount
            remaining_untracked_balance = str(new_untracked_qty) if new_untracked_qty > 0 else "0"

            ts = datetime.now(timezone.utc).isoformat()
            history = list((untracked.extra_data or {}).get("reconciliation_history") or [])
            history.append(
                {
                    "timestamp": ts,
                    "user_id": user_id,
                    "user_email": user_email,
                    "method": "add_to_inventory",
                    "quantity_reconciled": str(reconciliation_amount),
                    "surplus_to_live": str(surplus),
                }
            )
            new_extra = dict(untracked.extra_data or {})
            new_extra["reconciliation_history"] = history
            new_extra["untracked"] = True
            if new_untracked_qty <= 0:
                new_extra["resolved"] = True
                new_extra["resolved_at"] = ts
            inv_repo.update_inventory_item(
                item_id=untracked_item_id,
                org_id=org_id,
                quantity=remaining_untracked_balance,
                extra_data=new_extra,
                commit=False,
            )

        purchase_date_parsed = None
        if purchase_date:
            try:
                purchase_date_parsed = date_type.fromisoformat(purchase_date.replace("Z", "").split("T")[0])
            except (ValueError, TypeError):
                pass
        expiry_date_parsed = None
        if expiry_date:
            try:
                expiry_date_parsed = date_type.fromisoformat(expiry_date.replace("Z", "").split("T")[0])
            except (ValueError, TypeError):
                pass

        inv_type = inventory_type or InventoryType.RAW_MATERIAL.value
        if inv_type not in (
            InventoryType.RAW_MATERIAL.value,
            InventoryType.WORK_IN_PROGRESS.value,
            InventoryType.FINAL_PRODUCT.value,
        ):
            inv_type = InventoryType.RAW_MATERIAL.value

        new_item = inv_repo.create_inventory_item(
            org_id=org_id,
            name=name,
            quantity=str(added_qty),
            unit=unit,
            inventory_type=inv_type,
            supplier=supplier,
            purchase_date=purchase_date_parsed,
            supplier_batch_number=supplier_batch_number,
            expiry_date=expiry_date_parsed,
            extra_data={"reconciled_via_addition": True} if untracked_item_id else None,
            commit=False,
        )

        session.commit()
        return {
            "id": str(new_item.id),
            "name": new_item.name,
            "quantity": new_item.quantity,
            "unit": new_item.unit,
            "inventory_type": new_item.inventory_type,
            "reconciled_amount": str(reconciled_amount),
            "surplus": str(surplus),
            "remaining_untracked_balance": remaining_untracked_balance,
        }
    except Exception:
        session.rollback()
        raise


def reconcile_via_execution(
    org_id: UUID,
    session: Session,
    user_id: str | None,
    user_email: str | None,
    untracked_item_id: UUID,
    process_id: UUID,
    step_id: UUID,
    output_name: str,
    output_quantity: str | float,
    output_unit: str,
    output_date: str | None = None,
) -> dict[str, Any]:
    """
    Path B: Map to Execution Output. Creates a new execution, completes the given step
    with one output, creates one inventory item from that output, and reduces the untracked item.
    Atomic transaction with row-level lock; idempotency guard for same process/step; no float;
    audit linkage on new inventory; does not auto-clear untracked (sets resolved/resolved_at).
    """
    inv_repo = InventoryRepository(session)
    exec_repo = ExecutionRepository(session)

    untracked = inv_repo.get_inventory_item_by_id_for_update(untracked_item_id, org_id)
    if not untracked:
        return {"error": "Untracked item not found"}
    if (untracked.extra_data or {}).get("untracked") is not True:
        session.rollback()
        return {"error": "Item is not an untracked item"}

    # Idempotency guard: block if already reconciled against this process step
    history = list((untracked.extra_data or {}).get("reconciliation_history") or [])
    if any(
        h.get("method") == "map_to_execution"
        and h.get("process_id") == str(process_id)
        and h.get("step_id") == str(step_id)
        for h in history
    ):
        session.rollback()
        return {"error": "This untracked item has already been reconciled against this process step."}

    untracked_balance = _parse_quantity(untracked.quantity) or Decimal("0")
    if untracked_balance <= 0:
        session.rollback()
        return {"error": "Untracked item has no balance to reconcile"}

    qty_produced = _parse_quantity(output_quantity)
    if qty_produced is None or qty_produced <= 0:
        session.rollback()
        return {"error": "Invalid or non-positive quantity produced"}

    if (output_unit or "").strip() != (untracked.unit or "").strip():
        session.rollback()
        return {"error": "Unit mismatch: output unit must match untracked item unit"}

    reconciliation_amount = min(qty_produced, untracked_balance)
    surplus = qty_produced - reconciliation_amount
    new_untracked_qty = untracked_balance - reconciliation_amount
    remaining_untracked_balance = str(new_untracked_qty) if new_untracked_qty > 0 else "0"

    try:
        execution = exec_repo.create_execution(org_id=org_id, process_id=process_id, commit=False)
        session.flush()

        from app.core.db.models.execution_step import ExecutionStep, ExecutionStepStatus

        all_steps = (
            session.query(ExecutionStep)
            .filter(ExecutionStep.execution_id == execution.id)
            .order_by(ExecutionStep.step_number)
            .all()
        )
        exec_step = next((s for s in all_steps if s.step_id == step_id), None)
        if not exec_step:
            session.rollback()
            return {"error": "Step not found in this process"}

        for prior in all_steps:
            if prior.step_number >= exec_step.step_number:
                break
            if prior.status != ExecutionStepStatus.COMPLETED:
                exec_repo.complete_step(
                    execution_step_id=prior.id,
                    org_id=org_id,
                    actual_inputs=[],
                    actual_outputs=[],
                    execution_data={"completed_by": user_email, "reconciliation_via_execution": True},
                    commit=False,
                )
        session.flush()
        session.refresh(exec_step)

        # Quantity as string (no float) for precision
        actual_outputs = [
            {
                "name": output_name,
                "quantity": str(qty_produced),
                "unit": output_unit,
            }
        ]
        execution_data = {
            "completed_by": user_email,
            "completed_by_user_id": user_id,
            "reconciliation_via_execution": True,
            "untracked_item_id": str(untracked_item_id),
        }
        exec_repo.complete_step(
            execution_step_id=exec_step.id,
            org_id=org_id,
            actual_inputs=[],
            actual_outputs=actual_outputs,
            execution_data=execution_data,
            commit=False,
        )
        session.flush()
        # Single re-query for updated step (actual_outputs, etc.) for create_inventory_item
        exec_step = (
            session.query(ExecutionStep)
            .filter(ExecutionStep.execution_id == execution.id, ExecutionStep.step_id == step_id)
            .first()
        )

        inventory_type = InventoryType.FINAL_PRODUCT.value
        if exec_step and getattr(exec_step, "is_terminal_step", None) is False:
            inventory_type = InventoryType.WORK_IN_PROGRESS.value
        inv_repo.create_inventory_item(
            org_id=org_id,
            name=output_name,
            quantity=str(qty_produced),
            unit=output_unit,
            inventory_type=inventory_type,
            source_execution_id=execution.id,
            source_execution_step_id=exec_step.id,
            source_step_name=exec_step.step.name if exec_step.step else None,
            extra_data={
                "reconciled_via_execution": True,
                "untracked_item_id": str(untracked_item_id),
                "reconciliation_amount": str(reconciliation_amount),
                "surplus_from_reconciliation": str(surplus),
            },
            commit=False,
        )

        ts = datetime.now(timezone.utc).isoformat()
        history = list((untracked.extra_data or {}).get("reconciliation_history") or [])
        history.append(
            {
                "timestamp": ts,
                "user_id": user_id,
                "user_email": user_email,
                "method": "map_to_execution",
                "process_id": str(process_id),
                "step_id": str(step_id),
                "execution_id": str(execution.id),
                "quantity_reconciled": str(reconciliation_amount),
                "surplus_to_live": str(surplus),
            }
        )
        new_extra = dict(untracked.extra_data or {})
        new_extra["reconciliation_history"] = history
        new_extra["untracked"] = True
        if new_untracked_qty <= 0:
            new_extra["resolved"] = True
            new_extra["resolved_at"] = ts
        inv_repo.update_inventory_item(
            item_id=untracked_item_id,
            org_id=org_id,
            quantity=remaining_untracked_balance,
            extra_data=new_extra,
            commit=False,
        )

        session.commit()
        return {
            "execution_id": str(execution.id),
            "reconciled_amount": str(reconciliation_amount),
            "surplus": str(surplus),
            "remaining_untracked_balance": remaining_untracked_balance,
            "inventory_created": True,
        }
    except Exception:
        session.rollback()
        raise


def reconcile_output_to_untracked_reduce_only(
    org_id: UUID,
    session: Session,
    user_id: str | None,
    user_email: str | None,
    untracked_item_id: UUID,
    output_quantity: Decimal,
    output_unit: str,
    output_name: str,
    execution_id: UUID,
    execution_step_id: UUID,
    current_step_actual_inputs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Reduce the untracked item by the reconciliation amount (min of output qty and untracked balance).
    Does NOT create or update any output inventory item. Returns reconciled_amount and surplus.
    Caller should create an output item only when surplus > 0, with quantity = surplus.
    Uses row-level lock (FOR UPDATE) for concurrency safety when two completions hit the same untracked item.
    When current_step_actual_inputs is provided, consumption from this step is included when
    computing effective balance (so we detect usage even before the DB reflects the commit).
    """
    inv_repo = InventoryRepository(session)
    untracked = inv_repo.get_inventory_item_by_id_for_update(untracked_item_id, org_id)
    if not untracked:
        return {"error": "Untracked item not found"}
    if (untracked.extra_data or {}).get("untracked") is not True:
        return {"error": "Item is not an untracked item"}
    if (output_unit or "").strip() != (untracked.unit or "").strip():
        return {"error": "Unit mismatch: output unit must match untracked item unit"}
    if (output_name or "").strip().lower() != (untracked.name or "").strip().lower():
        return {"error": "Name mismatch: output name must match untracked item name"}

    untracked_balance = _parse_quantity(untracked.quantity)
    if untracked_balance is None:
        untracked_balance = Decimal("0")
    if output_quantity is None or output_quantity <= 0:
        return {"error": "Output quantity must be positive"}

    # Authoritative "balance still to reconcile" (set when creating untracked or after each reconcile).
    # Use it so partial reconciliations don't get confused with consumption (e.g. 4 kg created,
    # 1 kg consumed, reconcile 1 kg -> remaining should be 3 kg, not 2).
    stored_remaining = _parse_quantity((untracked.extra_data or {}).get("remaining_balance_to_reconcile"))
    if stored_remaining is not None and stored_remaining < 0:
        stored_remaining = Decimal("0")

    # Cap for this operation: we can only reconcile up to on-hand (or consumed in this execution if 0 on hand).
    effective_balance = untracked_balance
    if effective_balance <= 0:
        consumed_in_execution = _quantity_consumed_from_item_in_execution(
            session,
            execution_id,
            untracked_item_id,
            untracked.unit or "",
            current_step_actual_inputs=current_step_actual_inputs,
            current_step_id=execution_step_id,
        )
        if consumed_in_execution and consumed_in_execution > 0:
            effective_balance = consumed_in_execution
        else:
            effective_balance = output_quantity

    # How much we can reconcile this time: min of output qty, cap from on-hand/consumed, and stored remaining.
    if stored_remaining is not None and stored_remaining >= 0:
        reconciliation_amount = min(output_quantity, effective_balance, stored_remaining)
        remaining_to_reconcile = stored_remaining - reconciliation_amount
    else:
        reconciliation_amount = min(output_quantity, effective_balance)
        remaining_to_reconcile = effective_balance - reconciliation_amount

    surplus = output_quantity - reconciliation_amount
    # Only reduce DB quantity if there was remaining balance; if already 0 (consumed earlier), leave 0
    new_untracked_qty = max(Decimal("0"), untracked_balance - reconciliation_amount)

    history = list((untracked.extra_data or {}).get("reconciliation_history") or [])
    history.append(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "user_id": user_id,
            "user_email": user_email,
            "method": "map_to_untracked_at_completion",
            "execution_id": str(execution_id),
            "execution_step_id": str(execution_step_id),
            "quantity_reconciled": str(reconciliation_amount),
            "surplus_to_live": str(surplus),
        }
    )
    new_extra = dict(untracked.extra_data or {})
    new_extra["reconciliation_history"] = history
    # Persist remaining balance so SQL/UI can show correct "balance to reconcile" without
    # deriving from consumed/reconciled (which would wrongly treat reconciled qty as offsetting consumed).
    new_extra["remaining_balance_to_reconcile"] = "0" if remaining_to_reconcile <= 0 else str(remaining_to_reconcile)
    new_extra["untracked"] = True
    if remaining_to_reconcile <= 0 or abs(remaining_to_reconcile) < Decimal("0.0001"):
        ts = datetime.now(timezone.utc).isoformat()
        new_extra["resolved"] = True
        new_extra["resolved_at"] = ts
    inv_repo.update_inventory_item(
        item_id=untracked_item_id,
        org_id=org_id,
        quantity=str(new_untracked_qty) if new_untracked_qty > 0 else "0",
        extra_data=new_extra,
    )

    return {
        "reconciled_amount": str(reconciliation_amount),
        "surplus": str(surplus),
    }


def reconcile_output_to_untracked(
    org_id: UUID,
    session: Session,
    user_id: str | None,
    user_email: str | None,
    untracked_item_id: UUID,
    output_quantity: Decimal,
    output_unit: str,
    output_name: str,
    execution_id: UUID,
    execution_step_id: UUID,
    output_inventory_item_id: UUID,
) -> dict[str, Any]:
    """
    Reconcile an existing execution output (already created inventory item) to an untracked item.

    DEPRECATED: Prefer the completion flow that uses reconcile_output_to_untracked_reduce_only
    and creates output with quantity=surplus only. This legacy path is hardened for consistency
    (row lock, conditional resolved, remaining_balance_to_reconcile) but should not be used for new code.
    """
    inv_repo = InventoryRepository(session)
    untracked = inv_repo.get_inventory_item_by_id_for_update(untracked_item_id, org_id)
    if not untracked:
        return {"error": "Untracked item not found"}
    if (untracked.extra_data or {}).get("untracked") is not True:
        return {"error": "Item is not an untracked item"}
    if (output_unit or "").strip() != (untracked.unit or "").strip():
        return {"error": "Unit mismatch: output unit must match untracked item unit"}
    if (output_name or "").strip().lower() != (untracked.name or "").strip().lower():
        return {"error": "Name mismatch: output name must match untracked item name"}

    untracked_balance = _parse_quantity(untracked.quantity)
    if untracked_balance is None or untracked_balance <= 0:
        return {"error": "Untracked item has no balance to reconcile"}
    if output_quantity is None or output_quantity <= 0:
        return {"error": "Output quantity must be positive"}

    reconciliation_amount = min(output_quantity, untracked_balance)
    surplus = output_quantity - reconciliation_amount
    new_untracked_qty = untracked_balance - reconciliation_amount
    remaining_balance = str(new_untracked_qty) if new_untracked_qty > 0 else "0"

    history = list((untracked.extra_data or {}).get("reconciliation_history") or [])
    history.append(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "user_id": user_id,
            "user_email": user_email,
            "method": "map_to_untracked_at_completion",
            "execution_id": str(execution_id),
            "execution_step_id": str(execution_step_id),
            "output_inventory_item_id": str(output_inventory_item_id),
            "quantity_reconciled": str(reconciliation_amount),
            "surplus_to_live": str(surplus),
        }
    )
    new_extra = dict(untracked.extra_data or {})
    new_extra["reconciliation_history"] = history
    new_extra["untracked"] = True
    new_extra["remaining_balance_to_reconcile"] = remaining_balance
    if new_untracked_qty <= 0:
        ts = datetime.now(timezone.utc).isoformat()
        new_extra["resolved"] = True
        new_extra["resolved_at"] = ts
    inv_repo.update_inventory_item(
        item_id=untracked_item_id,
        org_id=org_id,
        quantity=remaining_balance,
        extra_data=new_extra,
    )

    output_item = inv_repo.get_inventory_item_by_id(output_inventory_item_id, org_id)
    if output_item and output_item.extra_data is not None:
        out_extra = dict(output_item.extra_data)
    else:
        out_extra = {}
    out_extra["reconciled_untracked_item_id"] = str(untracked_item_id)
    out_extra["quantity_reconciled"] = str(reconciliation_amount)
    out_extra["surplus_to_live"] = str(surplus)
    inv_repo.update_inventory_item(
        item_id=output_inventory_item_id,
        org_id=org_id,
        extra_data=out_extra,
    )

    return {
        "reconciled_amount": str(reconciliation_amount),
        "surplus": str(surplus),
    }
