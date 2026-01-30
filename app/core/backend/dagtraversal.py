"""
DAG Traversal for inventory traceability.

Centralizes forward/backward DAG traversal, connection mapping, and extra_data
enrichment for raw materials, intermediates, and final products. Used by
/api/core/inventory/trace, /api/core/inventory/trace-backward, and optionally
/api/core/inventory/check-needed.

All traversal uses execution_id as the primary link: connections are built by
execution flow (steps within an execution, execution_id on each connection).
Connection from_id and to_id are always inventory item UUIDs (never execution_id).
"""

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.core.db.models.execution import Execution
from app.core.db.models.execution_step import ExecutionStep
from app.core.db.models.inventory_item import InventoryItem
from app.core.db.models.process import Process

# Configurable depth limit to prevent runaway recursion and allow logging
MAX_DAG_DEPTH = 50

# Internal fields to exclude from execution_prompts
_EXECUTION_PROMPTS_INTERNAL = {"completed_by_email", "completed_by_user_id", "completed_at"}


def _normalize_date(val: Any) -> date | None:
    """Convert a value to a date for comparison. Handles datetime (uses .date()), date, or ISO string."""
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
            return None
    return None


class DAGTracer:
    """
    Reusable DAG tracer for inventory traceability.

    Traverses the graph of inventory items and execution steps (forward from a raw
    material to connected products, or backward from an item to source materials).
    Builds direct connections (from_id → to_id, with execution_id as the primary
    link). from_id and to_id are always inventory item UUIDs; execution_id is
    metadata for the flow. Enriches items with execution_prompts, variable_inputs,
    variable_output, and process_name.

    Usage:
        tracer = DAGTracer(org_id=uuid, session=db_session)
        result = tracer.trace_forward(item_id, include_quantity_filter=True)
        # result["items"]: list of item dicts; result["connections"]: list of {from_id, to_id, execution_id}
    """

    def __init__(self, org_id: UUID, session: Any):
        """
        Args:
            org_id: Organisation UUID; all queries are filtered by org_id.
            session: SQLAlchemy session (e.g. from app.core.db.db_session).
        """
        self.org_id = org_id
        self.session = session
        self._log = logging.getLogger(__name__)

    def trace_forward(
        self,
        item_id: UUID,
        include_quantity_filter: bool = True,
        root_item_id: UUID | None = None,
        log_deep_traversal: bool = True,
    ) -> dict[str, Any]:
        """
        Traverse forward from an inventory item to all connected items (intermediates and finals).

        Args:
            item_id: Starting inventory item UUID (e.g. raw material).
            include_quantity_filter: If True, exclude items with quantity <= 0 except the root item.
            root_item_id: If set, treated as the root (always included even if quantity 0). Defaults to item_id.
            log_deep_traversal: If True, log a warning when depth limit is reached.

        Returns:
            {
                "items": [{"id", "name", "quantity", "unit", "inventory_type", ... "extra_data", "process_name"}, ...],
                "connections": [{"from_id": str, "to_id": str, "execution_id": str}, ...]
            }
            Items and connections are restricted to the same org. Cycles are avoided via visited step IDs.
        """
        root = root_item_id if root_item_id is not None else item_id
        try:
            item = (
                self.session.query(InventoryItem)
                .filter(InventoryItem.id == item_id, InventoryItem.org_id == self.org_id)
                .first()
            )
        except Exception:
            return {"items": [], "connections": []}
        if not item:
            return {"items": [], "connections": []}

        visited_step_ids: set[UUID] = set()
        connections: list[dict[str, str]] = []
        connected_ids: set[UUID] = set()

        def _forward(node_id: UUID, depth: int) -> None:
            if depth > MAX_DAG_DEPTH:
                if log_deep_traversal:
                    self._log.warning(
                        "DAG forward traversal depth limit (%s) reached for item %s",
                        MAX_DAG_DEPTH,
                        node_id,
                    )
                return
            # Steps that use this item as input (bulk by loading org steps and filtering)
            steps = (
                self.session.query(ExecutionStep)
                .join(Execution, ExecutionStep.execution_id == Execution.id)
                .filter(Execution.org_id == self.org_id)
                .all()
            )
            steps_using = []
            for step in steps:
                if step.id in visited_step_ids:
                    continue
                if not step.actual_inputs:
                    continue
                for inp in step.actual_inputs:
                    inp_id = inp.get("inventory_item_id")
                    if inp_id and str(inp_id) == str(node_id):
                        steps_using.append(step)
                        visited_step_ids.add(step.id)
                        break
                    if inp.get("name"):
                        try:
                            uid = UUID(str(node_id)) if isinstance(node_id, str) else node_id
                            inv = (
                                self.session.query(InventoryItem)
                                .filter(InventoryItem.id == uid, InventoryItem.org_id == self.org_id)
                                .first()
                            )
                            if inv and (inp.get("name") or "").lower() == (inv.name or "").lower():
                                steps_using.append(step)
                                visited_step_ids.add(step.id)
                                break
                        except Exception:
                            pass

            for step in steps_using:
                produced = (
                    self.session.query(InventoryItem)
                    .filter(
                        InventoryItem.source_execution_step_id == step.id,
                        InventoryItem.org_id == self.org_id,
                    )
                    .all()
                )
                for p in produced:
                    connected_ids.add(p.id)
                    connections.append(
                        {
                            "from_id": str(node_id),
                            "to_id": str(p.id),
                            "execution_id": str(step.execution_id) if step.execution_id else "",
                        }
                    )
                    _forward(p.id, depth + 1)

        _forward(item_id, 0)

        # Filter to items that trace back to root (only include downstream items that actually connect to this root)
        filtered_ids: set[UUID] = set()
        for cid in connected_ids:
            sources = self._trace_backward_ids_only(cid, set())
            if root in sources:
                filtered_ids.add(cid)
        connected_ids = filtered_ids
        # Keep only connections where both endpoints are root or in connected_ids
        kept = connected_ids | {item_id}
        connections = [c for c in connections if UUID(c["from_id"]) in kept and UUID(c["to_id"]) in kept]

        # Build item list: root + connected, with quantity filter and enrichment
        all_ids = connected_ids | {item_id}
        items_orm = (
            self.session.query(InventoryItem)
            .filter(InventoryItem.id.in_(all_ids), InventoryItem.org_id == self.org_id)
            .all()
        )
        items_by_id = {i.id: i for i in items_orm}
        enriched = self._enrich_items_bulk(list(items_by_id.values()))
        item_dicts = []
        for i in enriched:
            uid = i["id"] if isinstance(i["id"], UUID) else UUID(i["id"])
            if include_quantity_filter:
                try:
                    qty_str = str(i.get("quantity") or "0").strip()
                    q = Decimal(qty_str)
                    if q <= 0 and uid != root:
                        continue
                except Exception:
                    continue
            item_dicts.append(i)

        # Add inter-item connections within same execution (execution_id as primary link):
        # when multiple stages (intermediates/finals) share the same execution_id and
        # a later step used an earlier item as input, add (earlier, later) so the
        # visual can show additional columns for multi-stage chains.
        self._add_step_order_connections(item_dicts, connections)

        return {"items": item_dicts, "connections": connections}

    def _trace_backward_ids_only(
        self,
        item_id: UUID,
        visited_item_ids: set[str],
        depth: int = 0,
    ) -> set[UUID]:
        """Return set of all item IDs that can be reached by tracing backward from item_id (for filtering)."""
        if depth > MAX_DAG_DEPTH:
            return set()
        key = str(item_id)
        if key in visited_item_ids:
            return set()
        visited_item_ids.add(key)
        result = set()
        try:
            item = (
                self.session.query(InventoryItem)
                .filter(InventoryItem.id == item_id, InventoryItem.org_id == self.org_id)
                .first()
            )
        except Exception:
            return result
        if not item or not item.source_execution_step_id:
            return result
        step = self.session.query(ExecutionStep).filter(ExecutionStep.id == item.source_execution_step_id).first()
        if not step or not step.actual_inputs:
            return result
        for inp in step.actual_inputs:
            inp_id = inp.get("inventory_item_id")
            if not inp_id:
                continue
            try:
                uid = UUID(str(inp_id)) if isinstance(inp_id, str) else inp_id
            except ValueError:
                continue
            inv = (
                self.session.query(InventoryItem)
                .filter(InventoryItem.id == uid, InventoryItem.org_id == self.org_id)
                .first()
            )
            if inv:
                result.add(inv.id)
                result |= self._trace_backward_ids_only(inv.id, visited_item_ids, depth + 1)
        return result

    def trace_backward(
        self,
        item_id: UUID,
        include_quantity_filter: bool = True,
        traced_item_id: UUID | None = None,
        log_deep_traversal: bool = True,
    ) -> dict[str, Any]:
        """
        Traverse backward from an inventory item to all source items (raw materials and intermediates).

        Args:
            item_id: Starting inventory item UUID.
            include_quantity_filter: If True, exclude source items with quantity <= 0 except the traced item.
            traced_item_id: If set, this item is always included (e.g. the requested item). Defaults to item_id.
            log_deep_traversal: If True, log when depth limit is reached.

        Returns:
            {
                "items": [{"id", "name", "quantity", ... "extra_data", "process_name"}, ...],
                "connections": [{"from_id": str, "to_id": str, "execution_id": str}, ...]
            }
        """
        traced = traced_item_id if traced_item_id is not None else item_id
        try:
            item = (
                self.session.query(InventoryItem)
                .filter(InventoryItem.id == item_id, InventoryItem.org_id == self.org_id)
                .first()
            )
        except Exception:
            return {"items": [], "connections": []}
        if not item:
            return {"items": [], "connections": []}

        visited: set[str] = set()
        connections: list[dict[str, str]] = []
        source_ids: set[UUID] = set()

        def _backward(node_id: UUID, depth: int) -> None:
            if depth > MAX_DAG_DEPTH:
                if log_deep_traversal:
                    self._log.warning(
                        "DAG backward traversal depth limit (%s) reached for item %s",
                        MAX_DAG_DEPTH,
                        node_id,
                    )
                return
            key = str(node_id)
            if key in visited:
                return
            visited.add(key)
            try:
                node = (
                    self.session.query(InventoryItem)
                    .filter(InventoryItem.id == node_id, InventoryItem.org_id == self.org_id)
                    .first()
                )
            except Exception:
                return
            if not node or not node.source_execution_step_id:
                return
            step = self.session.query(ExecutionStep).filter(ExecutionStep.id == node.source_execution_step_id).first()
            if not step or not step.actual_inputs:
                return
            exec_id_str = str(step.execution_id) if step.execution_id else ""
            for inp in step.actual_inputs:
                inp_id = inp.get("inventory_item_id")
                if not inp_id:
                    continue
                try:
                    uid = UUID(str(inp_id)) if isinstance(inp_id, str) else inp_id
                except ValueError:
                    continue
                inv = (
                    self.session.query(InventoryItem)
                    .filter(InventoryItem.id == uid, InventoryItem.org_id == self.org_id)
                    .first()
                )
                if not inv:
                    continue
                source_ids.add(inv.id)
                connections.append({"from_id": str(inv.id), "to_id": str(node_id), "execution_id": exec_id_str})
                _backward(inv.id, depth + 1)

        _backward(item_id, 0)

        all_ids = source_ids | {item_id}
        items_orm = (
            self.session.query(InventoryItem)
            .filter(InventoryItem.id.in_(all_ids), InventoryItem.org_id == self.org_id)
            .all()
        )
        enriched = self._enrich_items_bulk(items_orm)
        item_dicts = []
        for i in enriched:
            uid = i["id"] if isinstance(i["id"], UUID) else UUID(i["id"])
            if include_quantity_filter:
                try:
                    qty_str = str(i.get("quantity") or "0").strip()
                    q = Decimal(qty_str)
                    if q <= 0 and uid != traced:
                        continue
                except Exception:
                    continue
            item_dicts.append(i)

        return {"items": item_dicts, "connections": connections}

    def find_impacted_by_expired_raw(self, raw_material: Any) -> dict[str, Any]:
        """Find items that trace forward from an expired raw material and were made after it expired.

        Used by /api/core/inventory/check-needed. Only returns items where the
        step that produced the item completed after the raw material's expiry_date
        (production_date > expiry_date). "Check needed" = made with expired raw.
        Uses ExecutionStep.completed_at (step execution time only).

        Args:
            raw_material: ORM InventoryItem (expired raw material with expiry_date set).

        Returns:
            {"impacted_items": [{"id", "name", ... "expired_raw_material_id", "expired_raw_material_name", "is_made_with_expired": True}, ...],
             "connections": [{"from_id", "to_id", "execution_id"}, ...]}
        """
        result = self.trace_forward(
            raw_material.id,
            include_quantity_filter=True,
            root_item_id=raw_material.id,
        )
        trace_items = [i for i in result["items"] if i["id"] != str(raw_material.id)]
        trace_connections = [c for c in result["connections"] if c.get("from_id") == str(raw_material.id)]

        expiry_date = _normalize_date(raw_material.expiry_date)
        if not expiry_date:
            return {"impacted_items": [], "connections": []}

        # Resolve production date from ExecutionStep.completed_at using ORM items (same as original code path).
        trace_item_ids = []
        for i in trace_items:
            try:
                trace_item_ids.append(UUID(i["id"]))
            except (ValueError, TypeError):
                continue
        items_orm = (
            self.session.query(InventoryItem)
            .filter(InventoryItem.id.in_(trace_item_ids), InventoryItem.org_id == self.org_id)
            .all()
            if trace_item_ids
            else []
        )
        item_orm_by_id = {str(it.id): it for it in items_orm}
        step_ids_orm = {it.source_execution_step_id for it in items_orm if it.source_execution_step_id}
        steps = (
            self.session.query(ExecutionStep).filter(ExecutionStep.id.in_(step_ids_orm)).all() if step_ids_orm else []
        )
        step_by_id = {str(s.id): s for s in steps}

        impacted_items: list[dict[str, Any]] = []
        connections_out: list[dict[str, str]] = []

        for item in trace_items:
            item_id = item.get("id")
            if not item_id:
                continue
            item_orm = item_orm_by_id.get(str(item_id))
            if not item_orm:
                continue
            if not item_orm.source_execution_step_id:
                continue
            step = step_by_id.get(str(item_orm.source_execution_step_id))
            if not step:
                continue
            # Only consider items whose producing step directly used this raw (not via an intermediate).
            raw_id_str = str(raw_material.id)
            step_used_this_raw = False
            for inp in step.actual_inputs or []:
                inp_id = inp.get("inventory_item_id")
                if inp_id is not None and str(inp_id) == raw_id_str:
                    step_used_this_raw = True
                    break
            if not step_used_this_raw:
                continue
            production_date = _normalize_date(step.completed_at) if step.completed_at else None
            if not production_date:
                continue
            # Include only when step completed AFTER raw expired (production_date > expiry_date).
            if production_date <= expiry_date:
                continue
            completed_at_iso = step.completed_at.isoformat() if step.completed_at else None
            impacted_items.append(
                {
                    **{
                        k: v
                        for k, v in item.items()
                        if k not in ("expired_raw_material_id", "expired_raw_material_name", "is_made_with_expired")
                    },
                    "expired_raw_material_id": str(raw_material.id),
                    "expired_raw_material_name": raw_material.name,
                    "is_made_with_expired": True,
                    "completed_at": completed_at_iso,
                }
            )
            item_id_str = str(item_id)
            conn = next(
                (c for c in trace_connections if c.get("to_id") == item_id_str),
                {"execution_id": item.get("source_execution_id")},
            )
            eid = conn.get("execution_id") or item.get("source_execution_id")
            connections_out.append(
                {
                    "from_id": str(raw_material.id),
                    "to_id": item_id_str,
                    "execution_id": str(eid) if eid else "",
                }
            )

        return {"impacted_items": impacted_items, "connections": connections_out}

    def _enrich_items_bulk(self, items: list[Any]) -> list[dict[str, Any]]:
        """Enrich a list of ORM items with extra_data (execution_prompts, variable_inputs, variable_output) and process_name."""
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
            result.append(self._item_to_dict(item, extra, process_name))
        return result

    @staticmethod
    def _item_to_dict(
        item: Any,
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

    def _add_step_order_connections(
        self,
        item_dicts: list[dict],
        connections: list[dict[str, str]],
    ) -> None:
        """Append connections between items in the same execution based on step order and actual_inputs."""
        from app.core.db.models.inventory_item import InventoryType

        non_raw = [d for d in item_dicts if d.get("inventory_type") != InventoryType.RAW_MATERIAL.value]
        by_exec: dict[str, list[dict]] = {}
        for d in non_raw:
            eid = d.get("source_execution_id")
            if eid:
                by_exec.setdefault(eid, []).append(d)
        conn_set = {(c["from_id"], c["to_id"]) for c in connections}
        for eid, items in by_exec.items():
            if len(items) < 2:
                continue
            step_info = []
            for d in items:
                sid = d.get("source_execution_step_id")
                if not sid:
                    continue
                try:
                    step = self.session.query(ExecutionStep).filter(ExecutionStep.id == UUID(sid)).first()
                except Exception:
                    continue
                if step:
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
                    # Only add connection when later step actually used this earlier item (strict UUID match)
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
# Module-level API: create tracer and delegate (for routes and extensibility)
# ---------------------------------------------------------------------------


def trace_forward(
    org_id: UUID,
    session: Any,
    item_id: UUID,
    include_quantity_filter: bool = True,
    root_item_id: UUID | None = None,
) -> dict[str, Any]:
    """Trace forward from an inventory item. Creates a DAGTracer and returns trace_forward result."""
    tracer = DAGTracer(org_id=org_id, session=session)
    return tracer.trace_forward(
        item_id,
        include_quantity_filter=include_quantity_filter,
        root_item_id=root_item_id,
    )


def trace_backward(
    org_id: UUID,
    session: Any,
    item_id: UUID,
    include_quantity_filter: bool = True,
    traced_item_id: UUID | None = None,
) -> dict[str, Any]:
    """Trace backward from an inventory item. Creates a DAGTracer and returns trace_backward result."""
    tracer = DAGTracer(org_id=org_id, session=session)
    return tracer.trace_backward(
        item_id,
        include_quantity_filter=include_quantity_filter,
        traced_item_id=traced_item_id,
    )


def find_impacted_by_expired_raw(org_id: UUID, session: Any, raw_material: Any) -> dict[str, Any]:
    """Find items made with an expired raw material (production after expiry). Creates a DAGTracer and returns result."""
    tracer = DAGTracer(org_id=org_id, session=session)
    return tracer.find_impacted_by_expired_raw(raw_material)


# ---------------------------------------------------------------------------
# DAGTracer API and response structure (for endpoint consistency)
# ---------------------------------------------------------------------------
#
# trace_forward(item_id, include_quantity_filter=True, root_item_id=None)
#   Returns: {"items": [...], "connections": [...]}
#   - items: list of item dicts with id (str), name, quantity, unit, inventory_type,
#     supplier, purchase_date, supplier_batch_number, expiry_date,
#     source_execution_id, source_execution_step_id, source_step_name, process_name,
#     created_at, extra_data (enriched with execution_prompts, variable_inputs, variable_output).
#   - connections: list of {"from_id": str, "to_id": str, "execution_id": str}.
#
# trace_backward(item_id, include_quantity_filter=True, traced_item_id=None)
#   Returns: same shape as trace_forward.
#
# Safety: invalid UUIDs, missing items, and cycles are handled; depth limit MAX_DAG_DEPTH
# applies; optional logging for deep/complex DAGs.
# ---------------------------------------------------------------------------


def validate_item_uuid(value: Any) -> tuple[UUID | None, str | None]:
    """
    Validate and parse an inventory item UUID from string or UUID.

    Returns:
        (uuid, None) if valid; (None, error_message) if invalid.
    """
    if value is None:
        return None, "Invalid ID: null"
    try:
        uid = UUID(str(value))
        return uid, None
    except (ValueError, TypeError) as e:
        return None, f"Invalid ID: {e}"
