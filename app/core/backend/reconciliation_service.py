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
from app.core.db.models.execution_step import ExecutionStep
from app.core.db.models.inventory_item import InventoryItem, InventoryType
from app.core.db.repositories.execution_repo import ExecutionRepository
from app.core.db.repositories.inventory_repo import InventoryRepository
from app.core.utils.unit_conversion import are_units_compatible, convert_to_inventory_unit

_log = logging.getLogger(__name__)

_UNTRACKED_FILTER = {"untracked": True}


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
        total += _quantity_consumed_from_inputs_list(
            current_step_actual_inputs, inventory_item_id, ref_unit
        )
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
    By default only includes items with quantity > 0. When execution_id is set, also
    includes items with quantity 0 that were consumed in that execution (so user can
    reconcile the producing step to the same untracked item).
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
        if qty is None or qty < 0:
            continue
        if qty <= 0 and execution_id:
            try:
                item_uuid = UUID(item.get("id") or "")
            except (ValueError, TypeError):
                continue
            consumed = _quantity_consumed_from_item_in_execution(
                session, execution_id, item_uuid, unit_clean
            )
            if not consumed or consumed <= 0:
                continue
        elif qty <= 0:
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
    Path B (legacy): Map to Execution Output. Creates a new execution, completes the given step
    with one output, creates one inventory item from that output, and reduces the untracked item.
    Preferred approach: complete an execution step in the execution modal with optional
    untracked_item_id per output; the complete_step flow uses reconcile_output_to_untracked.
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
    When current_step_actual_inputs is provided, consumption from this step is included when
    computing effective balance (so we detect usage even before the DB reflects the commit).
    """
    inv_repo = InventoryRepository(session)
    untracked = inv_repo.get_inventory_item_by_id(untracked_item_id, org_id)
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
    history.append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user_id": user_id,
        "user_email": user_email,
        "method": "map_to_untracked_at_completion",
        "execution_id": str(execution_id),
        "execution_step_id": str(execution_step_id),
        "quantity_reconciled": str(reconciliation_amount),
        "surplus_to_live": str(surplus),
    })
    new_extra = dict(untracked.extra_data or {})
    new_extra["reconciliation_history"] = history
    # Persist remaining balance so SQL/UI can show correct "balance to reconcile" without
    # deriving from consumed/reconciled (which would wrongly treat reconciled qty as offsetting consumed).
    new_extra["remaining_balance_to_reconcile"] = (
        "0" if remaining_to_reconcile <= 0 else str(remaining_to_reconcile)
    )
    if remaining_to_reconcile <= 0 or abs(remaining_to_reconcile) < Decimal("0.0001"):
        new_extra["untracked"] = False
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
    Legacy: reduces untracked and updates output item extra_data. Prefer using
    reconcile_output_to_untracked_reduce_only and then creating output with quantity=surplus only.
    """
    inv_repo = InventoryRepository(session)
    untracked = inv_repo.get_inventory_item_by_id(untracked_item_id, org_id)
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

    history = list((untracked.extra_data or {}).get("reconciliation_history") or [])
    history.append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user_id": user_id,
        "user_email": user_email,
        "method": "map_to_untracked_at_completion",
        "execution_id": str(execution_id),
        "execution_step_id": str(execution_step_id),
        "output_inventory_item_id": str(output_inventory_item_id),
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
