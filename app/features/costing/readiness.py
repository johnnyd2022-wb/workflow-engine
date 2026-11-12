"""Cost readiness per product (live-cogs 8.1e-1; spec "8.1e-1 build contract").

A product is a step output definition (`output:<id>`), or a legacy name bucket (`name:<n>`)
for finished lots without one. Its materials come from its latest batch (walked back through
earlier batches, each once) or, with no batch yet, from its process's declared step inputs.
Read-only.
"""

from __future__ import annotations

from collections import defaultdict, deque
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.db.models.inventory_item import InventoryItem, InventoryType
from app.core.db.models.process import Process
from app.core.db.models.step import Step
from app.features.costing.engine import ACTUAL, ESTIMATED, CostEngine, TooLargeError, normalise, unit_str
from app.features.costing.models import CostFlow
from app.features.costing.service import CostingNotFoundError

FINAL = InventoryType.FINAL_PRODUCT.value


def _uuid(raw) -> UUID | None:
    try:
        return UUID(str(raw))
    except (ValueError, TypeError):
        return None


class _Graph:
    """Everything readiness reads, bulk-loaded once per request: steps by process, produced
    flows (latest batch per product), and the batch graph walked level by level across every
    product at once. Query count is bounded by graph depth, not by the number of products."""

    def __init__(self, db: Session, org_id: UUID):
        self.db, self.org_id = db, org_id
        steps = db.query(Step).join(Process, Process.id == Step.process_id).filter(Process.org_id == org_id).all()
        self.steps_by_process: dict = {}
        for step in steps:
            self.steps_by_process.setdefault(step.process_id, []).append(step)
        for group in self.steps_by_process.values():
            group.sort(key=lambda s: (s.position, str(s.id)))
        self.flows_by_exec: dict = {}
        self.producers: dict = {}  # item id -> execution ids that produced it

    def terminal_steps(self):
        # Terminal = last in position order, as executions are created (execution_repo);
        # ties on position broken by id so the answer is deterministic.
        return [group[-1] for group in self.steps_by_process.values() if group]

    def walk(self, roots) -> None:
        frontier = {r for r in roots if r is not None and r not in self.flows_by_exec}
        while frontier:
            ids = list(frontier)
            for eid in ids:
                self.flows_by_exec[eid] = []
            # nosemgrep: sqlalchemy-query-in-for-loop — one query per level of batch history, for every product at once.
            for flow in self.db.query(CostFlow).filter(CostFlow.org_id == self.org_id, CostFlow.execution_id.in_(ids)):
                self.flows_by_exec[flow.execution_id].append(flow)
            consumed = {
                f.inventory_item_id
                for eid in ids
                for f in self.flows_by_exec[eid]
                if f.direction == "out" and f.inventory_item_id not in self.producers
            }
            for item_id in consumed:
                self.producers[item_id] = set()
            if consumed:
                rows = self.db.query(CostFlow.inventory_item_id, CostFlow.execution_id).filter(
                    CostFlow.org_id == self.org_id,
                    CostFlow.inventory_item_id.in_(consumed),
                    CostFlow.direction == "in",
                    CostFlow.kind.in_(("produced", "reconciled_in")),
                )
                for item_id, eid in rows:
                    self.producers[item_id].add(eid)
            frontier = {
                eid
                for item_id in consumed
                for eid in self.producers[item_id]
                if eid is not None and eid not in self.flows_by_exec
            }


def _products(db: Session, org_id: UUID, graph: _Graph) -> dict[str, dict]:
    products = {}
    for step in graph.terminal_steps():
        for out in step.outputs or []:
            if isinstance(out, dict) and out.get("id") and _uuid(out.get("id")):
                oid = str(out["id"])
                products[f"output:{oid}"] = {"name": str(out.get("name") or "").strip(), "output_id": oid, "step": step}
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


def _latest_executions(db: Session, org_id: UUID, products: dict) -> dict[str, UUID | None]:
    """Latest produced batch per product, two queries for the whole catalogue."""
    latest_by_output, latest_by_name = {}, {}
    produced = (
        db.query(CostFlow.source_output_id, CostFlow.execution_id, InventoryItem.name)
        .join(
            InventoryItem, (InventoryItem.org_id == CostFlow.org_id) & (InventoryItem.id == CostFlow.inventory_item_id)
        )
        .filter(CostFlow.org_id == org_id, CostFlow.kind == "produced")
        .order_by(CostFlow.created_at.desc(), CostFlow.id.desc())
    )
    for output_id, execution_id, name in produced:
        if output_id is not None:
            latest_by_output.setdefault(str(output_id), execution_id)
        else:  # legacy bucket: produced lots of that name without an output id
            latest_by_name.setdefault(normalise(name), execution_id)
    return {
        key: latest_by_output.get(p["output_id"]) if p.get("output_id") else latest_by_name.get(p["name_key"])
        for key, p in products.items()
    }


def _material_lots(graph: _Graph, execution_id) -> list:
    seen, queue, lots = {execution_id}, deque([execution_id]), {}
    while queue:
        current = queue.popleft()
        flows = graph.flows_by_exec.get(current, [])
        produced_here = {f.inventory_item_id for f in flows if f.direction == "in"}
        for f in flows:
            if f.direction != "out" or f.inventory_item_id in produced_here:
                continue
            upstream = graph.producers.get(f.inventory_item_id) or set()
            if upstream:
                for eid in upstream:
                    if eid not in seen:  # each earlier batch walked once, cycles included
                        seen.add(eid)
                        queue.append(eid)
                continue
            lots[f.inventory_item_id] = True
    return list(lots)


def _lot_rows(lot_ids, engine: CostEngine, cache: dict | None = None) -> list[dict]:
    """``cache``: one lot's cost, worked out once for every product that used it."""
    cache = {} if cache is None else cache
    rows = []
    for item_id in lot_ids:
        if item_id not in cache:
            cost = engine.lot(item_id)
            cache[item_id] = {
                "name": cost["name"],
                "inventory_item_id": str(item_id),
                "costed": cost["status"] in (ACTUAL, ESTIMATED),
                "status": cost["status"],
            }
        rows.append(dict(cache[item_id]))
    return sorted(rows, key=lambda r: (r["name"] or "", r["inventory_item_id"]))


def _declared_names(graph: _Graph, step: Step) -> dict[str, str]:
    names = {}
    for s in graph.steps_by_process.get(step.process_id, []):
        for raw in s.inputs or []:
            name = (raw.get("name") if isinstance(raw, dict) else raw) or ""
            if normalise(name):
                names.setdefault(normalise(name), str(name).strip())
    return names


def _declared_rows(names: dict[str, str], engine: CostEngine) -> list[dict]:
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


def _details(db: Session, org_id: UUID, keys=None) -> dict[str, dict]:
    graph = _Graph(db, org_id)
    products = _products(db, org_id, graph)
    if keys is not None:
        products = {k: products[k] for k in keys if k in products}
    latest = _latest_executions(db, org_id, products)
    graph.walk(latest.values())
    engine = CostEngine(db, org_id)
    lots_by_key = {key: _material_lots(graph, eid) for key, eid in latest.items() if eid is not None}
    declared = {
        key: _declared_names(graph, p["step"])
        for key, p in products.items()
        if latest.get(key) is None and p.get("step") is not None
    }
    material_lots = {lot for lots in lots_by_key.values() for lot in lots}
    engine.prime(material_lots)
    # An unpriced material is estimated from same-name lots (last known price): prime those too,
    # so a material with a long purchase history doesn't cost one round of queries per lot.
    index = engine._material_index()
    names = {normalise(engine._get_lot(lot).name) for lot in material_lots if engine._get_lot(lot) is not None}
    names |= {norm for declared_names in declared.values() for norm in declared_names}
    engine.prime({lot.id for norm in names for lot in index.get(norm, [])})
    # The latest batches' produced lots, loaded together (with their graphs) for the list's cost
    # per unit: each product reads its own output lot's cost, so no batch is loaded on its own.
    batch_ids = [eid for eid in latest.values() if eid is not None]
    produced_by_batch: dict = defaultdict(list)
    if batch_ids:
        from app.features.costing.models import CostFlow

        produced = (
            db.query(CostFlow.execution_id, CostFlow.inventory_item_id)
            .filter(
                CostFlow.org_id == org_id,
                CostFlow.execution_id.in_(batch_ids),
                CostFlow.direction == "in",
                CostFlow.kind.in_(("produced", "reconciled_in")),
            )
            .all()
        )
        for execution_id, item_id in produced:
            produced_by_batch[execution_id].append(item_id)
        engine.prime({item_id for _eid, item_id in produced})
    lot_rows_cache: dict = {}
    out = {}
    for key, product in products.items():
        execution_id = latest.get(key)
        if execution_id is not None:
            basis, materials = "latest_batch", _lot_rows(lots_by_key[key], engine, lot_rows_cache)
        elif key in declared:
            basis, materials = "declared_inputs", _declared_rows(declared[key], engine)
        else:
            basis, materials = "declared_inputs", []
        ready = bool(materials) and all(m["costed"] for m in materials)
        out[key] = {
            "key": key,
            "name": product["name"],
            "basis": basis,
            "execution_id": str(execution_id) if execution_id else None,
            "ready": ready,
            "materials": materials,
            **(
                _latest_unit_cost(engine, produced_by_batch.get(execution_id, []), key)
                if ready and execution_id
                else {}
            ),
        }
    return out


def _latest_unit_cost(engine: CostEngine, produced_lot_ids, key: str) -> dict:
    """What one unit of the product cost in its latest batch (polish: answer it on the list).
    Matched by the output the product is (its stable id), never by name: a renamed output or a
    co-product must not lend its cost to this one."""
    if not key.startswith("output:"):
        return {}
    output_id = key.split(":", 1)[1]
    for item_id in produced_lot_ids:
        lot = engine._get_lot(item_id)
        if lot is None or str(lot.source_output_id) != output_id:
            continue
        try:
            cost = engine._solve(("lot", item_id))
        except TooLargeError:
            return {}
        if cost.status in (ACTUAL, ESTIMATED) and cost.unit_known is not None:
            return {"unit_cost": unit_str(cost.unit_known), "unit": lot.unit}
        return {}
    return {}


def product_detail(db: Session, org_id: UUID, key: str) -> dict:
    found = _details(db, org_id, keys=[key]).get(key)
    if found is None:
        raise CostingNotFoundError("Product not found")
    return found


def list_products(db: Session, org_id: UUID) -> list[dict]:
    out = [
        {
            "key": key,
            "name": detail["name"],
            "ready": detail["ready"],
            "materials_total": len(detail["materials"]),
            "materials_costed": sum(1 for m in detail["materials"] if m["costed"]),
            "unit_cost": detail.get("unit_cost"),
            "unit": detail.get("unit"),
        }
        for key, detail in _details(db, org_id).items()
    ]
    return sorted(out, key=lambda p: (p["name"].casefold(), p["key"]))
