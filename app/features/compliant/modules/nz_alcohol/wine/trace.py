"""One wine lot's trace and mass balance, ready to hand to a Wine Officer (WSMP: trace
records within 24 hours).

Walks back from the lot through every winemaking step it came from: what each step used
and made, the loss in between, and the intake records at the root. An output larger than
its inputs (in the same unit) is flagged, because a volume that grew is either a missing
input or a typing error, and either one breaks the trace.
"""

from __future__ import annotations

import csv
import io
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.db.models.execution_step import ExecutionStep
from app.core.db.models.inventory_item import InventoryItem

from . import composition as comp_mod
from . import roles, rules

_MAX_STEPS = 60


def _sum(entries, unit=None) -> tuple[Decimal, str | None, bool]:
    total, units = Decimal(0), set()
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        qty = comp_mod._num(entry.get("quantity"))
        if qty is None:
            continue
        units.add(str(entry.get("unit") or ""))
        total += qty
    mixed = len(units) > 1
    return total, (next(iter(units)) if len(units) == 1 else None), mixed


def lot_trace(session: Session, org_id: UUID, lot_id: UUID, role_map: dict[UUID, str]) -> dict | None:
    root = session.query(InventoryItem).filter(InventoryItem.org_id == org_id, InventoryItem.id == lot_id).one_or_none()
    if root is None:
        return None
    steps, seen, queue = [], set(), [root.id]
    while queue and len(steps) < _MAX_STEPS:
        item_id = queue.pop(0)
        if item_id in seen:
            continue
        seen.add(item_id)
        item = (
            session.query(InventoryItem)
            .filter(InventoryItem.org_id == org_id, InventoryItem.id == item_id)
            .one_or_none()
        )
        if item is None or item.source_execution_step_id is None:
            continue
        step = (
            session.query(ExecutionStep)
            .filter(ExecutionStep.org_id == org_id, ExecutionStep.id == item.source_execution_step_id)
            .one_or_none()
        )
        if step is None:
            continue
        role = role_map.get(step.step_id)
        used, used_unit, used_mixed = _sum(step.actual_inputs)
        made, made_unit, _ = _sum(step.actual_outputs)
        data = step.execution_data or {}
        row = {
            "lot_id": str(item.id),
            "lot": item.name,
            "stage": roles.ROLE_LABELS.get(role or "", step.step.name if step.step else "Step"),
            "completed_at": step.completed_at.isoformat() if step.completed_at else None,
            "recorded_by": data.get("completed_by") or data.get("completed_by_email"),
            "inputs": [
                {
                    "lot_id": e.get("inventory_item_id"),
                    "name": e.get("name"),
                    "quantity": e.get("quantity"),
                    "unit": e.get("unit"),
                }
                for e in (step.actual_inputs or [])
                if isinstance(e, dict)
            ],
            "made": float(made),
            "made_unit": made_unit,
            "used": float(used),
            "used_unit": used_unit,
            "loss": None,
            "loss_pct": None,
            "flag": None,
        }
        if role == "intake":
            row["source"] = {
                "grower": data.get(rules.GROWER),
                "variety": data.get(rules.VARIETY),
                "vintage": data.get(rules.VINTAGE),
                "region": data.get(rules.REGION),
                "spray_diary": data.get(rules.SPRAY_DIARY),
            }
        elif used and not used_mixed and used_unit and used_unit == made_unit:
            loss = used - made
            row["loss"] = float(loss)
            row["loss_pct"] = float(round(loss / used * 100, 1))
            if loss < 0:
                row["flag"] = "Made more than it used: an input is missing or a quantity is wrong"
        for entry in step.actual_inputs or []:
            if isinstance(entry, dict) and entry.get("inventory_item_id"):
                try:
                    queue.append(UUID(str(entry["inventory_item_id"])))
                except ValueError:
                    continue
        steps.append(row)
    return {
        "lot": {"id": str(root.id), "name": root.name, "quantity": float(root.quantity or 0), "unit": root.unit},
        "steps": steps,
    }


def as_csv(trace: dict) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(
        [
            "Lot",
            "Stage",
            "Completed",
            "Recorded by",
            "Used",
            "Made",
            "Unit",
            "Loss %",
            "Grower",
            "Variety",
            "Vintage",
            "Region",
            "Spray diary",
            "Inputs",
            "Flag",
        ]
    )
    for row in trace["steps"]:
        src = row.get("source") or {}
        inputs = "; ".join(f"{i['name']} {i['quantity']} {i['unit']}" for i in row["inputs"])
        cells = [
            row["lot"], row["stage"], row["completed_at"] or "", row["recorded_by"] or "", row["used"], row["made"],
            row["made_unit"] or "", "" if row["loss_pct"] is None else row["loss_pct"], src.get("grower") or "",
            src.get("variety") or "", src.get("vintage") or "", src.get("region") or "", src.get("spray_diary") or "",
            inputs, row["flag"] or "",
        ]  # fmt: skip
        # A cell starting with = + - @ would run as a formula in a spreadsheet: quote it.
        writer.writerow([f"'{c}" if isinstance(c, str) and c[:1] in ("=", "+", "-", "@") else c for c in cells])
    return out.getvalue()
