"""Confirmed contract order lines become planner demand, and stay in step (GL-P07 B3).

Idempotent: running it twice with nothing changed writes nothing. It runs under the org planning
lock, so two syncs (a contract order save and the planner page loading) can't both create a
demand for the same line; the partial unique index on (org_id, source_ref) backs that up.

- A confirmed line mapped to a workflow output gets one open demand (source='contract').
- A changed line updates its demand while no batch of it has started. Unstarted batches are
  cancelled, because they were sized for the old quantity or date. After a start the demand is
  left alone and says why.
- A line that is no longer confirmed cancels its demand by the planner's cancel rules; a
  completed order's demand is marked fulfilled.
- Lines without a workflow output are listed, never matched by product name.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from uuid import UUID

from app.core.utils.unit_conversion import convert_quantity_decimal, is_count_unit
from app.features.contract_manufacturing.models.orders import ContractOrder, ContractOrderLine
from app.features.contract_manufacturing.services.demand import contract_demand
from app.features.planning.batch_models import PlanningBatch
from app.features.planning.demand_service import MAX_QUANTITY, cancel_demand, output_catalog
from app.features.planning.models import PlanningDemand

NOT_CONFIRMED = "The contract order is no longer confirmed"
UNPLANNABLE = "The order line can't be planned until it has a workflow output it's made by"
SYNC_CANCELLED = (NOT_CONFIRMED, UNPLANNABLE)


def _started(db, org_id, demand_id) -> bool:
    return (
        db.query(PlanningBatch.id)
        .filter(
            PlanningBatch.org_id == org_id,
            PlanningBatch.demand_id == demand_id,
            PlanningBatch.status == "started",
        )
        .first()
        is not None
    )


def _drop_unstarted_batches(db, org_id, demand_id) -> int:
    from app.features.planning.material_adapter import close_commitments

    batches = (
        db.query(PlanningBatch)
        .filter(
            PlanningBatch.org_id == org_id,
            PlanningBatch.demand_id == demand_id,
            PlanningBatch.status.in_(("blocked", "planned")),
        )
        .with_for_update()
        .populate_existing()
        .all()
    )
    for batch in batches:
        batch.status = "cancelled"
        batch.revision += 1
        close_commitments(db, org_id, batch.id, "released")
    return len(batches)


def _quantity(line, output):
    """The line in the output's unit, or (None, reason)."""
    try:
        quantity = convert_quantity_decimal(Decimal(line["quantity"]), line["unit"], output["unit"])
    except (TypeError, ValueError, InvalidOperation):
        return None, f"Ordered in {line['unit']}, which can't be counted as {output['unit']}"
    if is_count_unit(output["unit"]) and quantity != quantity.to_integral_value():
        return None, f"{quantity.normalize():f} {output['unit']} is not a whole number"
    if not 0 < quantity <= MAX_QUANTITY:
        return None, "The ordered quantity can't be planned"
    return quantity.quantize(Decimal("0.0001")), None


def sync_contract_demand(db, org_id: UUID) -> dict:
    from app.features.planning.batch_service import _lock_org

    _lock_org(db, org_id)
    lines = contract_demand(db, org_id)
    catalog = {row["id"]: row for row in output_catalog(db, org_id)}
    order_refs = dict(
        db.query(ContractOrder.id, ContractOrder.reference)
        .filter(ContractOrder.org_id == org_id, ContractOrder.id.in_({UUID(line["order_id"]) for line in lines}))
        .all()
        if lines
        else []
    )
    existing = {
        row.source_ref: row
        for row in db.query(PlanningDemand)
        .filter(PlanningDemand.org_id == org_id, PlanningDemand.source == "contract")
        .with_for_update()
        .populate_existing()
        .all()
    }
    result = {"changes": [], "held": [], "unmapped": []}

    def change(action, row):
        result["changes"].append((action, row))

    def hold(row, note):
        if row.source_note != note:
            row.source_note = note
        result["held"].append({"demand_id": str(row.id), "reference": row.reference, "note": note})

    seen, unplannable = set(), set()
    for line in lines:
        order_reference = order_refs.get(UUID(line["order_id"]), "")
        output = catalog.get(line["product_key"]) if line["product_key"] else None
        quantity, problem = (None, "Choose the workflow output this product is made by")
        if output is not None:
            quantity, problem = _quantity(line, output)
        if problem:
            result["unmapped"].append(
                {
                    "line_id": line["demand_id"],
                    "order_id": line["order_id"],
                    "order_reference": order_reference,
                    "product_name": line["product_name"],
                    "quantity": line["quantity"],
                    "unit": line["unit"],
                    "reason": problem,
                }
            )
            unplannable.add(line["demand_id"])
            continue
        seen.add(line["demand_id"])
        reference = f"{order_reference} · {line['product_name']}"[:200]
        due = date.fromisoformat(line["due_date"])
        row = existing.get(line["demand_id"])
        if row is None:
            row = PlanningDemand(
                org_id=org_id,
                reference=reference,
                source_output_id=UUID(output["id"]),
                quantity=quantity,
                unit=output["unit"],
                due_date=due,
                priority=0,
                source="contract",
                source_ref=line["demand_id"],
            )
            db.add(row)
            db.flush()
            change("planning_demand_synced_created", row)
            continue
        if row.status == "fulfilled" or (row.status == "cancelled" and row.source_note not in SYNC_CANCELLED):
            # Done, or cancelled by someone in the planner: a sync doesn't undo that.
            continue
        wanted = (reference, UUID(output["id"]), quantity, output["unit"], due)
        current = (row.reference, row.source_output_id, row.quantity, row.unit, row.due_date)
        if row.status == "cancelled":
            row.status = "open"
            row.reference, row.source_output_id, row.quantity, row.unit, row.due_date = wanted
            row.source_note = None
            change("planning_demand_synced_reopened", row)
            continue
        if wanted == current:
            if row.source_note and not _started(db, org_id, row.id):
                row.source_note = None
            elif row.source_note:
                result["held"].append({"demand_id": str(row.id), "reference": row.reference, "note": row.source_note})
            continue
        if _started(db, org_id, row.id) or line["execution_ids"]:
            hold(
                row,
                f"The order now asks for {quantity.normalize():f} {output['unit']} by {due.isoformat()}, "
                "but a batch has started; review the plan",
            )
            continue
        row.reference, row.source_output_id, row.quantity, row.unit, row.due_date = wanted
        row.source_note = None
        _drop_unstarted_batches(db, org_id, row.id)
        change("planning_demand_synced_updated", row)

    completed = {
        str(line_id)
        for (line_id,) in db.query(ContractOrderLine.id)
        .join(
            ContractOrder,
            (ContractOrder.org_id == ContractOrderLine.org_id) & (ContractOrder.id == ContractOrderLine.order_id),
        )
        .filter(ContractOrderLine.org_id == org_id, ContractOrder.status == "completed")
        .all()
    }
    for ref, row in existing.items():
        if ref in seen or row.status != "open":
            continue
        if ref in completed:
            _drop_unstarted_batches(db, org_id, row.id)
            row.status = "fulfilled"
            row.source_note = None
            change("planning_demand_synced_fulfilled", row)
            continue
        why = UNPLANNABLE if ref in unplannable else NOT_CONFIRMED
        try:
            cancel_demand(db, org_id, row.id)
        except ValueError:
            hold(row, why + ", but a batch has started; review it")
            continue
        row.source_note = why
        change("planning_demand_synced_cancelled", row)
    db.flush()
    return result


def summary(result: dict) -> dict:
    """The JSON a route returns: counts, held demands and lines that need a workflow output."""
    counts: dict[str, int] = {}
    for action, _ in result["changes"]:
        name = action.removeprefix("planning_demand_synced_")
        counts[name] = counts.get(name, 0) + 1
    return {"changes": counts, "held": result["held"], "unmapped": result["unmapped"]}


def sync_after_order_change(db, org_id: UUID, user_id) -> None:
    """Run after a contract order or line save has committed. The order save never waits on or
    fails because of planning: a failure here is logged, and the planner page syncs on load."""
    import structlog
    from sqlalchemy.exc import SQLAlchemyError

    from app.core.db.models.audit_log import AuditLog

    try:
        from datetime import date as _date

        from app.features.planning.replan import replan

        result = sync_contract_demand(db, org_id)
        for event in replan(db, org_id, today=_date.today(), trigger="contract_order_saved"):
            result["changes"].append((f"planning_batch_auto_{event.kind}", event))
        for action, row in result["changes"]:
            db.add(
                AuditLog(
                    org_id=org_id,
                    user_id=user_id,
                    action=action,
                    entity="planning_batch" if action.startswith("planning_batch_") else "planning_demand",
                    entity_id=row.batch_id if action.startswith("planning_batch_") else row.id,
                    meta_data={"reason": row.reason}
                    if action.startswith("planning_batch_")
                    else {"source_output_id": str(row.source_output_id), "source_ref": row.source_ref},
                )
            )
        db.commit()
    except (ValueError, SQLAlchemyError) as exc:
        db.rollback()
        structlog.get_logger(__name__).warning(
            "planning_contract_sync_failed", org_id=str(org_id), error=type(exc).__name__
        )
