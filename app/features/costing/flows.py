"""Core's hooks into costing: one ``cost_flows`` row per stock write cost cares about.

Called from ``InventoryRepository.create_inventory_item`` / ``add_quantity_to_inventory_item``
and from ``complete_step``, inside the stock write's own transaction. Plain inserts, no cost
logic, so they cannot fail independently of the write. Keys are shared with the backfill
(``backfill.py``), and the insert is ON CONFLICT DO NOTHING on ``(org_id, source_key)``, so a
live write and a backfill can never both record the same stock movement.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.utils.time import utc_now


def _qty(value: Any) -> Decimal | None:
    try:
        quantity = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not quantity.is_finite() or quantity <= 0:
        return None
    return quantity.quantize(Decimal("0.0001"))


def created_kind(item) -> str:
    """Spec precedence: a transfer destination copies production provenance, so check it first."""
    if getattr(item, "transfer_receipt_id", None):
        return "transfer_in"
    if getattr(item, "source_execution_step_id", None):
        return "produced"
    return "created"


def create_key(item_id: UUID) -> str:
    return f"create:{item_id}"


def add_key(event_id: UUID) -> str:
    return f"add:{event_id}"


def consume_key(execution_step_id: UUID, item_id: UUID) -> str:
    return f"consume:{execution_step_id}:{item_id}"


def reconcile_key(execution_step_id: UUID, untracked_item_id: UUID, output_ref: str) -> str:
    return f"reconcile:{execution_step_id}:{untracked_item_id}:{output_ref}"


def insert_flow(
    db: Session,
    *,
    org_id: UUID,
    inventory_item_id: UUID,
    direction: str,
    kind: str,
    quantity: Any,
    source_key: str,
    write_reason: str,
    execution_id: UUID | None = None,
    execution_step_id: UUID | None = None,
    step_number: int | None = None,
    source_output_id: UUID | None = None,
    reconstructed: bool = False,
) -> bool:
    """Insert one flow; returns False when the quantity isn't positive or the key exists."""
    from app.features.costing.models import CostFlow

    amount = _qty(quantity)
    if amount is None:
        return False
    stmt = (
        insert(CostFlow.__table__)
        .values(
            id=uuid4(),
            org_id=org_id,
            inventory_item_id=inventory_item_id,
            direction=direction,
            kind=kind,
            quantity=amount,
            execution_id=execution_id,
            execution_step_id=execution_step_id,
            step_number=step_number,
            source_output_id=source_output_id,
            source_key=source_key[:200],
            write_reason=str(write_reason)[:50],
            reconstructed=reconstructed,
            created_at=utc_now(),
        )
        .on_conflict_do_nothing(index_elements=["org_id", "source_key"])
    )
    return db.execute(stmt).rowcount > 0


def _step_number(db: Session, execution_step_id: UUID | None) -> int | None:
    if not execution_step_id:
        return None
    from app.core.db.models.execution_step import ExecutionStep

    row = db.query(ExecutionStep.step_number).filter(ExecutionStep.id == execution_step_id).first()
    return row[0] if row else None


def on_lot_created(db: Session, item, write_reason) -> None:
    kind = created_kind(item)
    from_execution = kind == "produced"
    insert_flow(
        db,
        org_id=item.org_id,
        inventory_item_id=item.id,
        direction="in",
        kind=kind,
        quantity=item.quantity,
        source_key=create_key(item.id),
        write_reason=getattr(write_reason, "value", write_reason),
        execution_id=item.source_execution_id if from_execution else None,
        execution_step_id=item.source_execution_step_id if from_execution else None,
        step_number=_step_number(db, item.source_execution_step_id) if from_execution else None,
        source_output_id=item.source_output_id if from_execution else None,
    )


def on_quantity_added(db: Session, item, delta: Decimal, event_id: UUID, write_reason) -> None:
    insert_flow(
        db,
        org_id=item.org_id,
        inventory_item_id=item.id,
        direction="in",
        kind="added",
        quantity=delta,
        source_key=add_key(event_id),
        write_reason=getattr(write_reason, "value", write_reason),
    )


def on_consumed(db: Session, *, org_id, item_id, quantity, execution_id, execution_step_id, step_number) -> None:
    insert_flow(
        db,
        org_id=org_id,
        inventory_item_id=item_id,
        direction="out",
        kind="consumed",
        quantity=quantity,
        source_key=consume_key(execution_step_id, item_id),
        write_reason="execution_step_inventory",
        execution_id=execution_id,
        execution_step_id=execution_step_id,
        step_number=step_number,
    )


def on_reconciled(
    db: Session,
    *,
    org_id,
    untracked_item_id,
    quantity,
    execution_id,
    execution_step_id,
    step_number,
    source_output_id,
    output_name: str,
) -> None:
    insert_flow(
        db,
        org_id=org_id,
        inventory_item_id=untracked_item_id,
        direction="in",
        kind="reconciled_in",
        quantity=quantity,
        source_key=reconcile_key(execution_step_id, untracked_item_id, str(source_output_id or output_name)),
        write_reason="execution_step_inventory",
        execution_id=execution_id,
        execution_step_id=execution_step_id,
        step_number=step_number,
        source_output_id=source_output_id,
    )


def resolve_output_id(output: dict, declared: list) -> tuple[UUID | None, str | None]:
    """Spec "Output identity": (definition id or None, error message or None)."""
    defs = [d for d in (declared or []) if isinstance(d, dict) and d.get("id")]
    sent = output.get("output_id")
    if sent not in (None, ""):
        for d in defs:
            if str(d.get("id")) == str(sent):
                try:
                    return UUID(str(sent)), None
                except (ValueError, TypeError):
                    return None, f"Output '{output.get('name')}' names an output this step doesn't have"
        return None, f"Output '{output.get('name')}' names an output this step doesn't have"
    name = str(output.get("name") or "").strip()
    matches = [d for d in defs if str(d.get("name") or "").strip() == name]
    if len(matches) != 1:
        return None, None
    try:
        return UUID(str(matches[0]["id"])), None
    except (ValueError, TypeError):
        return None, None
