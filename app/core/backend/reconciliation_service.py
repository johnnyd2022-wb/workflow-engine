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

from app.core.backend.checks.untracked_items import run_untracked_items_check
from app.core.backend.corechecks import CoreChecksRunner
from app.core.db.models.inventory_item import InventoryItem, InventoryType
from app.core.db.repositories.execution_repo import ExecutionRepository
from app.core.db.repositories.inventory_repo import InventoryRepository

_log = logging.getLogger(__name__)

_UNTRACKED_FILTER = {"untracked": True}


def _parse_quantity(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def get_matching_untracked(
    org_id: UUID,
    session: Session,
    name: str,
    unit: str,
    process_id: UUID | None = None,
) -> list[dict[str, Any]]:
    """
    Return untracked inventory items matching name and unit (and optionally process scope).
    Only includes items with quantity > 0. Process scope: when process_id is set,
    only return untracked items whose source execution belongs to that process.
    """
    runner = CoreChecksRunner(org_id=org_id, session=session)
    result = runner.run_check("untracked_items")
    if not result or not result.data or not result.data.get("untracked_items"):
        return []

    items = result.data["untracked_items"]
    name_clean = (name or "").strip().lower()
    unit_clean = (unit or "").strip()

    matching = []
    for item in items:
        if (item.get("name") or "").strip().lower() != name_clean:
            continue
        if (item.get("unit") or "").strip() != unit_clean:
            continue
        qty = _parse_quantity(item.get("quantity"))
        if qty is None or qty <= 0:
            continue
        if process_id:
            # Filter by process: untracked item must have source_execution in this process
            from app.core.db.models.execution import Execution

            src_exec_id = item.get("source_execution_id")
            if not src_exec_id:
                continue
            try:
                exec_uuid = UUID(src_exec_id)
            except ValueError:
                continue
            ex = session.query(Execution).filter(
                Execution.id == exec_uuid,
                Execution.org_id == org_id,
                Execution.process_id == process_id,
            ).first()
            if not ex:
                continue
        matching.append(item)
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

    - If untracked_item_id is set: reconciliation_amount = min(added_quantity, untracked_balance);
      reduce untracked balance, append reconciliation history, then add full quantity as live inventory.
    - If no mapping: create standard inventory addition (no change to untracked).
    """
    from datetime import date as date_type

    inv_repo = InventoryRepository(session)
    added_qty = _parse_quantity(quantity)
    if added_qty is None or added_qty <= 0:
        return {"error": "Invalid or non-positive quantity"}

    # Optional: reduce untracked and record reconciliation
    reconciled_amount = Decimal("0")
    surplus = added_qty
    if untracked_item_id:
        untracked = inv_repo.get_inventory_item_by_id(untracked_item_id, org_id)
        if not untracked:
            return {"error": "Untracked item not found"}
        if (untracked.extra_data or {}).get("untracked") is not True:
            return {"error": "Item is not an untracked item"}
        try:
            untracked_balance = _parse_quantity(untracked.quantity)
        except Exception:
            untracked_balance = Decimal("0")
        if untracked_balance is None or untracked_balance <= 0:
            return {"error": "Untracked item has no balance to reconcile"}

        # Unit must match
        if (unit or "").strip() != (untracked.unit or "").strip():
            return {"error": "Unit mismatch: cannot reconcile with different unit"}

        reconciliation_amount = min(added_qty, untracked_balance)
        new_untracked_qty = untracked_balance - reconciliation_amount
        reconciled_amount = reconciliation_amount
        surplus = added_qty - reconciliation_amount

        # Update untracked item: reduce quantity, append history, clear untracked if zero
        history = list((untracked.extra_data or {}).get("reconciliation_history") or [])
        history.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "user_id": user_id,
            "user_email": user_email,
            "method": "add_to_inventory",
            "quantity_reconciled": str(reconciliation_amount),
            "surplus_to_live": str(surplus),
        })
        new_extra = dict(untracked.extra_data or {})
        new_extra["reconciliation_history"] = history
        if new_untracked_qty <= 0:
            new_extra["untracked"] = False
        inv_repo.update_inventory_item(
            item_id=untracked_item_id,
            org_id=org_id,
            quantity=str(new_untracked_qty) if new_untracked_qty > 0 else "0",
            extra_data=new_extra,
        )

    # Create new inventory item (live stock) with full added quantity
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
    if inv_type not in (InventoryType.RAW_MATERIAL.value, InventoryType.WORK_IN_PROGRESS.value, InventoryType.FINAL_PRODUCT.value):
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
    )

    return {
        "id": str(new_item.id),
        "name": new_item.name,
        "quantity": new_item.quantity,
        "unit": new_item.unit,
        "inventory_type": new_item.inventory_type,
        "reconciled_amount": str(reconciled_amount),
        "surplus": str(surplus),
    }


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
    Path B: Map to Execution Output. Creates an execution, completes the given step
    with one output, creates one inventory item from that output, and reduces
    the untracked item by reconciliation_amount.
    """
    inv_repo = InventoryRepository(session)
    exec_repo = ExecutionRepository(session)

    untracked = inv_repo.get_inventory_item_by_id(untracked_item_id, org_id)
    if not untracked:
        return {"error": "Untracked item not found"}
    if (untracked.extra_data or {}).get("untracked") is not True:
        return {"error": "Item is not an untracked item"}

    untracked_balance = _parse_quantity(untracked.quantity)
    if untracked_balance is None or untracked_balance <= 0:
        return {"error": "Untracked item has no balance to reconcile"}

    qty_produced = _parse_quantity(output_quantity)
    if qty_produced is None or qty_produced <= 0:
        return {"error": "Invalid or non-positive quantity produced"}

    if (output_unit or "").strip() != (untracked.unit or "").strip():
        return {"error": "Unit mismatch: output unit must match untracked item unit"}

    reconciliation_amount = min(qty_produced, untracked_balance)
    surplus = qty_produced - reconciliation_amount
    new_untracked_qty = untracked_balance - reconciliation_amount

    # Create execution for the process
    execution = exec_repo.create_execution(org_id=org_id, process_id=process_id)
    session.refresh(execution)

    # Find execution step that corresponds to process step_id
    from app.core.db.models.execution_step import ExecutionStep, ExecutionStepStatus

    all_steps = (
        session.query(ExecutionStep)
        .filter(ExecutionStep.execution_id == execution.id)
        .order_by(ExecutionStep.step_number)
        .all()
    )
    exec_step = next((s for s in all_steps if s.step_id == step_id), None)
    if not exec_step:
        return {"error": "Step not found in this process"}

    # Complete any prior steps with empty outputs so we can complete the selected step
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
            )
    # Re-load exec_step after prior commits
    exec_step = (
        session.query(ExecutionStep)
        .filter(ExecutionStep.execution_id == execution.id, ExecutionStep.step_id == step_id)
        .first()
    )
    if not exec_step:
        return {"error": "Execution step not found after completing prior steps"}

    # Complete the step with one output (no inputs for reconciliation flow)
    actual_outputs = [{
        "name": output_name,
        "quantity": float(qty_produced),
        "unit": output_unit,
    }]
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
    )
    exec_step = (
        session.query(ExecutionStep)
        .filter(ExecutionStep.execution_id == execution.id, ExecutionStep.step_id == step_id)
        .first()
    )

    # Create one inventory item from the execution output (tracked)
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
        extra_data={"reconciled_via_execution": True, "untracked_item_id": str(untracked_item_id)},
    )

    # Reduce untracked item and append history
    history = list((untracked.extra_data or {}).get("reconciliation_history") or [])
    history.append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user_id": user_id,
        "user_email": user_email,
        "method": "map_to_execution",
        "process_id": str(process_id),
        "step_id": str(step_id),
        "execution_id": str(execution.id),
        "quantity_reconciled": str(reconciliation_amount),
        "surplus_to_live": str(surplus),
    })
    new_extra = dict(untracked.extra_data or {})
    new_extra["reconciliation_history"] = history
    if new_untracked_qty <= 0:
        new_extra["untracked"] = False
    inv_repo.update_inventory_item(
        item_id=untracked_item_id,
        org_id=org_id,
        quantity=str(new_untracked_qty) if new_untracked_qty > 0 else "0",
        extra_data=new_extra,
    )

    return {
        "execution_id": str(execution.id),
        "reconciled_amount": str(reconciliation_amount),
        "surplus": str(surplus),
        "inventory_created": True,
    }
