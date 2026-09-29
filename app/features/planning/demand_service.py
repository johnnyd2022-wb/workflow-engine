"""Explicit production demand; every lookup requires an authenticated org."""

from datetime import date
from decimal import Decimal, InvalidOperation
from uuid import UUID

from app.core.db.models.step import Step
from app.core.utils.unit_conversion import is_count_unit
from app.features.planning.models import PlanningDemand

MAX_QUANTITY = Decimal("99999999999999.9999")


def output_catalog(db, org_id: UUID) -> list[dict]:
    catalog = []
    seen = set()
    for step in db.query(Step).filter(Step.org_id == org_id).order_by(Step.process_id, Step.position).all():
        for output in step.outputs or []:
            if not isinstance(output, dict):
                continue
            try:
                identity = UUID(str(output.get("id", "")))
            except ValueError:
                continue
            unit = output.get("unit")
            if unit is None:
                unit = "units"
            if not isinstance(unit, str) or not unit.strip() or len(unit.strip()) > 50:
                continue
            if identity in seen:
                continue
            seen.add(identity)
            catalog.append(
                {
                    "id": str(identity),
                    "name": str(output.get("name") or "Unnamed output"),
                    "unit": unit.strip(),
                    "process_id": str(step.process_id),
                }
            )
    return catalog


def demand_dict(row: PlanningDemand) -> dict:
    return {
        "id": str(row.id),
        "reference": row.reference,
        "source_output_id": str(row.source_output_id),
        "quantity": str(row.quantity),
        "unit": row.unit,
        "due_date": row.due_date.isoformat(),
        "priority": row.priority,
        "status": row.status,
    }


def list_demands(db, org_id: UUID) -> list[dict]:
    rows = (
        db.query(PlanningDemand)
        .filter(PlanningDemand.org_id == org_id)
        .order_by(
            PlanningDemand.due_date,
            PlanningDemand.priority.desc(),
            PlanningDemand.id,
        )
        .all()
    )
    return [demand_dict(row) for row in rows]


def create_demand(db, org_id: UUID, data: dict) -> PlanningDemand:
    if not isinstance(data, dict):
        raise ValueError("Demand must be an object")
    if set(data) - {"reference", "source_output_id", "quantity", "due_date", "priority"}:
        raise ValueError("Unexpected demand fields")
    reference = data.get("reference")
    if not isinstance(reference, str) or not reference.strip() or len(reference.strip()) > 200:
        raise ValueError("Enter an order or demand reference, at most 200 characters")
    try:
        output_id = UUID(str(data.get("source_output_id", "")))
        quantity = Decimal(str(data.get("quantity", "")))
        due = date.fromisoformat(data.get("due_date", ""))
    except (ValueError, TypeError, InvalidOperation) as exc:
        raise ValueError("Choose an output, positive quantity and ISO due date") from exc
    if not quantity.is_finite() or not 0 < quantity <= MAX_QUANTITY or quantity.as_tuple().exponent < -4:
        raise ValueError("Quantity must be positive with at most four decimal places")
    priority = data.get("priority", 0)
    if isinstance(priority, bool) or not isinstance(priority, int) or not 0 <= priority <= 100:
        raise ValueError("Priority must be a whole number from 0 to 100")
    output = next((row for row in output_catalog(db, org_id) if row["id"] == str(output_id)), None)
    if output is None:
        raise ValueError("Choose an output belonging to this business")
    if is_count_unit(output["unit"]) and quantity != quantity.to_integral_value():
        raise ValueError("Counted units must be whole quantities")
    row = PlanningDemand(
        org_id=org_id,
        reference=reference.strip(),
        source_output_id=output_id,
        quantity=quantity,
        unit=output["unit"],
        due_date=due,
        priority=priority,
    )
    db.add(row)
    db.flush()
    return row


def cancel_demand(db, org_id: UUID, demand_id: UUID) -> PlanningDemand | None:
    row = (
        db.query(PlanningDemand)
        .filter(
            PlanningDemand.org_id == org_id,
            PlanningDemand.id == demand_id,
        )
        .with_for_update()
        .first()
    )
    if row is None:
        return None
    if row.status == "fulfilled":
        raise ValueError("A fulfilled demand cannot be cancelled")
    row.status = "cancelled"
    db.flush()
    return row
