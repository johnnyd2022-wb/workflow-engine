"""Reconstruct ``cost_flows`` for stock that existed before the live hooks (live-cogs 8.1a).

Spec .agents/specs/live-cogs.md, "Backfill". Idempotent: every row uses the same
``source_key`` the live hook would have used, and inserts are ON CONFLICT DO NOTHING, so a rerun
or a later live write never records a movement twice. One org per call; never crosses orgs.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.db.models.entity_event import EntityEvent
from app.core.db.models.execution_step import ExecutionStep
from app.core.db.models.inventory_item import InventoryItem
from app.core.domain.inventory_quantity_guard import InventoryQuantityWriteReason
from app.core.utils.packs import convert_for_lot
from app.features.costing.flows import add_key, consume_key, create_key, created_kind, insert_flow


def _dec(value) -> Decimal | None:
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return d if d.is_finite() else None


def _in_lot_unit(quantity: Decimal, unit: str | None, lot: InventoryItem) -> Decimal | None:
    lot_unit = lot.unit or ""
    if not (unit or "").strip() or (unit or "").strip().lower() == lot_unit.strip().lower():
        return quantity
    try:
        return convert_for_lot(quantity, unit, lot)  # through the lot's pack when it has one
    except (ValueError, InvalidOperation, ZeroDivisionError):
        return None


def backfill_flows(db: Session, org_id: UUID) -> dict:
    """Returns ``{"inserted", "skipped_inputs"}``. Caller commits."""
    lots = {lot.id: lot for lot in db.query(InventoryItem).filter(InventoryItem.org_id == org_id).all()}
    steps = (
        db.query(ExecutionStep).filter(ExecutionStep.org_id == org_id, ExecutionStep.actual_inputs.isnot(None)).all()
    )
    inserted = 0
    skipped_inputs = 0

    # consumed: per completed step x input lot, summed in the lot's unit
    consumed_by_lot: dict[UUID, Decimal] = defaultdict(Decimal)
    consumed_rows = []
    for step in steps:
        if step.completed_at is None and str(getattr(step.status, "value", step.status)).lower() != "completed":
            continue
        per_lot: dict[UUID, Decimal] = defaultdict(Decimal)
        for row in step.actual_inputs or []:
            if not isinstance(row, dict) or not row.get("inventory_item_id"):
                continue
            try:
                item_id = UUID(str(row["inventory_item_id"]))
            except (ValueError, TypeError):
                skipped_inputs += 1
                continue
            lot = lots.get(item_id)
            q = _dec(row.get("quantity"))
            converted = _in_lot_unit(q, row.get("unit"), lot) if lot is not None and q is not None else None
            if converted is None or converted <= 0:
                skipped_inputs += 1
                continue
            per_lot[item_id] += converted
        for item_id, q in per_lot.items():
            consumed_by_lot[item_id] += q
            consumed_rows.append((step, item_id, q))

    # created / produced / transfer_in: the earliest created event's quantity, else a floor
    created_qty: dict[UUID, Decimal] = {}
    added_rows = []
    events = (
        db.query(EntityEvent)
        .filter(
            EntityEvent.org_id == org_id,
            EntityEvent.entity_type == "inventory_item",
            EntityEvent.event_type.in_(("inventory_item.created", "inventory_item.quantity_adjusted")),
        )
        .order_by(EntityEvent.seq)
        .all()
    )
    add_reason = InventoryQuantityWriteReason.REPOSITORY_ADD_QUANTITY.value
    for event in events:
        if event.entity_id not in lots:
            continue
        payload = event.payload or {}
        if event.event_type == "inventory_item.created":
            q = _dec(payload.get("quantity"))
            if q is not None and event.entity_id not in created_qty:
                created_qty[event.entity_id] = q
        elif payload.get("reason") == add_reason:
            delta = _dec(payload.get("delta"))
            if delta is not None and delta > 0:
                added_rows.append((event, delta))

    step_numbers = {
        row.id: row.step_number
        for row in db.query(ExecutionStep.id, ExecutionStep.step_number).filter(ExecutionStep.org_id == org_id)
    }
    for lot in lots.values():
        quantity = created_qty.get(lot.id)
        if quantity is None:
            quantity = (_dec(lot.quantity) or Decimal("0")) + consumed_by_lot.get(lot.id, Decimal("0"))
        kind = created_kind(lot)
        from_execution = kind == "produced"
        if from_execution and lot.source_execution_step_id not in step_numbers:
            skipped_inputs += 1  # provenance outside this org: never follow it
            continue
        step_number = step_numbers.get(lot.source_execution_step_id) if from_execution else None
        inserted += insert_flow(
            db,
            org_id=org_id,
            inventory_item_id=lot.id,
            direction="in",
            kind=kind,
            quantity=quantity,
            source_key=create_key(lot.id),
            write_reason="backfill",
            execution_id=lot.source_execution_id if from_execution else None,
            execution_step_id=lot.source_execution_step_id if from_execution else None,
            step_number=step_number,
            source_output_id=lot.source_output_id if from_execution else None,
            reconstructed=True,
        )

    for event, delta in added_rows:
        inserted += insert_flow(
            db,
            org_id=org_id,
            inventory_item_id=event.entity_id,
            direction="in",
            kind="added",
            quantity=delta,
            source_key=add_key(event.id),
            write_reason="backfill",
            reconstructed=True,
        )

    for step, item_id, q in consumed_rows:
        inserted += insert_flow(
            db,
            org_id=org_id,
            inventory_item_id=item_id,
            direction="out",
            kind="consumed",
            quantity=q,
            source_key=consume_key(step.id, item_id),
            write_reason="backfill",
            execution_id=step.execution_id,
            execution_step_id=step.id,
            step_number=step.step_number,
            reconstructed=True,
        )

    return {"inserted": int(inserted), "skipped_inputs": skipped_inputs}
