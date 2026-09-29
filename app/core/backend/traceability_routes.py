"""Core traceability page and API routes. Register with register_routes(core_bp)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from flask import g, jsonify, render_template, request
from sqlalchemy.orm import joinedload

from app.core.db import db_session
from app.core.db.models.execution import Execution
from app.core.db.models.execution_step import ExecutionStep
from app.core.db.models.inventory_item import InventoryItem, InventoryType
from app.core.db.models.process import Process
from app.core.domain.execution_entry_timing import entry_timing
from app.core.security.permissions import requires_auth
from app.core.utils.inventory_quantity import quantity_to_api_str
from app.features.activity_log.routes.activity_routes import _human_summary
from app.observability import get_logger

logger = get_logger(__name__)


def _to_iso_timestamp(ts) -> str | None:
    """Normalize a timestamp to ISO format string for consistent API output."""
    if ts is None:
        return None
    if isinstance(ts, str):
        return ts
    if hasattr(ts, "isoformat"):
        return ts.isoformat()
    return str(ts)


def _log_trace_access_denied(org_id: UUID, item_id: UUID) -> None:
    """Same rationale as _log_process_access_denied, for the traceability slice's own
    item lookups (trace_raw_material, trace_inventory_backward, sourcemap_trace's
    current-state branch) -- a rejected lookup here is a tenant-boundary probe just as
    much as a stale/mistyped id, and the route can't distinguish the two in its response
    (AC2/AC6: cross-org existence must not be distinguishable from non-existence), so the
    log doesn't try to either.
    """
    logger.warning(
        "access_denied",
        reason="inventory_item_not_found_or_cross_org",
        feature="traceability",
        org_id=str(org_id),
        item_id=str(item_id),
        path=request.path,
    )


def _parse_uuid(v: str | None) -> UUID | None:
    """Parse v as a UUID, returning None on any failure. Avoids double-parsing and 500s on malformed DB values."""
    if not v:
        return None
    try:
        return UUID(str(v))
    except (ValueError, AttributeError):
        return None


def _hydrate_step_data(items: list[dict], db_session, org_id: UUID) -> None:
    """
    Attach step_data to each item dict in-place.

    Bulk-fetches ExecutionStep records for all items that have a source_execution_step_id,
    joining through Execution to enforce org_id (defense-in-depth against upstream scoping drift).
    Sets item["step_data"] = {completed_at, actual_inputs, actual_outputs} or None.
    """
    from app.core.db.models.execution import Execution as ExecutionModel
    from app.core.db.models.execution_step import ExecutionStep as ExecutionStepModel

    # Parse UUIDs once; raw value → UUID map eliminates second-pass parsing in the hydration loop.
    raw_to_uuid: dict[str, UUID] = {
        raw: uid for it in items if (raw := it.get("source_execution_step_id")) and (uid := _parse_uuid(raw))
    }
    step_ids: set[UUID] = set(raw_to_uuid.values())

    # UUID-keyed map: avoids str/UUID mismatch at lookup time.
    step_map: dict[UUID, ExecutionStepModel] = {}
    if step_ids:
        for _s in (
            db_session.query(ExecutionStepModel)
            .join(ExecutionModel, ExecutionStepModel.execution_id == ExecutionModel.id)
            .filter(ExecutionStepModel.id.in_(step_ids), ExecutionModel.org_id == org_id)
            .all()
        ):
            step_map[_s.id] = _s

    for _item in items:
        uid = raw_to_uuid.get(_item.get("source_execution_step_id"))
        _s = step_map.get(uid) if uid else None
        if uid and _s is None:
            logger.debug("_hydrate_step_data: ExecutionStep %s not found (org_id=%s)", uid, org_id)
        _item["step_data"] = (
            {
                "completed_at": _to_iso_timestamp(_s.completed_at),
                **entry_timing(_s.completed_at, _s.execution_data),
                "actual_inputs": _s.actual_inputs,
                "actual_outputs": _s.actual_outputs,
            }
            if _s
            else None
        )


def _trace_step_summaries(items: list[dict], db_session, org_id: UUID) -> list[dict]:
    """Return every producing operation represented by a traced inventory DAG.

    An inventory item points at the execution step that produced it. Collecting those
    pointers from the complete backward trace is more reliable than the old
    ``previous_steps_data`` display projection and gives clients a compact operation
    timeline without reimplementing DAG traversal from item JSON.
    """

    source_step_ids = {uid for item in items if (uid := _parse_uuid(item.get("source_execution_step_id"))) is not None}
    if not source_step_ids:
        return []

    traced_steps = (
        db_session.query(ExecutionStep)
        .join(Execution, ExecutionStep.execution_id == Execution.id)
        .filter(Execution.org_id == org_id, ExecutionStep.id.in_(source_step_ids))
        .options(joinedload(ExecutionStep.step))
        .all()
    )

    summaries = [
        {
            "execution_step_id": str(step.id),
            "execution_id": str(step.execution_id),
            "step_name": step.step.name if step.step else None,
            "step_number": step.step_number,
            "completed_at": _to_iso_timestamp(step.completed_at),
            **entry_timing(step.completed_at, step.execution_data),
        }
        for step in traced_steps
    ]
    # Completion time is the clearest ordering across branches/executions. Within one
    # execution it naturally presents the familiar #1 → #N operation sequence.
    summaries.sort(
        key=lambda step: (
            step["completed_at"] is None,
            step["completed_at"] or "",
            step["step_number"],
            step["execution_step_id"],
        )
    )
    return summaries


def register_routes(bp):
    """Register traceability routes on the given blueprint, preserving endpoint names."""

    @bp.route("/core/sourcemap", methods=["GET"])
    @requires_auth
    def sourcemap():
        """Serve the sourcemap.html frontend page"""
        return render_template("sourcemap/sourcemap.html", active_page="core")

    @bp.route("/api/core/inventory/trace/<raw_material_id>", methods=["GET"])
    @requires_auth
    def trace_raw_material(raw_material_id: str):
        """Trace forward from a raw material to find all connected intermediates and final products.

        Returns all items in the production chain regardless of current quantity — zero-quantity
        intermediates must be visible for a complete audit trail.
        """
        from app.core.backend.dagtraversal import trace_forward, validate_item_uuid
        from app.core.db.models.inventory_item import InventoryItem

        org_id = UUID(g.org_id)
        raw_material_uuid, err = validate_item_uuid(raw_material_id)
        if err or raw_material_uuid is None:
            return jsonify({"error": err or "Invalid raw material ID"}), 400

        raw_material = (
            db_session.query(InventoryItem)
            .filter(InventoryItem.id == raw_material_uuid, InventoryItem.org_id == org_id)
            .first()
        )
        if not raw_material:
            _log_trace_access_denied(org_id, raw_material_uuid)
            return jsonify({"error": "Raw material not found"}), 404

        result = trace_forward(
            org_id,
            db_session,
            raw_material_uuid,
            include_quantity_filter=False,
            root_item_id=raw_material_uuid,
        )
        connected_items = result["items"]
        connections = result["connections"]

        # Attach step_data to each item for historical quantities and step timestamps.
        _hydrate_step_data(connected_items, db_session, org_id)

        # Match original API: add direct connection from raw material to every connected item (execution_id as link)
        raw_id_str = str(raw_material_uuid)
        conn_pairs = {(c["from_id"], c["to_id"]) for c in connections}
        for item in connected_items:
            if item["id"] == raw_id_str:
                continue
            exec_id = item.get("source_execution_id")
            if exec_id and (raw_id_str, item["id"]) not in conn_pairs:
                connections.append({"from_id": raw_id_str, "to_id": item["id"], "execution_id": exec_id})
                conn_pairs.add((raw_id_str, item["id"]))

        # Only return connections where both from_id and to_id are inventory item IDs in the response.
        # This prevents the source map table from showing "TO <uuid>" when an ID is missing (e.g. execution_id).
        item_ids = {item["id"] for item in connected_items} | {raw_id_str}
        connections = [c for c in connections if c.get("from_id") in item_ids and c.get("to_id") in item_ids]

        raw_material_data = {
            "id": str(raw_material.id),
            "name": raw_material.name,
            "quantity": quantity_to_api_str(raw_material.quantity),
            "unit": raw_material.unit,
            "inventory_type": raw_material.inventory_type,
            "supplier": raw_material.supplier,
            "purchase_date": raw_material.purchase_date.isoformat() if raw_material.purchase_date else None,
            "supplier_batch_number": raw_material.supplier_batch_number,
            "expiry_date": raw_material.expiry_date.isoformat() if raw_material.expiry_date else None,
            "source_execution_id": str(raw_material.source_execution_id) if raw_material.source_execution_id else None,
            "source_execution_step_id": str(raw_material.source_execution_step_id)
            if raw_material.source_execution_step_id
            else None,
            "source_step_name": raw_material.source_step_name,
            "process_name": None,
            "created_at": raw_material.created_at.isoformat() if raw_material.created_at else None,
            "extra_data": raw_material.extra_data if raw_material.extra_data else {},
            "step_data": None,
        }
        if not any(item["id"] == str(raw_material.id) for item in connected_items):
            connected_items.insert(0, raw_material_data)

        intermediates = [
            item for item in connected_items if item["inventory_type"] == InventoryType.WORK_IN_PROGRESS.value
        ]
        finals = [item for item in connected_items if item["inventory_type"] == InventoryType.FINAL_PRODUCT.value]

        return jsonify(
            {
                "raw_material": raw_material_data,
                "intermediates": intermediates,
                "finals": finals,
                "all_items": connected_items,
                "connections": connections,
            }
        ), 200

    @bp.route("/api/core/inventory/trace-backward/<inventory_item_id>", methods=["GET"])
    @requires_auth
    def trace_inventory_backward(inventory_item_id: str):
        """Trace backward from any inventory item (raw, intermediate, or final) to find all source items.

        Returns all items in the production chain regardless of current quantity — zero-quantity
        intermediates must be visible for a complete audit trail.
        """
        from app.core.backend.dagtraversal import trace_backward, validate_item_uuid
        from app.core.db.models.inventory_item import InventoryItem

        org_id = UUID(g.org_id)
        item_uuid, err = validate_item_uuid(inventory_item_id)
        if err or item_uuid is None:
            return jsonify({"error": err or "Invalid inventory item ID"}), 400

        traced_item = (
            db_session.query(InventoryItem)
            .filter(InventoryItem.id == item_uuid, InventoryItem.org_id == org_id)
            .first()
        )
        if not traced_item:
            _log_trace_access_denied(org_id, item_uuid)
            return jsonify({"error": "Inventory item not found"}), 404

        result = trace_backward(
            org_id,
            db_session,
            item_uuid,
            include_quantity_filter=False,
            traced_item_id=item_uuid,
        )
        all_result_items = result["items"]
        connections = result["connections"]

        # Build traced_item_data first; add it to all_result_items so step enrichment and connection
        # filtering both include it. trace_backward only returns SOURCE items, not the traced item itself.
        traced_item_data = next(
            (item for item in all_result_items if item["id"] == str(traced_item.id)),
            None,
        )
        if traced_item_data is None:
            traced_extra = traced_item.extra_data if traced_item.extra_data else {}
            traced_item_data = {
                "id": str(traced_item.id),
                "name": traced_item.name,
                "quantity": quantity_to_api_str(traced_item.quantity),
                "unit": traced_item.unit,
                "inventory_type": traced_item.inventory_type,
                "supplier": traced_item.supplier,
                "purchase_date": traced_item.purchase_date.isoformat() if traced_item.purchase_date else None,
                "supplier_batch_number": traced_item.supplier_batch_number,
                "expiry_date": traced_item.expiry_date.isoformat() if traced_item.expiry_date else None,
                "source_execution_id": str(traced_item.source_execution_id)
                if traced_item.source_execution_id
                else None,
                "source_execution_step_id": str(traced_item.source_execution_step_id)
                if traced_item.source_execution_step_id
                else None,
                "source_step_name": traced_item.source_step_name,
                "process_name": None,
                "created_at": traced_item.created_at.isoformat() if traced_item.created_at else None,
                "extra_data": traced_extra,
                "step_data": None,
            }
            all_result_items.append(traced_item_data)

        # Attach step_data (including traced item itself, which is now in all_result_items).
        _hydrate_step_data(all_result_items, db_session, org_id)
        trace_steps = _trace_step_summaries(all_result_items, db_session, org_id)

        # Add direct connections from every source item to traced item (for sourcemap execution grouping)
        traced_id_str = str(traced_item.id)
        exec_id_str = str(traced_item.source_execution_id) if traced_item.source_execution_id else None
        if exec_id_str:
            existing_to_traced = {c["from_id"] for c in connections if c.get("to_id") == traced_id_str}
            for item in all_result_items:
                if item["id"] == traced_id_str:
                    continue
                if item["id"] not in existing_to_traced:
                    connections.append({"from_id": item["id"], "to_id": traced_id_str, "execution_id": exec_id_str})
                    existing_to_traced.add(item["id"])

        source_items_without_traced = [item for item in all_result_items if item["id"] != str(traced_item.id)]
        raw_materials = [
            item for item in source_items_without_traced if item["inventory_type"] == InventoryType.RAW_MATERIAL.value
        ]
        intermediates = [
            item
            for item in source_items_without_traced
            if item["inventory_type"] == InventoryType.WORK_IN_PROGRESS.value
        ]

        # Only return connections where both endpoints are items in the response (prevents TO <uuid> display).
        # all_result_items now includes traced_item so connections to it are preserved.
        all_item_ids = {item["id"] for item in all_result_items}
        connections = [c for c in connections if c.get("from_id") in all_item_ids and c.get("to_id") in all_item_ids]

        return jsonify(
            {
                "traced_item": traced_item_data,
                "raw_materials": raw_materials,
                "intermediates": intermediates,
                "all_items": all_result_items,
                "connections": connections,
                # Complete, deduplicated operations for inventory-card provenance. This
                # includes the traced item's producing step and every upstream operation,
                # regardless of current inventory quantity.
                "trace_steps": trace_steps,
            }
        ), 200

    @bp.route("/api/core/inventory/trace-graph/<inventory_item_id>", methods=["GET"])
    @requires_auth
    def trace_inventory_to_sale_graph(inventory_item_id: str):
        """Trace any inventory item from its source material through production to sales.

        The graph is bidirectional around the selected item, then augmented with terminal
        sales nodes using the persisted FIFO allocations. A sale edge therefore identifies
        the exact labelled final-product batch that fulfilled the invoice line.
        """
        from app.core.backend.dagtraversal import trace_bidirectional, validate_item_uuid
        from app.features.crm.services.sales_traceability_service import append_sales_to_dag

        org_id = UUID(g.org_id)
        item_uuid, err = validate_item_uuid(inventory_item_id)
        if err or item_uuid is None:
            return jsonify({"error": err or "Invalid inventory item ID"}), 400
        traced_item = (
            db_session.query(InventoryItem)
            .filter(InventoryItem.id == item_uuid, InventoryItem.org_id == org_id)
            .first()
        )
        if not traced_item:
            _log_trace_access_denied(org_id, item_uuid)
            return jsonify({"error": "Inventory item not found"}), 404

        traced = trace_bidirectional(
            org_id,
            db_session,
            item_uuid,
            include_quantity_filter=False,
            root_item_id=item_uuid,
        )
        inventory_by_id = {item["id"]: item for item in (traced["forward"]["items"] + traced["backward"]["items"])}
        connections_by_key = {
            (edge["from_id"], edge["to_id"], edge.get("execution_id") or ""): edge
            for edge in (traced["forward"]["connections"] + traced["backward"]["connections"])
        }
        inventory_items = list(inventory_by_id.values())
        _hydrate_step_data(inventory_items, db_session, org_id)
        sale_nodes, sale_edges = append_sales_to_dag(db_session, org_id, set(inventory_by_id))

        return jsonify(
            {
                "traced_item": inventory_by_id.get(str(item_uuid)),
                "all_items": inventory_items + sale_nodes,
                "connections": list(connections_by_key.values()) + sale_edges,
            }
        ), 200

    @bp.route("/api/core/sourcemap/objects", methods=["GET"])
    @requires_auth
    def sourcemap_objects():
        """Lightweight paginated index of all traceable entities.

        Returns just enough for selectors — no joins to steps or execution_steps.
        """
        org_id = UUID(g.org_id)
        db = db_session()

        try:
            page = max(1, int(request.args.get("page", 1)))
            limit = min(int(request.args.get("limit", 50)), 200)
        except (TypeError, ValueError):
            return jsonify({"error": "page and limit must be integers"}), 400
        offset = (page - 1) * limit
        q = request.args.get("q", "").strip()
        entity_type_filter = request.args.get("type", "").strip()

        objects = []
        total = 0

        from app.core.db.models.execution import Execution
        from app.core.db.models.inventory_item import InventoryItem

        if not entity_type_filter or entity_type_filter == "inventory_item":
            inv_q = db.query(InventoryItem).filter(InventoryItem.org_id == org_id)
            if q:
                inv_q = inv_q.filter(InventoryItem.name.ilike(f"%{q}%"))
            inv_count = inv_q.count()
            total += inv_count
            for item in (
                inv_q.order_by(InventoryItem.created_at.desc())
                .offset(offset if not entity_type_filter else 0)
                .limit(limit)
                .all()
            ):
                objects.append(
                    {
                        "id": str(item.id),
                        "type": "inventory_item",
                        "label": item.display_label or item.name,
                        "sublabel": f"{item.inventory_type.replace('_', ' ').title()} · {item.quantity} {item.unit}",
                        "discriminators": {
                            "supplier": item.supplier,
                            "batch_number": item.supplier_batch_number,
                            "expiry_date": item.expiry_date.isoformat() if item.expiry_date else None,
                            "quantity": str(item.quantity),
                            "unit": item.unit,
                        },
                        "traceable_since": item.created_at.isoformat() if item.created_at else None,
                        "is_consumed": str(item.quantity) == "0.0000",
                    }
                )

        if not entity_type_filter or entity_type_filter == "execution":
            exec_q = db.query(Execution).filter(Execution.org_id == org_id)
            exec_count = exec_q.count()
            total += exec_count
            for ex in exec_q.order_by(Execution.created_at.desc()).limit(limit).all():
                objects.append(
                    {
                        "id": str(ex.id),
                        "type": "execution",
                        "label": f"Execution #{str(ex.id)[:8]}",
                        "sublabel": f"{ex.status.value.replace('_', ' ').title()} · {ex.total_steps or '?'} steps",
                        "discriminators": {
                            "process_id": str(ex.process_id),
                            "status": ex.status.value,
                            "started_at": ex.started_at.isoformat() if ex.started_at else None,
                        },
                        "traceable_since": ex.created_at.isoformat() if ex.created_at else None,
                    }
                )

        if not entity_type_filter or entity_type_filter == "process":
            proc_q = db.query(Process).filter(Process.org_id == org_id)
            if q:
                proc_q = proc_q.filter(Process.name.ilike(f"%{q}%"))
            proc_count = proc_q.count()
            total += proc_count
            for proc in proc_q.order_by(Process.created_at.desc()).limit(limit).all():
                objects.append(
                    {
                        "id": str(proc.id),
                        "type": "process",
                        "label": proc.name,
                        "sublabel": f"{'Draft' if proc.is_draft else 'Published'} · {proc.category.value if proc.category else 'Uncategorised'}",
                        "discriminators": {
                            "category": proc.category.value if proc.category else None,
                            "is_draft": proc.is_draft,
                        },
                        "traceable_since": proc.created_at.isoformat() if proc.created_at else None,
                    }
                )

        return jsonify({"objects": objects[:limit], "total": total, "page": page}), 200

    @bp.route("/api/core/sourcemap/trace", methods=["POST"])
    @requires_auth
    def sourcemap_trace():
        """On-demand DAG traversal — current state or temporal (with as_of).

        Routes to DAGTracer (current) or TemporalDAGTracer (historical).
        """
        data = request.get_json() or {}
        root_type = data.get("root_type", "inventory_item")
        root_id_str = data.get("root_id")
        as_of_str = data.get("as_of")
        try:
            depth = min(int(data.get("depth", 5)), 10)
        except (TypeError, ValueError):
            return jsonify({"error": "depth must be an integer"}), 400

        if not root_id_str:
            return jsonify({"error": "root_id is required"}), 400

        try:
            root_id = UUID(root_id_str)
        except ValueError:
            return jsonify({"error": "Invalid root_id"}), 400

        org_id = UUID(g.org_id)
        db = db_session()

        # Temporal trace — use as_of if provided
        if as_of_str:
            try:
                as_of = datetime.fromisoformat(as_of_str.replace("Z", "+00:00"))
            except ValueError:
                return jsonify({"error": "Invalid as_of datetime format"}), 400

            from app.core.backend.temporal_dag_tracer import TemporalDAGTracer

            tracer = TemporalDAGTracer(db, org_id, as_of, max_depth=depth)
            result = tracer.trace(root_id, root_type)

            # Annotate timeline with human summaries
            from app.core.db.models.entity_event import EntityEvent as _EE_Trace

            timeline_ids = [item.get("event_id") for item in result["timeline"] if item.get("event_id")]
            events_by_id: dict = {}
            if timeline_ids:
                ev_rows = db.query(_EE_Trace).filter(_EE_Trace.id.in_(timeline_ids), _EE_Trace.org_id == org_id).all()
                events_by_id = {str(ev.id): ev for ev in ev_rows}
            story = [
                {
                    "at": item["at"],
                    "event_type": item["event_type"],
                    "entity_id": item["entity_id"],
                    "summary": _human_summary(events_by_id[item["event_id"]])
                    if item.get("event_id") and item["event_id"] in events_by_id
                    else item["event_type"].replace(".", " — ").replace("_", " ").capitalize(),
                    "actor": item.get("actor"),
                }
                for item in result["timeline"]
            ]

            return jsonify(
                {
                    "root": next(
                        (n for n in result["nodes"] if n["is_root"]), result["nodes"][0] if result["nodes"] else {}
                    ),
                    "nodes": result["nodes"],
                    "edges": result["edges"],
                    "as_of": result["as_of"],
                    "is_current": False,
                    "story": story,
                }
            ), 200

        # Current state trace — use existing DAGTracer
        from app.core.db.models.inventory_item import InventoryItem

        item = db.query(InventoryItem).filter(InventoryItem.id == root_id, InventoryItem.org_id == org_id).first()
        if not item:
            _log_trace_access_denied(org_id, root_id)
            return jsonify({"error": "Item not found"}), 404

        try:
            from app.core.backend.dagtraversal import trace_bidirectional

            both = trace_bidirectional(org_id, db, root_id, include_quantity_filter=False, root_item_id=root_id)
            result_fwd = both["forward"]
            result_bwd = both["backward"]

            all_nodes = {n["id"]: n for n in (result_fwd["items"] + result_bwd["items"])}
            all_edges = {(e["from_id"], e["to_id"]): e for e in (result_fwd["connections"] + result_bwd["connections"])}

            return jsonify(
                {
                    "root": {"id": str(root_id), "type": "inventory_item", "label": item.display_label or item.name},
                    "nodes": list(all_nodes.values()),
                    "edges": [
                        {"from": e["from_id"], "to": e["to_id"], "execution_id": e.get("execution_id")}
                        for e in all_edges.values()
                    ],
                    "as_of": None,
                    "is_current": True,
                    "story": [],
                }
            ), 200
        except Exception:
            logger.exception("Trace failed")
            return jsonify({"error": "Trace failed"}), 500
