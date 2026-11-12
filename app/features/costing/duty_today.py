"""Duty if sold today on the batch cost card (live-cogs 8.1f-3b, spec Q6).

Measured by the nz_alcohol excise module on each output's produced quantity; costing never
computes rates. Adds ``duty_today`` to each output and returns the batch-level summary.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from app.features.costing.engine import money


def attach(db_session: Session, org_id: UUID, result: dict) -> dict:
    """Attach today's excise measure to produced-flow quantities, keeping rates in the module."""
    from app.features.compliant.modules.nz_alcohol import excise
    from app.features.compliant.service import nz_alcohol_active
    from app.features.costing.purchase_sources import nz_today

    on = nz_today()
    outputs = result.get("outputs", [])
    if not nz_alcohol_active(db_session, org_id):
        untracked = {"tracked": False, "on": on.isoformat(), "per_unit": None, "total": None, "landed_per_unit": None}
        for output in outputs:
            output["duty_today"] = dict(untracked)
        return untracked

    from app.core.db.models.inventory_item import InventoryItem

    lot_ids = [UUID(output["inventory_item_id"]) for output in outputs]
    lots = (
        {
            item.id: item
            for item in db_session.query(InventoryItem)
            .filter(InventoryItem.org_id == org_id, InventoryItem.id.in_(set(lot_ids)))
            .all()
        }
        if lot_ids
        else {}
    )
    pairs = [
        (lots[item_id], Decimal(str(output["quantity"])))
        for output, item_id in zip(outputs, lot_ids, strict=True)
        if item_id in lots
    ]
    measured = excise.measure(db_session, org_id, pairs, on)
    duty_by_lot = {}
    for (item, quantity), measure in zip(pairs, measured, strict=True):
        duty_by_lot.setdefault(item.id, []).append((quantity, measure))

    shaped = []
    for output, item_id in zip(outputs, lot_ids, strict=True):
        quantity = Decimal(str(output["quantity"]))
        rows = duty_by_lot.get(item_id, [])
        measure = rows.pop(0)[1] if rows else {"duty": None}
        duty = Decimal(str(measure["duty"])) if measure.get("duty") is not None else None
        per_unit = duty / quantity if duty is not None and quantity else None
        production_unit_cost = Decimal(str(output["unit_cost"])) if output.get("unit_cost") is not None else None
        landed = production_unit_cost + per_unit if production_unit_cost is not None and per_unit is not None else None
        values = {
            "tracked": True,
            "on": on.isoformat(),
            "per_unit": money(per_unit),
            "total": money(duty),
            "landed_per_unit": money(landed),
        }
        if duty is None:
            values["missing"] = measure.get("reason") or "Not an excise product or no rate set"
        output["duty_today"] = values
        shaped.append(values)

    if len(shaped) == 1:
        return dict(shaped[0])
    complete = bool(shaped) and all(row["total"] is not None for row in shaped)
    total = sum((Decimal(row["total"]) for row in shaped), Decimal("0")) if complete else None
    summary = {
        "tracked": True,
        "on": on.isoformat(),
        "per_unit": None,
        "total": money(total),
        "landed_per_unit": None,
    }
    if not complete and shaped:
        summary["missing"] = next(row["missing"] for row in shaped if row["total"] is None)
    return summary
