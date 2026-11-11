"""Cost readiness per product (live-cogs 8.1e-1; spec "8.1e-1 build contract").

A product is a step output definition (`output:<id>`), or a legacy name bucket (`name:<n>`)
for finished lots without one. Its materials come from its latest batch (walked back through
earlier batches, each once) or, with no batch yet, from its process's declared step inputs.
Read-only.
"""

from __future__ import annotations

from collections import deque
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.db.models.inventory_item import InventoryItem, InventoryType
from app.core.db.models.process import Process
from app.core.db.models.step import Step
from app.features.costing.engine import ACTUAL, ESTIMATED, CostEngine, normalise
from app.features.costing.models import CostFlow
from app.features.costing.service import CostingNotFoundError

FINAL = InventoryType.FINAL_PRODUCT.value


def _uuid(raw) -> UUID | None:
    try:
        return UUID(str(raw))
    except (ValueError, TypeError):
        return None


def _definitions(db: Session, org_id: UUID) -> dict[str, tuple[str, Step]]:
    """Terminal-step output definitions with an id: id -> (name, step)."""
    steps = db.query(Step).join(Process, Process.id == Step.process_id).filter(Process.org_id == org_id).all()
    last = {}
    for step in steps:
        if step.process_id not in last or step.step_number > last[step.process_id].step_number:
            last[step.process_id] = step
    found = {}
    for step in last.values():
        for out in step.outputs or []:
            if isinstance(out, dict) and out.get("id") and _uuid(out.get("id")):
                found[str(out["id"])] = (str(out.get("name") or "").strip(), step)
    return found


def _products(db: Session, org_id: UUID) -> dict[str, dict]:
    defs = _definitions(db, org_id)
    products = {f"output:{oid}": {"name": name, "output_id": oid, "step": step} for oid, (name, step) in defs.items()}
    finished = (
        db.query(InventoryItem).filter(InventoryItem.org_id == org_id, InventoryItem.inventory_type == FINAL).all()
    )
    for item in finished:
        if (item.extra_data or {}).get("library_stock"):
            continue
        if item.source_output_id:
            key = f"output:{item.source_output_id}"
            products.setdefault(key, {"name": item.name.strip(), "output_id": str(item.source_output_id), "step": None})
        else:
            norm = normalise(item.name)
            if norm:
                products.setdefault(f"name:{norm}", {"name": item.name.strip(), "name_key": norm, "step": None})
    return products


def _latest_execution(db: Session, org_id: UUID, product: dict):
    query = db.query(CostFlow).filter(CostFlow.org_id == org_id, CostFlow.kind == "produced")
    if product.get("output_id"):
        query = query.filter(CostFlow.source_output_id == _uuid(product["output_id"]))
        flow = query.order_by(CostFlow.created_at.desc(), CostFlow.id.desc()).first()
        return flow.execution_id if flow else None
    # legacy bucket: produced lots of that name without an output id
    for flow in query.filter(CostFlow.source_output_id.is_(None)).order_by(
        CostFlow.created_at.desc(), CostFlow.id.desc()
    ):
        item = (
            db.query(InventoryItem)
            .filter(InventoryItem.org_id == org_id, InventoryItem.id == flow.inventory_item_id)
            .one_or_none()
        )
        if item is not None and normalise(item.name) == product["name_key"]:
            return flow.execution_id
    return None


def _materials_from_batch(db: Session, org_id: UUID, execution_id, engine: CostEngine) -> list[dict]:
    seen, queue, lots = {execution_id}, deque([execution_id]), {}
    while queue:
        current = queue.popleft()
        flows = db.query(CostFlow).filter(CostFlow.org_id == org_id, CostFlow.execution_id == current).all()
        produced_here = {f.inventory_item_id for f in flows if f.direction == "in"}
        for f in flows:
            if f.direction != "out" or f.inventory_item_id in produced_here:
                continue
            upstream = (
                db.query(CostFlow.execution_id)
                .filter(
                    CostFlow.org_id == org_id,
                    CostFlow.inventory_item_id == f.inventory_item_id,
                    CostFlow.direction == "in",
                    CostFlow.kind.in_(("produced", "reconciled_in")),
                )
                .all()
            )
            if upstream:
                for (eid,) in upstream:
                    if eid not in seen:
                        seen.add(eid)
                        queue.append(eid)
                continue
            lots[f.inventory_item_id] = True
    rows = []
    for item_id in lots:
        cost = engine.lot(item_id)
        rows.append(
            {
                "name": cost["name"],
                "inventory_item_id": str(item_id),
                "costed": cost["status"] in (ACTUAL, ESTIMATED),
                "status": cost["status"],
            }
        )
    return sorted(rows, key=lambda r: (r["name"] or "", r["inventory_item_id"]))


def _materials_from_declaration(db: Session, org_id: UUID, step: Step, engine: CostEngine) -> list[dict]:
    steps = db.query(Step).filter(Step.process_id == step.process_id).order_by(Step.step_number).all()
    names = {}
    for s in steps:
        for raw in s.inputs or []:
            name = (raw.get("name") if isinstance(raw, dict) else raw) or ""
            if normalise(name):
                names.setdefault(normalise(name), str(name).strip())
    index = engine._material_index()
    rows = []
    for norm, name in names.items():
        costed = any(
            engine._is_direct(lot) and engine._direct_cost(lot).status == ACTUAL for lot in index.get(norm, [])
        )
        rows.append(
            {"name": name, "inventory_item_id": None, "costed": costed, "status": "actual" if costed else "unknown"}
        )
    return sorted(rows, key=lambda r: r["name"])


def product_detail(db: Session, org_id: UUID, key: str, *, products=None, engine=None) -> dict:
    products = _products(db, org_id) if products is None else products
    product = products.get(key)
    if product is None:
        raise CostingNotFoundError("Product not found")
    engine = engine or CostEngine(db, org_id)
    execution_id = _latest_execution(db, org_id, product)
    if execution_id is not None:
        basis, materials = "latest_batch", _materials_from_batch(db, org_id, execution_id, engine)
    elif product.get("step") is not None:
        basis, materials = "declared_inputs", _materials_from_declaration(db, org_id, product["step"], engine)
    else:
        basis, materials = "declared_inputs", []
    return {
        "key": key,
        "name": product["name"],
        "basis": basis,
        "execution_id": str(execution_id) if execution_id else None,
        "ready": bool(materials) and all(m["costed"] for m in materials),
        "materials": materials,
    }


def list_products(db: Session, org_id: UUID) -> list[dict]:
    products = _products(db, org_id)
    engine = CostEngine(db, org_id)
    out = []
    for key in products:
        detail = product_detail(db, org_id, key, products=products, engine=engine)
        out.append(
            {
                "key": key,
                "name": detail["name"],
                "ready": detail["ready"],
                "materials_total": len(detail["materials"]),
                "materials_costed": sum(1 for m in detail["materials"] if m["costed"]),
            }
        )
    return sorted(out, key=lambda p: (p["name"].casefold(), p["key"]))
