"""
DAG Traversal for inventory traceability.

Single unified traversal engine: tracer.traverse(start_nodes, direction, stop_conditions, filters).
Returns TraversalResult objects; interpretation and presentation live on the result, not in API code.
Used by /api/core/inventory/trace, /api/core/inventory/trace-backward, /api/core/inventory/check-needed,
and future use cases (site map, compliance, recall simulation).

Connections are built by execution flow (execution_id on each connection).
from_id and to_id are always inventory item UUIDs (never execution_id).
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.db.models.execution import Execution
from app.core.db.models.execution_step import ExecutionStep
from app.core.db.models.inventory_item import InventoryItem
from app.core.db.models.process import Process

try:
    from dateutil import parser as dateutil_parser
except ImportError:
    dateutil_parser = None  # type: ignore[assignment]

# Internal fields to exclude from execution_prompts
_EXECUTION_PROMPTS_INTERNAL = {"completed_by_email", "completed_by_user_id", "completed_at"}


def _normalize_date(val: Any) -> date | None:
    """Convert a value to a date for comparison. Handles datetime, date, ISO string; uses dateutil if available."""
    if val is None:
        return None
    if hasattr(val, "date") and callable(getattr(val, "date")):
        return val.date()
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    if isinstance(val, str):
        try:
            parsed = datetime.fromisoformat(val.replace("Z", "+00:00"))
            return parsed.date()
        except (ValueError, TypeError):
            pass
        if dateutil_parser is not None:
            try:
                parsed = dateutil_parser.parse(val)
                return parsed.date() if hasattr(parsed, "date") else parsed
            except (ValueError, TypeError):
                pass
    return None


# ---------------------------------------------------------------------------
# Traversal result and metadata
# ---------------------------------------------------------------------------


@dataclass
class TraversalMetadata:
    """Metadata about a traversal run (nodes visited, edge count, filtered, etc.)."""

    nodes_visited: int = 0
    edges_count: int = 0
    nodes_filtered_out: int = 0
    edges_removed_by_filter: int = 0


@dataclass
class TraversalResult:
    """
    Result of a DAG traversal. Holds nodes and edges; interpretation and presentation
    live here, not in API or services.
    """

    root_nodes: set[UUID]
    direction: Literal["forward", "backward"]
    nodes: list[dict[str, Any]]  # Enriched item dicts
    edges: list[dict[str, str]]  # {"from_id", "to_id", "execution_id"}
    metadata: TraversalMetadata = field(default_factory=TraversalMetadata)
    # Optional: ORM items used to build nodes (avoids re-query in find_impacted_by_expired_raw)
    items_orm: list[InventoryItem] | None = None

    def as_items_and_connections(self) -> dict[str, Any]:
        """Raw items and connections for APIs that need the same shape as before."""
        return {"items": self.nodes, "connections": self.edges}

    def as_trace_forward_response(
        self,
        raw_material_id: UUID,
        raw_material_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Shape expected by /api/core/inventory/trace: raw_material, intermediates, finals, all_items, connections.
        Adds display-only edges (raw->item by execution_id) for UI; all edges remain valid (from_id/to_id are
        inventory item IDs). Step-order (visual) edges: use DAGTracer.add_step_order_connections if needed.
        """
        items = list(self.nodes)
        connections = list(self.edges)
        raw_id_str = str(raw_material_id)
        item_ids = {item["id"] for item in items} | {raw_id_str}
        connections = [c for c in connections if c.get("from_id") in item_ids and c.get("to_id") in item_ids]
        conn_pairs = {(c["from_id"], c["to_id"]) for c in connections}
        for item in items:
            if item["id"] == raw_id_str:
                continue
            eid = item.get("source_execution_id")
            if eid and (raw_id_str, item["id"]) not in conn_pairs:
                connections.append({"from_id": raw_id_str, "to_id": item["id"], "execution_id": eid})
                conn_pairs.add((raw_id_str, item["id"]))
        if not any(item["id"] == raw_id_str for item in items):
            items.insert(0, raw_material_data)
        intermediates = [i for i in items if i.get("inventory_type") == "work_in_progress"]
        finals = [i for i in items if i.get("inventory_type") == "final_product"]
        return {
            "raw_material": raw_material_data,
            "intermediates": intermediates,
            "finals": finals,
            "all_items": items,
            "connections": connections,
        }

    def as_trace_backward_response(
        self,
        traced_item_id: UUID,
        traced_item_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Shape expected by /api/core/inventory/trace-backward. Adds display-only edges (source->traced by
        execution_id) for UI; connections remain valid (inventory item IDs). Step-order: DAGTracer.add_step_order_connections."""
        items = list(self.nodes)
        connections = list(self.edges)
        traced_id_str = str(traced_item_id)
        exec_id_str = traced_item_data.get("source_execution_id")
        if exec_id_str:
            existing_to_traced = {c["from_id"] for c in connections if c.get("to_id") == traced_id_str}
            for item in items:
                if item["id"] == traced_id_str:
                    continue
                if item["id"] not in existing_to_traced:
                    connections.append({"from_id": item["id"], "to_id": traced_id_str, "execution_id": exec_id_str})
                    existing_to_traced.add(item["id"])
        return {"items": items, "connections": connections, "traced_item_data": traced_item_data}

    def impacted_inventory_items(self) -> list[dict[str, Any]]:
        """All inventory item dicts in this result (alias for nodes)."""
        return self.nodes

    def as_recall_view(self) -> dict[str, Any]:
        """Minimal view for recall/simulation: items and edges only."""
        return {"items": self.nodes, "connections": self.edges}


# ---------------------------------------------------------------------------
# Stop conditions (composable; passed into traverse)
# ---------------------------------------------------------------------------

StopCondition = Callable[[UUID, dict[str, Any]], bool]
# Stop conditions: when a condition returns True for a node, that node is still included in the result;
# we do not traverse beyond it (no further edges from that node). To exclude the node entirely, use filters.


def stop_at_inventory_types(*inventory_types: str) -> StopCondition:
    """Stop traversal when node has one of the given inventory_type values. The node itself is still
    included in the result; we only stop following edges from that node."""

    def _stop(node_id: UUID, context: dict[str, Any]) -> bool:
        item = context.get("item")
        if not item:
            return False
        itype = getattr(item, "inventory_type", None) or (
            item.get("inventory_type") if isinstance(item, dict) else None
        )
        return itype in inventory_types

    return _stop


# ---------------------------------------------------------------------------
# DAGTracer: single traversal engine
# ---------------------------------------------------------------------------


class DAGTracer:
    """
    Single DAG tracer. One traversal engine: traverse(start_nodes, direction, stop_conditions, filters).
    Direction-agnostic, multi-root, no hard depth limit. Bulk-loads data once; recursion is in-memory.
    """

    def __init__(self, org_id: UUID, session: Session):
        self.org_id = org_id
        self.session = session
        self._log = logging.getLogger(__name__)
        self._enrichment_cache: dict[UUID, dict[str, Any]] = {}

    def traverse(
        self,
        start_nodes: list[UUID],
        direction: Literal["forward", "backward"],
        stop_conditions: list[StopCondition] | None = None,
        filters: list[Callable[[dict], bool]] | None = None,
        include_quantity_filter: bool = True,
        root_set: set[UUID] | None = None,
        traversal_order: Literal["dfs", "bfs"] = "dfs",
        clear_enrichment_cache: bool = True,
    ) -> TraversalResult:
        """
        Single entry point for DAG traversal. Bulk-loads steps and items once;
        runs in-memory forward or backward from start_nodes. No hard depth limit;
        termination is by graph structure and optional stop_conditions.

        Args:
            start_nodes: Starting inventory item UUIDs (multi-root supported).
            direction: "forward" (to downstream) or "backward" (to upstream).
            stop_conditions: Optional list of callables (node_id, context) -> bool. When True for a node, that node
            is still included in the result; we do not traverse beyond it (no further edges from that node).
        filters: Optional list of callables (item_dict) -> bool; applied when building final node list.
        include_quantity_filter: If True, exclude items with quantity <= 0 except those in root_set. Filtering
            removes nodes and any edges whose endpoints are not both in the final set (see edge filtering below).
        root_set: Items always included even if quantity 0. Defaults to set(start_nodes).
        traversal_order: "dfs" (depth-first, stack) or "bfs" (breadth-first, queue). BFS can be useful when
            level-order or distance-from-root matters for UI or simulation.
        clear_enrichment_cache: If True (default), clear the per-request enrichment cache before traversal.
            Set False when performing repeated traversals with the same tracer to reuse cached enrichment.

        Returns:
            TraversalResult with root_nodes, direction, nodes, edges, metadata.
        """
        stop_conditions = stop_conditions or []
        filters = filters or []
        root_set = root_set or set(start_nodes)
        if clear_enrichment_cache:
            self._enrichment_cache.clear()

        # Resolve start nodes in one query
        start_set = set(start_nodes)
        start_items = (
            self.session.query(InventoryItem)
            .filter(InventoryItem.id.in_(start_set), InventoryItem.org_id == self.org_id)
            .all()
        )
        node_ids: set[UUID] = {i.id for i in start_items}
        if not node_ids:
            return TraversalResult(
                root_nodes=set(start_nodes),
                direction=direction,
                nodes=[],
                edges=[],
                metadata=TraversalMetadata(),
            )

        # Bulk-load all execution steps for org (and items produced by them for forward)
        steps = (
            self.session.query(ExecutionStep)
            .join(Execution, ExecutionStep.execution_id == Execution.id)
            .filter(Execution.org_id == self.org_id)
            .all()
        )
        steps_by_id = {s.id: s for s in steps}
        steps_by_input_item_id: dict[UUID, list[ExecutionStep]] = {}
        for step in steps:
            if not step.actual_inputs:
                continue
            for inp in step.actual_inputs:
                inp_id = inp.get("inventory_item_id")
                if inp_id is not None:
                    try:
                        uid = UUID(str(inp_id))
                        steps_by_input_item_id.setdefault(uid, []).append(step)
                    except (ValueError, TypeError):
                        pass

        # Items produced by these steps (for forward: step -> output item)
        step_ids = {s.id for s in steps}
        produced_items = (
            self.session.query(InventoryItem)
            .filter(
                InventoryItem.source_execution_step_id.in_(step_ids),
                InventoryItem.org_id == self.org_id,
            )
            .all()
        )
        items_by_source_step_id: dict[UUID, list[InventoryItem]] = {}
        for inv in produced_items:
            if inv.source_execution_step_id:
                items_by_source_step_id.setdefault(inv.source_execution_step_id, []).append(inv)

        # For backward: bulk-load all potentially reachable items (inputs/outputs of steps, start nodes)
        input_item_ids = set(steps_by_input_item_id.keys())
        output_item_ids = {i.id for i in produced_items}
        all_backward_ids = node_ids | output_item_ids | input_item_ids
        items_by_id: dict[UUID, Any] = {}
        if direction == "backward" and all_backward_ids:
            items_backward = (
                self.session.query(InventoryItem)
                .filter(InventoryItem.id.in_(all_backward_ids), InventoryItem.org_id == self.org_id)
                .all()
            )
            items_by_id = {i.id: i for i in items_backward}

        start_items_by_id = {i.id: i for i in start_items}

        visited_node_ids: set[UUID] = set()
        visited_step_ids: set[UUID] = set()
        collected_edges: list[dict[str, str]] = []
        collected_node_ids: set[UUID] = set()

        def context_for(node_id: UUID) -> dict[str, Any]:
            return {"node_id": node_id, "item": item_orm_by_id.get(node_id)}

        item_orm_by_id: dict[UUID, Any] = {}

        # Iterative traversal (deque: DFS=pop, BFS=popleft) to avoid recursion limits on large DAGs
        use_bfs = traversal_order == "bfs"
        if direction == "forward":
            for nid in node_ids:
                item_orm_by_id[nid] = start_items_by_id.get(nid)
            worklist: deque[UUID] = deque(node_ids)
            while worklist:
                nid = worklist.popleft() if use_bfs else worklist.pop()
                if nid in visited_node_ids:
                    continue
                visited_node_ids.add(nid)
                collected_node_ids.add(nid)
                for step in steps_by_input_item_id.get(nid, []):
                    if step.id in visited_step_ids:
                        continue
                    visited_step_ids.add(step.id)
                    for out_item in items_by_source_step_id.get(step.id, []):
                        child_id = out_item.id
                        item_orm_by_id[child_id] = out_item
                        collected_edges.append(
                            {
                                "from_id": str(nid),
                                "to_id": str(child_id),
                                "execution_id": str(step.execution_id) if step.execution_id else "",
                            }
                        )
                        collected_node_ids.add(child_id)
                        ctx = context_for(child_id)
                        if any(stop(child_id, ctx) for stop in stop_conditions):
                            continue
                        worklist.append(child_id)
        else:
            for nid in node_ids:
                item_orm_by_id[nid] = items_by_id.get(nid)
            worklist = deque(node_ids)
            while worklist:
                nid = worklist.popleft() if use_bfs else worklist.pop()
                if nid in visited_node_ids:
                    continue
                visited_node_ids.add(nid)
                collected_node_ids.add(nid)
                item = items_by_id.get(nid)
                if item:
                    item_orm_by_id[nid] = item
                if not item or not item.source_execution_step_id:
                    continue
                step = steps_by_id.get(item.source_execution_step_id)
                if not step or not step.actual_inputs:
                    continue
                exec_id_str = str(step.execution_id) if step.execution_id else ""
                for inp in step.actual_inputs:
                    inp_id = inp.get("inventory_item_id")
                    if not inp_id:
                        continue
                    try:
                        uid = UUID(str(inp_id))
                    except (ValueError, TypeError):
                        continue
                    parent_item = items_by_id.get(uid)
                    if not parent_item:
                        continue
                    item_orm_by_id[uid] = parent_item
                    collected_edges.append({"from_id": str(uid), "to_id": str(nid), "execution_id": exec_id_str})
                    collected_node_ids.add(uid)
                    ctx = {"node_id": uid, "item": parent_item}
                    if any(stop(uid, ctx) for stop in stop_conditions):
                        continue
                    worklist.append(uid)

        # Load all collected items and enrich
        all_ids = collected_node_ids
        items_orm = (
            self.session.query(InventoryItem)
            .filter(InventoryItem.id.in_(all_ids), InventoryItem.org_id == self.org_id)
            .all()
        )
        enriched = self._enrich_items_bulk(items_orm)
        node_dicts = []
        nodes_filtered_out = 0
        for i in enriched:
            uid = i["id"] if isinstance(i["id"], UUID) else UUID(i["id"])
            if include_quantity_filter:
                try:
                    qty_str = str(i.get("quantity") or "0").strip()
                    q = Decimal(qty_str)
                    if q <= 0 and uid not in root_set:
                        nodes_filtered_out += 1
                        continue
                except (InvalidOperation, ValueError, TypeError) as e:
                    self._log.warning(
                        "Quantity conversion failed for item %s (quantity=%r): %s",
                        i.get("id"),
                        i.get("quantity"),
                        e,
                    )
                    nodes_filtered_out += 1
                    continue
            if filters and not all(f(i) for f in filters):
                nodes_filtered_out += 1
                continue
            node_dicts.append(i)

        # Keep only edges whose endpoints are in the final returned node set. When nodes are filtered out
        # (e.g. quantity <= 0 or custom filters), edges touching those nodes are removed so the result
        # graph is consistent (no dangling edges). Stakeholders should be aware that quantity filtering
        # can remove both nodes and edges.
        node_id_strs = {item["id"] for item in node_dicts}
        edges_before = len(collected_edges)
        edges_final = [
            c for c in collected_edges if c.get("from_id") in node_id_strs and c.get("to_id") in node_id_strs
        ]
        edges_removed = edges_before - len(edges_final)
        if edges_removed > 0:
            self._log.warning(
                "Traversal removed %s edge(s) because endpoint(s) were filtered out (e.g. quantity filter); "
                "ensure graph remains consistent.",
                edges_removed,
            )

        meta = TraversalMetadata(
            nodes_visited=len(collected_node_ids),
            edges_count=len(edges_final),
            nodes_filtered_out=nodes_filtered_out,
            edges_removed_by_filter=edges_removed,
        )
        self._log.info(
            "Traversal complete: direction=%s, nodes_visited=%s, nodes_returned=%s, nodes_filtered_out=%s, "
            "edges=%s, edges_removed=%s, start_nodes=%s",
            direction,
            len(collected_node_ids),
            len(node_dicts),
            nodes_filtered_out,
            len(edges_final),
            edges_removed,
            [str(n) for n in start_nodes],
            extra={
                "direction": direction,
                "nodes_visited": len(collected_node_ids),
                "nodes_returned": len(node_dicts),
                "nodes_filtered_out": nodes_filtered_out,
                "edges_count": len(edges_final),
                "edges_removed": edges_removed,
                "start_nodes": [str(n) for n in start_nodes],
            },
        )

        return TraversalResult(
            root_nodes=set(start_nodes),
            direction=direction,
            nodes=node_dicts,
            edges=edges_final,
            metadata=meta,
            items_orm=items_orm,
        )

    def find_impacted_by_expired_raw(self, raw_material: Any) -> dict[str, Any]:
        """
        Items that trace forward from an expired raw and were made after it expired.
        Uses traverse(forward) then filters by production_date > expiry_date.
        """
        expiry_date = _normalize_date(raw_material.expiry_date)
        if not expiry_date:
            return {"impacted_items": [], "connections": []}

        result = self.traverse(
            start_nodes=[raw_material.id],
            direction="forward",
            include_quantity_filter=True,
            root_set={raw_material.id},
        )
        trace_items = [i for i in result.nodes if i["id"] != str(raw_material.id)]
        trace_connections = [c for c in result.edges if c.get("from_id") == str(raw_material.id)]

        # Use step IDs from result nodes (no item re-query); one bulk step query
        step_ids_orm = set()
        for i in trace_items:
            sid = i.get("source_execution_step_id")
            if sid:
                try:
                    step_ids_orm.add(UUID(str(sid)))
                except (ValueError, TypeError):
                    pass
        steps = (
            self.session.query(ExecutionStep).filter(ExecutionStep.id.in_(step_ids_orm)).all() if step_ids_orm else []
        )
        step_by_id = {str(s.id): s for s in steps}

        impacted_items: list[dict[str, Any]] = []
        connections_out: list[dict[str, str]] = []
        raw_id_str = str(raw_material.id)

        for item in trace_items:
            item_id = item.get("id")
            if not item_id:
                continue
            step_id_str = item.get("source_execution_step_id")
            if not step_id_str:
                continue
            step = step_by_id.get(str(step_id_str))
            if not step:
                continue
            step_used_this_raw = False
            for inp in step.actual_inputs or []:
                inp_id = inp.get("inventory_item_id")
                if inp_id is not None and str(inp_id) == raw_id_str:
                    step_used_this_raw = True
                    break
            if not step_used_this_raw:
                continue
            production_date = _normalize_date(step.completed_at) if step.completed_at else None
            if not production_date or production_date <= expiry_date:
                continue
            completed_at_iso = step.completed_at.isoformat() if step.completed_at else None
            execution_id_str = str(step.execution_id) if step.execution_id else None
            impacted_items.append(
                {
                    **{
                        k: v
                        for k, v in item.items()
                        if k not in ("expired_raw_material_id", "expired_raw_material_name", "made_after_raw_expired")
                    },
                    "expired_raw_material_id": raw_id_str,
                    "expired_raw_material_name": raw_material.name,
                    "made_after_raw_expired": True,
                    "completed_at": completed_at_iso,
                    "execution_id": execution_id_str,
                }
            )
            conn = next((c for c in trace_connections if c.get("to_id") == item_id), {})
            eid = conn.get("execution_id") or item.get("source_execution_id") or execution_id_str
            connections_out.append(
                {
                    "from_id": raw_id_str,
                    "to_id": item_id,
                    "execution_id": str(eid) if eid else "",
                }
            )

        return {"impacted_items": impacted_items, "connections": connections_out}

    def _enrich_items_bulk(self, items: list[InventoryItem]) -> list[dict[str, Any]]:
        """Enrich ORM items with extra_data and process_name; uses per-request cache. For very large
        DAGs, generator-based enrichment could be considered for memory efficiency."""
        if not items:
            return []
        step_ids = {i.source_execution_step_id for i in items if i.source_execution_step_id}
        exec_ids = {i.source_execution_id for i in items if i.source_execution_id}
        steps = self.session.query(ExecutionStep).filter(ExecutionStep.id.in_(step_ids)).all() if step_ids else []
        steps_by_id = {s.id: s for s in steps}
        executions = self.session.query(Execution).filter(Execution.id.in_(exec_ids)).all() if exec_ids else []
        exec_by_id = {e.id: e for e in executions}
        process_ids = {e.process_id for e in executions if e.process_id}
        processes = self.session.query(Process).filter(Process.id.in_(process_ids)).all() if process_ids else []
        process_by_id = {p.id: p for p in processes}

        result = []
        for item in items:
            if item.id in self._enrichment_cache:
                result.append(self._enrichment_cache[item.id])
                continue
            extra = dict(item.extra_data) if item.extra_data else {}
            step = steps_by_id.get(item.source_execution_step_id) if item.source_execution_step_id else None
            if step and not extra.get("execution_prompts") and step.execution_data:
                prompts = {
                    k: v
                    for k, v in step.execution_data.items()
                    if k not in _EXECUTION_PROMPTS_INTERNAL and v is not None and v != ""
                }
                if prompts:
                    extra["execution_prompts"] = prompts
                if not extra.get("variable_inputs") and step.actual_inputs:
                    extra["variable_inputs"] = step.actual_inputs
                if not extra.get("variable_output") and step.actual_outputs and item.name:
                    match = next((o for o in step.actual_outputs if o.get("name") == item.name), None)
                    if match:
                        extra["variable_output"] = match
            process_name = None
            if item.source_execution_id:
                ex = exec_by_id.get(item.source_execution_id)
                if ex and ex.process_id:
                    proc = process_by_id.get(ex.process_id)
                    if proc:
                        process_name = proc.name
            d = self._item_to_dict(item, extra, process_name)
            self._enrichment_cache[item.id] = d
            result.append(d)
        return result

    @staticmethod
    def _item_to_dict(
        item: InventoryItem,
        extra_data: dict[str, Any],
        process_name: str | None = None,
    ) -> dict[str, Any]:
        return {
            "id": str(item.id),
            "name": item.name,
            "quantity": item.quantity,
            "unit": item.unit,
            "inventory_type": item.inventory_type,
            "supplier": item.supplier,
            "purchase_date": item.purchase_date.isoformat() if item.purchase_date else None,
            "supplier_batch_number": item.supplier_batch_number,
            "expiry_date": item.expiry_date.isoformat() if item.expiry_date else None,
            "source_execution_id": str(item.source_execution_id) if item.source_execution_id else None,
            "source_execution_step_id": str(item.source_execution_step_id) if item.source_execution_step_id else None,
            "source_step_name": item.source_step_name,
            "process_name": process_name,
            "created_at": item.created_at.isoformat() if item.created_at else None,
            "extra_data": extra_data,
        }

    def add_step_order_connections(
        self,
        item_dicts: list[dict],
        connections: list[dict[str, str]],
    ) -> None:
        """Add same-execution step-order edges for visualization. Bulk-loads steps once."""
        from app.core.db.models.inventory_item import InventoryType

        non_raw = [d for d in item_dicts if d.get("inventory_type") != InventoryType.RAW_MATERIAL.value]
        by_exec: dict[str, list[dict]] = {}
        for d in non_raw:
            eid = d.get("source_execution_id")
            if eid:
                by_exec.setdefault(eid, []).append(d)
        conn_set = {(c["from_id"], c["to_id"]) for c in connections}
        step_ids = set()
        for d in non_raw:
            sid = d.get("source_execution_step_id")
            if sid:
                try:
                    step_ids.add(UUID(sid))
                except (ValueError, TypeError):
                    pass
        steps = self.session.query(ExecutionStep).filter(ExecutionStep.id.in_(step_ids)).all() if step_ids else []
        step_by_id = {str(s.id): s for s in steps}

        for eid, exec_items in by_exec.items():
            if len(exec_items) < 2:
                continue
            step_info = []
            seen_step_numbers: set[int] = set()
            for d in exec_items:
                sid = d.get("source_execution_step_id")
                if not sid:
                    self._log.debug(
                        "add_step_order_connections: item %s has no source_execution_step_id (exec=%s)",
                        d.get("id"),
                        eid,
                    )
                    continue
                step = step_by_id.get(sid)
                if not step:
                    self._log.warning(
                        "add_step_order_connections: step %s not found for item %s (exec=%s)",
                        sid,
                        d.get("id"),
                        eid,
                    )
                    continue
                if step.step_number in seen_step_numbers:
                    self._log.warning(
                        "add_step_order_connections: duplicate step_number=%s in exec %s (step_id=%s)",
                        step.step_number,
                        eid,
                        sid,
                    )
                seen_step_numbers.add(step.step_number)
                step_info.append({"item": d, "step": step, "step_number": step.step_number})
            step_info.sort(key=lambda x: x["step_number"])
            for i, later in enumerate(step_info):
                later_step = later["step"]
                later_item = later["item"]
                if not later_step.actual_inputs:
                    continue
                for earlier in step_info[:i]:
                    earlier_item = earlier["item"]
                    try:
                        earlier_id_uuid = UUID(str(earlier_item.get("id") or ""))
                    except (ValueError, TypeError):
                        continue
                    used_earlier = False
                    for inp in later_step.actual_inputs or []:
                        inp_id = inp.get("inventory_item_id")
                        if inp_id is None:
                            continue
                        try:
                            if UUID(str(inp_id)) == earlier_id_uuid:
                                used_earlier = True
                                break
                        except (ValueError, TypeError):
                            continue
                    if used_earlier and (earlier_item["id"], later_item["id"]) not in conn_set:
                        connections.append(
                            {
                                "from_id": earlier_item["id"],
                                "to_id": later_item["id"],
                                "execution_id": eid,
                            }
                        )
                        conn_set.add((earlier_item["id"], later_item["id"]))


# ---------------------------------------------------------------------------
# Module-level API: thin wrappers that use traverse() and TraversalResult
# ---------------------------------------------------------------------------


def trace_forward(
    org_id: UUID,
    session: Session,
    item_id: UUID,
    include_quantity_filter: bool = True,
    root_item_id: UUID | None = None,
) -> dict[str, Any]:
    """Trace forward from an inventory item. Uses single traversal engine; returns legacy dict shape."""
    tracer = DAGTracer(org_id=org_id, session=session)
    result = tracer.traverse(
        start_nodes=[item_id],
        direction="forward",
        include_quantity_filter=include_quantity_filter,
        root_set={root_item_id if root_item_id is not None else item_id},
    )
    items = result.nodes
    connections = result.edges
    tracer.add_step_order_connections(items, connections)
    return {"items": items, "connections": connections}


def trace_backward(
    org_id: UUID,
    session: Session,
    item_id: UUID,
    include_quantity_filter: bool = True,
    traced_item_id: UUID | None = None,
) -> dict[str, Any]:
    """Trace backward from an inventory item. Uses single traversal engine; returns legacy dict shape."""
    tracer = DAGTracer(org_id=org_id, session=session)
    result = tracer.traverse(
        start_nodes=[item_id],
        direction="backward",
        include_quantity_filter=include_quantity_filter,
        root_set={traced_item_id if traced_item_id is not None else item_id},
    )
    return {"items": result.nodes, "connections": result.edges}


def find_impacted_by_expired_raw(org_id: UUID, session: Session, raw_material: Any) -> dict[str, Any]:
    """Find items made with an expired raw material (production after expiry)."""
    tracer = DAGTracer(org_id=org_id, session=session)
    return tracer.find_impacted_by_expired_raw(raw_material)


def validate_item_uuid(value: Any) -> tuple[UUID | None, str | None]:
    """Validate and parse an inventory item UUID. Returns (uuid, None) if valid; (None, error_message) if invalid."""
    if value is None:
        return None, "Invalid ID: null"
    try:
        uid = UUID(str(value))
        return uid, None
    except (ValueError, TypeError) as e:
        return None, f"Invalid ID: {e}"
