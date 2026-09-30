"""Inventory page and API routes. Register with register_routes(core_bp)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from uuid import UUID

from flask import g, jsonify, render_template, request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from app.core.backend.event_writer import EventWriter
from app.core.db import db_session
from app.core.db.models.entity_event_summary import EntityEventSummary
from app.core.db.models.execution import Execution
from app.core.db.models.execution_step import ExecutionStep
from app.core.db.models.inventory_item import InventoryItem, InventoryType
from app.core.db.repositories.inventory_repo import InventoryRepository
from app.core.domain.inventory_quantity_guard import (
    InventoryQuantityWriteReason,
    allow_inventory_quantity_write,
)
from app.core.security.permissions import requires_auth
from app.core.utils.internal_counters import inc_counter
from app.core.utils.inventory_quantity import (
    coerce_stored_quantity,
    parse_stored_quantity_to_decimal,
    quantity_to_api_str,
)
from app.features.compliance_checks.routes import corechecks
from app.features.reconciliation.service import _find_producing_step
from app.observability import get_logger

logger = get_logger(__name__)

_VALID_INVENTORY_TYPES = frozenset(t.value for t in InventoryType)
LIST_INVENTORY_MAX_PREVIOUS_STEPS = 80
LIST_INVENTORY_MAX_AUDIT_HISTORY = 120
LIST_INVENTORY_MAX_RECONCILIATION_HISTORY = 60
_LIST_ITEM_MAX_CHARS = 4096
_LIST_ITEM_MAX_NESTED = 20


def _trim_value(v):
    """Cap strings, lists, and dicts one level deep — prevents deep payload explosions."""
    if isinstance(v, str) and len(v) > _LIST_ITEM_MAX_CHARS:
        return v[:_LIST_ITEM_MAX_CHARS] + "…"
    if isinstance(v, list):
        return v[:_LIST_ITEM_MAX_NESTED]
    if isinstance(v, dict):
        return {k: _trim_value(val) for k, val in list(v.items())[:_LIST_ITEM_MAX_NESTED]}
    return v


def _safe_slice_list(lst: list, max_len: int) -> list:
    """Slice list and recursively bound values inside dict items."""
    out = []
    for item in lst[:max_len]:
        if isinstance(item, dict):
            out.append({k: _trim_value(v) for k, v in item.items()})
        else:
            out.append(item)
    return out


def _bound_inventory_extra_data_for_list_response(extra_data: dict) -> dict:
    """Clamp large nested lists in extra_data for list responses (operator UI only)."""
    if not extra_data:
        return extra_data
    out = dict(extra_data)
    psd = out.get("previous_steps_data")
    if isinstance(psd, list):
        out["previous_steps_data"] = _safe_slice_list(psd, LIST_INVENTORY_MAX_PREVIOUS_STEPS)
    ah = out.get("inventory_audit_history")
    if isinstance(ah, list):
        sliced = _safe_slice_list(ah, LIST_INVENTORY_MAX_AUDIT_HISTORY)
        out["inventory_audit_history"] = [
            {k: v for k, v in entry.items() if k != "user_id"} if isinstance(entry, dict) else entry for entry in sliced
        ]
    rh = out.get("reconciliation_history")
    if isinstance(rh, list):
        out["reconciliation_history"] = _safe_slice_list(rh, LIST_INVENTORY_MAX_RECONCILIATION_HISTORY)
    return out


def register_routes(bp, *, parse_page_params, encode_list_cursor, split_execution_data):
    """Register inventory routes; shared pagination/execution serializers stay in Core shell."""

    @bp.route("/core/inventory/add", methods=["GET"])
    @requires_auth
    def inventory_add_hub():
        """Inventory entry hub: choose manual / CSV / barcode."""
        return render_template("inventory/add.html", active_page="core")

    @bp.route("/core/inventory/add/manual", methods=["GET"])
    @requires_auth
    def inventory_add_manual():
        """Add inventory via manual single-item form."""
        return render_template("inventory/add_manual.html", active_page="core")

    @bp.route("/core/inventory/add/csv", methods=["GET"])
    @requires_auth
    def inventory_add_csv():
        """Add or update inventory in bulk via CSV upload."""
        return render_template("inventory/add_csv.html", active_page="core")

    @bp.route("/core/inventory/add/barcode", methods=["GET"])
    @requires_auth
    def inventory_add_barcode():
        """Add inventory via barcode / camera scan."""
        return render_template("inventory/add_barcode.html", active_page="core")

    @bp.route("/core/inventory/view", methods=["GET"])
    @requires_auth
    def inventory_view():
        """Full-page inventory list with filtering."""
        return render_template("inventory/view.html", active_page="core")

    @bp.route("/core/inventory/live", methods=["GET"])
    @requires_auth
    def inventory_live_view():
        """Dedicated live inventory experience (drill-in from Core inventory tab)."""
        return render_template("core/core2.html", active_page="core", core2_focus="inventory_live")

    @bp.route("/api/core/inventory", methods=["GET"])
    @requires_auth
    def list_inventory():
        """List inventory items, optionally filtered by type or process"""
        org_id = UUID(g.org_id)
        inventory_type = request.args.get("type")
        process_id_str = request.args.get("process_id")

        process_id = None
        if process_id_str:
            try:
                process_id = UUID(process_id_str)
            except ValueError:
                return jsonify({"error": "Invalid process_id parameter"}), 400

        try:
            page_limit, cursor = parse_page_params(request.args)
        except ValueError:
            return jsonify({"error": "Invalid limit or cursor parameter"}), 400

        repo = InventoryRepository(db_session)
        items = repo.list_inventory_items(
            org_id=org_id,
            inventory_type=inventory_type,
            process_id=process_id,
            limit=(page_limit + 1 if page_limit is not None else None),
            cursor=cursor,
        )
        has_more = page_limit is not None and len(items) > page_limit
        if has_more:
            items = items[:page_limit]
        next_cursor = encode_list_cursor(items[-1].created_at, items[-1].id) if has_more and items else None

        # Compact view: just the core item fields, no per-item enrichment (system findings,
        # producing-step hydration, ready-date lookups, audit history). The sourcemap browse
        # grid groups the whole list by name / batch / supplier and needs none of that; the
        # full representation is ~20x larger.
        if request.args.get("view") == "compact":
            return jsonify(
                {
                    "inventory_items": [
                        {
                            "id": str(i.id),
                            "name": i.name,
                            "display_label": i.display_label,
                            "inventory_type": i.inventory_type,
                            "quantity": str(i.quantity),
                            "unit": i.unit,
                            "supplier": i.supplier,
                            "supplier_batch_number": i.supplier_batch_number,
                            "expiry_date": i.expiry_date.isoformat() if i.expiry_date else None,
                        }
                        for i in items
                    ],
                    "has_more": has_more,
                    "next_cursor": next_cursor,
                }
            ), 200

        # System findings per item (all checks) for UI: red border + reasons in dropdown
        findings_by_id = corechecks.get_system_findings_by_item(org_id, db_session)

        from app.core.db.models.inventory_item import InventoryItem
        from app.features.compliance_checks.checks.output_ready_date_check import get_operator_ready_instant_for_item

        # One query for all producing steps (avoids N+1 hydration + ready-date lookups).
        # JOIN Execution + filter org_id: bounded by step_ids (inventory row count), no materialized list of all org executions.
        # Step.outputs is JSONB on `steps` (see Step model); joinedload(ExecutionStep.step) loads one row per step — no relationship N+1 for outputs.
        step_ids = {i.source_execution_step_id for i in items if i.source_execution_step_id}
        execution_step_by_id: dict = {}
        if step_ids:
            loaded_steps = (
                db_session.query(ExecutionStep)
                .join(Execution, ExecutionStep.execution_id == Execution.id)
                .filter(Execution.org_id == org_id)
                .filter(ExecutionStep.id.in_(step_ids))
                .options(joinedload(ExecutionStep.step))
                .all()
            )
            execution_step_by_id = {es.id: es for es in loaded_steps}

        # Batch-load executions and their processes for process-name and untracked-step lookups.
        # Replaces per-item db_session.query(Execution/Process) calls inside the loop below.
        source_exec_ids = {i.source_execution_id for i in items if i.source_execution_id}
        execution_by_id: dict = {}
        process_by_id: dict = {}
        if source_exec_ids:
            loaded_execs = (
                db_session.query(Execution)
                .filter(Execution.org_id == org_id)
                .filter(Execution.id.in_(source_exec_ids))
                .all()
            )
            execution_by_id = {e.id: e for e in loaded_execs}
            proc_ids = {e.process_id for e in loaded_execs if e.process_id}
            if proc_ids:
                from sqlalchemy.orm import selectinload

                from app.core.db.models.process import Process as ProcessModel

                loaded_procs = (
                    db_session.query(ProcessModel)
                    .filter(ProcessModel.org_id == org_id)
                    .filter(ProcessModel.id.in_(proc_ids))
                    .options(selectinload(ProcessModel.steps))
                    .all()
                )
                process_by_id = {p.id: p for p in loaded_procs}

        # Batch-load event summaries for card enrichment (single query, no N+1)

        item_ids_all = [item.id for item in items]
        event_summary_by_id: dict = {}
        if item_ids_all:
            # entity_id is this table's PK and the ids came from an org-scoped query, so the
            # org filter is redundant today — kept because every other tenant table in this
            # file is scoped explicitly, and the redundancy is what survives the next refactor.
            ees_rows = (
                db_session.query(EntityEventSummary)
                .filter(EntityEventSummary.entity_id.in_(item_ids_all), EntityEventSummary.org_id == org_id)
                .all()
            )
            event_summary_by_id = {str(r.entity_id): r.summary for r in ees_rows}

        # Lazy, request-scoped cache for the backward DAG trace below (previous_steps_data).
        # Populated on first use, not unconditionally: an org whose inventory is all raw
        # materials never pays for it. Once populated it holds every org-scoped InventoryItem
        # and ExecutionStep, so trace_step_chain() below does in-memory dict lookups instead
        # of two DB queries per node — same bulk-load-then-walk-in-memory shape as
        # DAGTracer.traverse() (dagtraversal.py), just inlined here to keep this function's
        # existing previous_steps_data output shape unchanged.
        _dag_trace_cache: dict[str, dict] = {}

        def _dag_trace_lookups():
            if not _dag_trace_cache:
                # DAG traversal needs the complete graph in memory — a LIMIT would silently
                # truncate a chain mid-trace (same rationale as DAGTracer.traverse() above).
                all_items = (  # nosemgrep: sqlalchemy-all-without-limit
                    db_session.query(InventoryItem).filter(InventoryItem.org_id == org_id).all()
                )
                all_steps = (  # nosemgrep: sqlalchemy-all-without-limit
                    db_session.query(ExecutionStep)
                    .join(Execution, ExecutionStep.execution_id == Execution.id)
                    .filter(Execution.org_id == org_id)
                    .options(joinedload(ExecutionStep.step))
                    .all()
                )
                _dag_trace_cache["items_by_id"] = {str(i.id): i for i in all_items}
                _dag_trace_cache["steps_by_id"] = {s.id: s for s in all_steps}
            return _dag_trace_cache["items_by_id"], _dag_trace_cache["steps_by_id"]

        result = []
        for item in items:
            # Filter out items with zero or negative quantity
            # QUANTITY PRECISION: Use Decimal for safe comparison
            try:
                quantity_decimal = parse_stored_quantity_to_decimal(item.quantity)
                # Skip items with zero or negative quantity (including very small numbers)
                if quantity_decimal <= 0 or abs(quantity_decimal) < Decimal("0.0001"):
                    continue  # Skip this item
            except (InvalidOperation, ValueError, TypeError):
                # If quantity is not a valid number, skip this item
                continue

            # Hydrate extra_data from the producing ExecutionStep when needed (shallow copy so we don't mutate ORM JSON in place).
            # Prompts, trace, inputs, and output are filled independently — previously inputs were only loaded when
            # execution_prompts was missing, which hid variable_inputs on many intermediate/final items.
            extra_data = {**(item.extra_data or {})}
            src_step = (
                execution_step_by_id.get(item.source_execution_step_id) if item.source_execution_step_id else None
            )
            if src_step:
                try:
                    if src_step.execution_data:
                        execution_prompts, execution_trace = split_execution_data(
                            src_step.execution_data, completed_at=src_step.completed_at
                        )
                        if not extra_data.get("execution_prompts"):
                            extra_data["execution_prompts"] = execution_prompts or {}
                        if not extra_data.get("execution_trace"):
                            extra_data["execution_trace"] = execution_trace or {}

                    if not extra_data.get("variable_inputs"):
                        if src_step.actual_inputs:
                            extra_data["variable_inputs"] = src_step.actual_inputs
                        else:
                            extra_data["variable_inputs"] = []

                    if not extra_data.get("variable_output") and src_step.actual_outputs:
                        output_name = item.name
                        matching_output = next(
                            (o for o in src_step.actual_outputs if o.get("name") == output_name), None
                        )
                        if matching_output:
                            extra_data["variable_output"] = matching_output
                except Exception:
                    inc_counter("inventory_hydration_failures")

            # Look up previous steps data for intermediate products AND final products
            # DAG TRAVERSAL PERFORMANCE WARNING:
            # This recursive traversal happens inside list_inventory() which is called frequently.
            # For large DAGs with deep chains, this can become a scalability bottleneck.
            # Consider:
            # 1. Caching previous_steps_data in extra_data (but mark as derived/read-only)
            # 2. Separating traceability queries into a dedicated endpoint
            # 3. Adding depth limits or pagination for very deep chains
            # 4. Using materialized views or denormalized data for common queries
            #
            # Traverse the full chain of steps that produced the inputs
            previous_steps_data = []
            # Check if this is a WIP or final product that has variable inputs
            has_variable_inputs = extra_data.get("variable_inputs") and len(extra_data.get("variable_inputs", [])) > 0
            if (
                item.inventory_type == InventoryType.WORK_IN_PROGRESS.value
                or item.inventory_type == InventoryType.FINAL_PRODUCT.value
            ) and has_variable_inputs:
                try:
                    # Helper function to recursively trace back through the chain of steps
                    # PERFORMANCE: This recursive traversal can be expensive for deep DAGs
                    # Consider adding depth limits or caching strategies for production use
                    def trace_step_chain(
                        inventory_item_id,
                        input_name=None,
                        input_quantity=None,
                        input_unit=None,
                        visited_ids=None,
                        depth=0,
                    ):
                        """Recursively trace back through all steps that produced this inventory item

                        Args:
                            inventory_item_id: UUID of inventory item to trace
                            input_name: Name of input consumed from this step
                            input_quantity: Quantity consumed
                            input_unit: Unit of quantity consumed
                            visited_ids: Set of visited inventory item IDs to prevent cycles
                            depth: Current recursion depth (for safety limits)

                        Returns:
                            List of step data dictionaries in chronological order (oldest first)
                        """
                        # Safety limit to prevent excessive recursion (configurable)
                        max_dag_depth = 50
                        if depth > max_dag_depth:
                            logger.warning(
                                f"DAG traversal depth limit ({max_dag_depth}) reached for inventory item {inventory_item_id}"
                            )
                            return []

                        if visited_ids is None:
                            visited_ids = set()

                        # Prevent infinite loops (cycle detection)
                        if inventory_item_id in visited_ids:
                            logger.warning(f"Cycle detected in DAG traversal at inventory item {inventory_item_id}")
                            return []
                        visited_ids.add(inventory_item_id)

                        steps_data = []

                        # Look up the input inventory item (in-memory; see _dag_trace_lookups above —
                        # this used to be a per-node query, which made list_inventory() O(items x depth)
                        # queries for orgs with any WIP/final-product history).
                        items_by_id, steps_by_id = _dag_trace_lookups()
                        input_inventory_item = items_by_id.get(str(inventory_item_id))

                        if not input_inventory_item or not input_inventory_item.source_execution_step_id:
                            return steps_data

                        # Look up the execution step that produced this input (in-memory; org-scoped
                        # via the bulk load's Execution.org_id join, which is a stricter tenant check
                        # than the previous unscoped-by-org query relied on the FK invariant for).
                        input_execution_step = steps_by_id.get(input_inventory_item.source_execution_step_id)

                        if not input_execution_step:
                            return steps_data

                        # Build step data for this step
                        step_data = {
                            "step_name": input_execution_step.step.name if input_execution_step.step else None,
                            "step_number": input_execution_step.step_number,
                            "completed_at": input_execution_step.completed_at.isoformat()
                            if input_execution_step.completed_at
                            else None,
                        }

                        # Add input information (what was consumed from the previous step)
                        if input_name:
                            step_data["input_name"] = input_name
                        if input_quantity is not None:
                            step_data["input_quantity"] = input_quantity
                        if input_unit:
                            step_data["input_unit"] = input_unit

                        # Add full execution metadata for sourcemap/audit traceability (every piece traceable)
                        if input_execution_step.execution_data:
                            prev_prompts, prev_trace = split_execution_data(
                                input_execution_step.execution_data,
                                completed_at=input_execution_step.completed_at,
                            )
                            if prev_prompts:
                                step_data["execution_prompts"] = prev_prompts
                            if prev_trace.get("completed_by") is not None:
                                step_data["completed_by"] = prev_trace["completed_by"]
                            if prev_trace.get("completed_at") is not None:
                                step_data["completed_at"] = prev_trace["completed_at"]
                            if prev_trace.get("execution_errors") is not None:
                                step_data["execution_errors"] = prev_trace["execution_errors"]
                            if prev_trace.get("execution_warnings") is not None:
                                step_data["execution_warnings"] = prev_trace["execution_warnings"]

                        # Add this step to the list
                        steps_data.append(step_data)

                        # Now trace back through this step's inputs
                        if input_execution_step.actual_inputs:
                            for prev_input_data in input_execution_step.actual_inputs:
                                prev_inventory_item_id = prev_input_data.get("inventory_item_id")
                                if prev_inventory_item_id:
                                    # Recursively get steps that produced this input
                                    # Pass the input information so we know what was consumed
                                    # Increment depth to track recursion level
                                    prev_steps = trace_step_chain(
                                        prev_inventory_item_id,
                                        input_name=prev_input_data.get("name"),
                                        input_quantity=prev_input_data.get("quantity"),
                                        input_unit=prev_input_data.get("unit"),
                                        visited_ids=visited_ids,
                                        depth=depth + 1,
                                    )
                                    # Prepend previous steps (so they appear in chronological order)
                                    steps_data = prev_steps + steps_data

                        return steps_data

                    # For each variable input, trace back through the full chain
                    for input_data in extra_data["variable_inputs"]:
                        inventory_item_id = input_data.get("inventory_item_id")
                        if inventory_item_id:
                            # Trace the full chain of steps, passing the input information
                            chain_steps = trace_step_chain(
                                inventory_item_id,
                                input_name=input_data.get("name"),
                                input_quantity=input_data.get("quantity"),
                                input_unit=input_data.get("unit"),
                            )
                            previous_steps_data.extend(chain_steps)

                    # Remove duplicates (same step_number and step_name) while preserving order
                    seen = set()
                    unique_steps = []
                    for step in previous_steps_data:
                        step_key = (step.get("step_number"), step.get("step_name"))
                        if step_key not in seen:
                            seen.add(step_key)
                            unique_steps.append(step)
                    previous_steps_data = unique_steps

                    # Sort by step_number in descending order (most recent first, oldest at bottom)
                    previous_steps_data.sort(key=lambda x: x.get("step_number", 0), reverse=True)

                except Exception:
                    # If lookup fails, just continue without previous steps data
                    logger.exception("Error tracing step chain")
                    pass

            # EXTRA_DATA DISCIPLINE: previous_steps_data is derived/read-only data for display only
            # It should NEVER be persisted to the database - it's computed on-the-fly for traceability
            # This ensures we don't accidentally persist derived data that could become stale
            if previous_steps_data:
                extra_data["previous_steps_data"] = previous_steps_data

            # Get process name from execution if available (uses pre-loaded batch dicts)
            process_name = None
            if item.source_execution_id:
                try:
                    execution = execution_by_id.get(item.source_execution_id)
                    if execution and execution.process_id:
                        process = process_by_id.get(execution.process_id)
                        if process:
                            process_name = process.name
                except Exception:
                    pass
            if not process_name:
                try:
                    tagged = (extra_data or {}).get("producing_process_name")
                    if tagged:
                        process_name = str(tagged)
                except Exception:
                    pass

            # For untracked items, resolve producing step (step that defines this output) for "Execute next step" button
            producing_step_id = None
            producing_step_name = None
            if extra_data.get("untracked") and item.source_execution_id:
                try:
                    execution = execution_by_id.get(item.source_execution_id)
                    if execution and execution.process_id:
                        process_with_steps = process_by_id.get(execution.process_id)
                        if process_with_steps:
                            producing_step_id, producing_step_name = _find_producing_step(
                                process_with_steps, item.name, item.unit
                            )
                        # Fallback: if no output match (e.g. name/unit mismatch), use the step where item was added
                        if not producing_step_id and item.source_execution_step_id:
                            es_untracked = execution_step_by_id.get(item.source_execution_step_id)
                            if es_untracked:
                                producing_step_id = es_untracked.step_id
                                if es_untracked.step:
                                    producing_step_name = es_untracked.step.name
                except Exception:
                    inc_counter("inventory_producing_step_failures")
                    logger.debug(
                        "list_inventory producing_step resolution failed item_id=%s",
                        item.id,
                        exc_info=True,
                    )
            if not producing_step_name:
                try:
                    tagged_step = (extra_data or {}).get("producing_step_name")
                    if tagged_step:
                        producing_step_name = str(tagged_step)
                except Exception:
                    inc_counter("inventory_producing_step_name_fallback_failures")
                    logger.debug(
                        "list_inventory producing_step_name fallback failed item_id=%s", item.id, exc_info=True
                    )

            # Single operator-facing ready instant (set_at_execution date or fixed-duration from step completion)
            ready_date_display = None
            try:
                rdt = get_operator_ready_instant_for_item(db_session, item, execution_step=src_step)
                if rdt:
                    ready_date_display = rdt.isoformat()
            except Exception:
                inc_counter("ready_date_compute_failures")
                logger.debug("list_inventory ready_date_display failed item_id=%s", item.id, exc_info=True)

            result.append(
                {
                    "id": str(item.id),
                    "name": item.name,
                    "quantity": quantity_to_api_str(item.quantity),
                    "unit": item.unit,
                    "inventory_type": item.inventory_type,
                    "barcode": item.barcode,
                    "supplier": item.supplier,
                    "purchase_date": item.purchase_date.isoformat() if item.purchase_date else None,
                    "supplier_batch_number": item.supplier_batch_number,
                    "expiry_date": item.expiry_date.isoformat() if item.expiry_date else None,
                    "source_execution_id": str(item.source_execution_id) if item.source_execution_id else None,
                    "source_execution_step_id": str(item.source_execution_step_id)
                    if item.source_execution_step_id
                    else None,
                    "source_output_id": str(item.source_output_id) if item.source_output_id else None,
                    "source_step_name": item.source_step_name,
                    "process_name": process_name,
                    "producing_step_id": str(producing_step_id) if producing_step_id else None,
                    "producing_step_name": producing_step_name,
                    "created_at": item.created_at.isoformat() if item.created_at else None,
                    "extra_data": _bound_inventory_extra_data_for_list_response(extra_data),
                    "system_findings": findings_by_id.get(str(item.id), []),
                    "ready_date_display": ready_date_display,
                    "event_summary": event_summary_by_id.get(str(item.id)),
                }
            )

        body = {"inventory_items": result}
        if page_limit is not None:
            # next_cursor points at the last FETCHED row (pre zero-quantity filtering) so the
            # next page's keyset scan continues from the right place regardless of how many
            # rows the display filter dropped.
            body["has_more"] = has_more
            body["next_cursor"] = next_cursor
        return jsonify(body), 200

    @bp.route("/api/core/inventory/out-of-stock", methods=["GET"])
    @requires_auth
    def list_out_of_stock_raw_materials():
        """List raw materials with zero quantity for recall/traceability purposes.

        Returns raw materials that have been fully consumed (quantity = 0) but may still
        need to be traced for supplier recall scenarios.
        """
        org_id = UUID(g.org_id)

        # Query raw materials with exactly zero quantity
        # Note: We use exact zero comparison, not near-zero, as some customer processes
        # may require very precise measurements where small quantities are still valid stock
        items = (
            db_session.query(InventoryItem)
            .filter(InventoryItem.org_id == org_id)
            .filter(InventoryItem.inventory_type == InventoryType.RAW_MATERIAL.value)
            .order_by(InventoryItem.purchase_date.desc().nullslast(), InventoryItem.created_at.desc())
            .all()
        )

        result = []
        for item in items:
            quantity_decimal = parse_stored_quantity_to_decimal(item.quantity)
            if quantity_decimal != Decimal("0"):
                continue

            result.append(
                {
                    "id": str(item.id),
                    "name": item.name,
                    "quantity": quantity_to_api_str(item.quantity),
                    "unit": item.unit,
                    "inventory_type": item.inventory_type,
                    "supplier": item.supplier,
                    "purchase_date": item.purchase_date.isoformat() if item.purchase_date else None,
                    "supplier_batch_number": item.supplier_batch_number,
                    "expiry_date": item.expiry_date.isoformat() if item.expiry_date else None,
                    "source_execution_id": str(item.source_execution_id) if item.source_execution_id else None,
                    "source_execution_step_id": str(item.source_execution_step_id)
                    if item.source_execution_step_id
                    else None,
                    "source_step_name": item.source_step_name,
                    "created_at": item.created_at.isoformat() if item.created_at else None,
                    "extra_data": item.extra_data if item.extra_data else {},
                    "is_out_of_stock": True,
                }
            )

        return jsonify({"inventory_items": result}), 200

    @bp.route("/api/core/inventory", methods=["POST"])
    @requires_auth
    def create_inventory_item():
        """Create a new inventory item (typically raw material). Supports barcode; enforces product identity when barcode exists."""
        org_id = UUID(g.org_id)
        data = request.get_json()

        name = (data.get("name") or "").strip() or None
        quantity = data.get("quantity")
        unit = (data.get("unit") or "").strip() or None
        inventory_type = data.get("inventory_type", InventoryType.RAW_MATERIAL.value)

        # inventory_type is a plain String(50) with no DB constraint, and several views match
        # it exactly (`/out-of-stock`, `?type=`). An off-enum value therefore does not error —
        # the item just silently stops appearing in the recall-tracing view. Validate here.
        if inventory_type not in _VALID_INVENTORY_TYPES:
            return jsonify(
                {"error": f"inventory_type must be one of: {', '.join(sorted(_VALID_INVENTORY_TYPES))}"}
            ), 400
        barcode = (data.get("barcode") or "").strip() or None

        if quantity is None or (isinstance(quantity, str) and not quantity.strip()):
            return jsonify({"error": "quantity is required"}), 400
        try:
            qty_val = float(quantity)
            if qty_val <= 0:
                return jsonify({"error": "quantity must be greater than 0"}), 400
        except (TypeError, ValueError):
            return jsonify({"error": "quantity must be a valid number"}), 400

        repo = InventoryRepository(db_session)
        try:
            # If barcode provided and we have an existing row for it, add quantity to it (one row per barcode per org)
            if barcode:
                existing = repo.find_by_barcode(org_id, barcode)
                if existing:
                    if name is not None and name != existing.name:
                        return jsonify({"error": "Product name does not match existing product for this barcode"}), 409
                    if unit is not None and unit != existing.unit:
                        return jsonify({"error": "Unit does not match existing product for this barcode"}), 409
                    # Add quantity to existing item; supplier is stock-level (stored in audit only, row.supplier unchanged)
                    supplier = (data.get("supplier") or "").strip() or None
                    purchase_date = None
                    if data.get("purchase_date"):
                        purchase_date = datetime.fromisoformat(data.get("purchase_date").replace("Z", "+00:00")).date()
                    expiry_date = None
                    if data.get("expiry_date"):
                        expiry_date = datetime.fromisoformat(data.get("expiry_date").replace("Z", "+00:00")).date()
                    source_method = (data.get("source_method") or "barcode_scan").strip()
                    if source_method not in ("manual", "csv_upload", "barcode_scan"):
                        source_method = "barcode_scan"
                    # Human-friendly operator fields for audit (self-contained, append-only).
                    operator_email = getattr(getattr(g, "current_user", None), "email", None)
                    operator_first = getattr(getattr(g, "current_user", None), "first_name", None)
                    operator_last = getattr(getattr(g, "current_user", None), "last_name", None)
                    operator_name = " ".join([x for x in [operator_first, operator_last] if x]) or operator_email
                    audit_entry = {
                        "user_id": str(g.user_id) if getattr(g, "user_id", None) else None,
                        "operator_email": operator_email,
                        "operator_name": operator_name,
                        "timestamp_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "source_method": source_method,
                        "quantity_added": str(quantity),
                        "supplier": supplier,
                        "purchase_date": purchase_date.isoformat() if purchase_date else None,
                        "expiry_date": expiry_date.isoformat() if expiry_date else None,
                        "supplier_batch_number": (data.get("supplier_batch_number") or "").strip() or None,
                    }
                    extra_merge = {"inventory_audit_history": [audit_entry]}
                    updated = repo.add_quantity_to_inventory_item(
                        existing.id, org_id, str(quantity), extra_data_merge=extra_merge, commit=True
                    )
                    if not updated:
                        return jsonify({"error": "Failed to add quantity to existing item"}), 500
                    return (
                        jsonify(
                            {
                                "id": str(updated.id),
                                "name": updated.name,
                                "quantity": quantity_to_api_str(updated.quantity),
                                "unit": updated.unit,
                                "inventory_type": updated.inventory_type,
                                "supplier": updated.supplier,
                                "purchase_date": updated.purchase_date.isoformat() if updated.purchase_date else None,
                                "supplier_batch_number": updated.supplier_batch_number,
                                "expiry_date": updated.expiry_date.isoformat() if updated.expiry_date else None,
                                "created_at": updated.created_at.isoformat() if updated.created_at else None,
                                "quantity_added": True,
                            }
                        ),
                        200,
                    )
                elif not name or not unit:
                    return jsonify({"error": "name and unit are required for new barcode"}), 400
            if not name:
                return jsonify({"error": "name is required"}), 400
            if not unit:
                return jsonify({"error": "unit is required"}), 400

            supplier = (data.get("supplier") or "").strip() or None
            # Parse purchase date if provided
            purchase_date = None
            if data.get("purchase_date"):
                purchase_date = datetime.fromisoformat(data.get("purchase_date").replace("Z", "+00:00")).date()

            expiry_date = None
            if data.get("expiry_date"):
                expiry_date = datetime.fromisoformat(data.get("expiry_date").replace("Z", "+00:00")).date()

            # Optional traceability (e.g. in-flow "add missing output" from execution step)
            source_execution_id = None
            if data.get("source_execution_id"):
                source_execution_id = UUID(data["source_execution_id"])
            source_execution_step_id = None
            if data.get("source_execution_step_id"):
                source_execution_step_id = UUID(data["source_execution_step_id"])
            source_output_id = None
            if data.get("source_output_id"):
                source_output_id = UUID(data["source_output_id"])

            extra_data = dict(data.get("metadata") or {})
            source_method = (data.get("source_method") or "manual").strip()
            if source_method not in ("manual", "csv_upload", "barcode_scan"):
                source_method = "manual"
            # Human-friendly operator fields for audit (self-contained, append-only).
            operator_email = getattr(getattr(g, "current_user", None), "email", None)
            operator_first = getattr(getattr(g, "current_user", None), "first_name", None)
            operator_last = getattr(getattr(g, "current_user", None), "last_name", None)
            operator_name = " ".join([x for x in [operator_first, operator_last] if x]) or operator_email
            audit_entry = {
                "user_id": str(g.user_id) if getattr(g, "user_id", None) else None,
                "operator_email": operator_email,
                "operator_name": operator_name,
                "timestamp_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "source_method": source_method,
            }
            history = list(extra_data.get("inventory_audit_history") or [])
            history.append(audit_entry)
            extra_data["inventory_audit_history"] = history
            if data.get("untracked"):
                notes = (extra_data.get("notes") or data.get("notes") or "").strip()
                if not notes:
                    return jsonify({"error": "notes are required when adding an untracked item"}), 400
                extra_data["notes"] = notes
                # Invariant: untracked items must always have remaining_balance_to_reconcile for reduce_only logic.
                extra_data["untracked"] = True  # Flag for reconciliation/sourcemap banners
                try:
                    qty_val = float(quantity) if quantity is not None else 0
                    extra_data["remaining_balance_to_reconcile"] = str(qty_val) if qty_val > 0 else "0"
                except (TypeError, ValueError):
                    extra_data["remaining_balance_to_reconcile"] = str(quantity) if quantity else "0"

            try:
                item = repo.create_inventory_item(
                    org_id=org_id,
                    name=name,
                    quantity=str(quantity),
                    unit=unit,
                    inventory_type=inventory_type,
                    supplier=supplier,
                    barcode=barcode,
                    purchase_date=purchase_date,
                    supplier_batch_number=data.get("supplier_batch_number"),
                    expiry_date=expiry_date,
                    source_execution_id=source_execution_id,
                    source_execution_step_id=source_execution_step_id,
                    source_output_id=source_output_id,
                    extra_data=extra_data if extra_data else None,
                    site_id=getattr(g, "validated_site_id", None),
                )
            except IntegrityError:
                db_session.rollback()
                return jsonify(
                    {"error": "Duplicate barcode for this organisation; try again or add quantity to existing item."}
                ), 409

            return (
                jsonify(
                    {
                        "id": str(item.id),
                        "name": item.name,
                        "quantity": quantity_to_api_str(item.quantity),
                        "unit": item.unit,
                        "inventory_type": item.inventory_type,
                        "supplier": item.supplier,
                        "purchase_date": item.purchase_date.isoformat() if item.purchase_date else None,
                        "supplier_batch_number": item.supplier_batch_number,
                        "expiry_date": item.expiry_date.isoformat() if item.expiry_date else None,
                        "created_at": item.created_at.isoformat() if item.created_at else None,
                    }
                ),
                201,
            )
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except Exception:
            # Log the full error for debugging but return generic message to client
            logger.exception("Error creating inventory item")
            return jsonify({"error": "Failed to create inventory item"}), 500

    @bp.route("/api/core/inventory/<item_id>", methods=["PUT"])
    @requires_auth
    def update_inventory_item(item_id):
        """Update an existing inventory item"""
        org_id = UUID(g.org_id)
        data = request.get_json()

        name = data.get("name")
        quantity = data.get("quantity")
        unit = data.get("unit")
        inventory_type = data.get("inventory_type", InventoryType.RAW_MATERIAL.value)

        if not all([name, quantity, unit]):
            return jsonify({"error": "name, quantity, and unit are required"}), 400

        repo = InventoryRepository(db_session)
        try:
            # Parse purchase date if provided
            purchase_date = None
            if data.get("purchase_date"):
                purchase_date = datetime.fromisoformat(data.get("purchase_date").replace("Z", "+00:00")).date()

            expiry_date = None
            if data.get("expiry_date"):
                expiry_date = datetime.fromisoformat(data.get("expiry_date").replace("Z", "+00:00")).date()

            # Get existing item
            item = repo.get_inventory_item_by_id(UUID(item_id), org_id)
            if not item:
                return jsonify({"error": "Inventory item not found"}), 404

            # Snapshot before mutation for diff
            before = {
                "name": item.name,
                "inventory_type": item.inventory_type,
                "quantity": quantity_to_api_str(item.quantity),
                "unit": item.unit,
                "supplier": item.supplier,
                "supplier_batch_number": item.supplier_batch_number,
                "purchase_date": item.purchase_date.isoformat() if item.purchase_date else None,
                "expiry_date": item.expiry_date.isoformat() if item.expiry_date else None,
                "barcode": item.barcode,
            }

            # Apply updates
            item.name = name
            with allow_inventory_quantity_write(InventoryQuantityWriteReason.MANUAL_API_UPDATE):
                item.quantity = coerce_stored_quantity(quantity)
                # Flush the quantity change while the write reason is still active. The guard
                # (inventory_quantity_guard._before_flush) authorizes quantity writes at FLUSH
                # time, not at assignment time. Without this flush the change stays pending and
                # is first written during EventWriter.emit() below — outside this context —
                # where the guard rejects it and every quantity-changing edit 500s.
                db_session.flush()
            item.unit = unit
            item.inventory_type = inventory_type
            item.supplier = data.get("supplier")
            item.purchase_date = purchase_date
            item.supplier_batch_number = data.get("supplier_batch_number")
            item.expiry_date = expiry_date
            item.barcode = data.get("barcode") or None
            if data.get("metadata"):
                item.extra_data = data.get("metadata")

            after = {
                "name": item.name,
                "inventory_type": item.inventory_type,
                "quantity": quantity_to_api_str(item.quantity),
                "unit": item.unit,
                "supplier": item.supplier,
                "supplier_batch_number": item.supplier_batch_number,
                "purchase_date": item.purchase_date.isoformat() if item.purchase_date else None,
                "expiry_date": item.expiry_date.isoformat() if item.expiry_date else None,
                "barcode": item.barcode,
            }

            diff = {k: {"before": before[k], "after": after[k]} for k in before if before[k] != after[k]}

            ew = EventWriter(db_session, org_id)
            ew.emit(
                event_type="inventory_item.updated",
                entity_type="inventory_item",
                entity_id=item.id,
                payload={**after, "reason": "manual_edit"},
                diff=diff if diff else None,
            )

            db_session.commit()
            db_session.refresh(item)

            return (
                jsonify(
                    {
                        "id": str(item.id),
                        "name": item.name,
                        "quantity": quantity_to_api_str(item.quantity),
                        "unit": item.unit,
                        "inventory_type": item.inventory_type,
                        "supplier": item.supplier,
                        "purchase_date": item.purchase_date.isoformat() if item.purchase_date else None,
                        "supplier_batch_number": item.supplier_batch_number,
                        "expiry_date": item.expiry_date.isoformat() if item.expiry_date else None,
                        "created_at": item.created_at.isoformat() if item.created_at else None,
                    }
                ),
                200,
            )
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except Exception:
            logger.exception("Error updating inventory item")
            return jsonify({"error": "Failed to update inventory item"}), 500

    @bp.route("/api/core/inventory/<item_id>/adjust", methods=["POST"])
    @requires_auth
    def adjust_inventory_item_quantity(item_id):
        """Manually correct an inventory item's quantity (absolute value).

        Emits inventory_item.quantity_adjusted so the change is fully traceable.
        """
        org_id = UUID(g.org_id)
        data = request.get_json() or {}
        raw = data.get("new_quantity")
        if raw is None or str(raw).strip() == "":
            return jsonify({"error": "new_quantity is required"}), 400
        try:
            float(str(raw).strip())
        except (TypeError, ValueError):
            return jsonify({"error": "new_quantity must be a valid number"}), 400

        repo = InventoryRepository(db_session)
        try:
            item = repo.set_inventory_item_quantity(UUID(item_id), org_id, str(raw).strip())
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        if not item:
            return jsonify({"error": "Inventory item not found"}), 404
        return jsonify(
            {
                "id": str(item.id),
                "quantity": quantity_to_api_str(item.quantity),
                "unit": item.unit,
            }
        ), 200

    @bp.route("/api/core/inventory/consume-fifo", methods=["POST"])
    @requires_auth
    def consume_final_product_fifo():
        """Consume finished stock FIFO from the default or explicit shipping site."""
        org_id = UUID(g.org_id)
        data = request.get_json() or {}
        name = (data.get("name") or "").strip()
        quantity = data.get("quantity")
        reference = data.get("reference")
        if not name:
            return jsonify({"error": "name is required"}), 400
        if quantity is None or str(quantity).strip() == "":
            return jsonify({"error": "quantity is required"}), 400

        repo = InventoryRepository(db_session)
        try:
            consumed = repo.consume_final_product_fifo(
                org_id, name, str(quantity).strip(), reference=reference, site_id=getattr(g, "validated_site_id", None)
            )
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        return jsonify({"name": name, "consumed": consumed}), 200

    @bp.route("/api/core/inventory/<item_id>", methods=["DELETE"])
    @requires_auth
    def delete_inventory_item(item_id):
        """Delete an inventory item"""
        org_id = UUID(g.org_id)
        repo = InventoryRepository(db_session)

        try:
            success = repo.delete_inventory_item(UUID(item_id), org_id)
            if not success:
                return jsonify({"error": "Inventory item not found"}), 404

            return jsonify({"message": "Inventory item deleted successfully"}), 200
        except Exception:
            logger.exception("Error deleting inventory item")
            return jsonify({"error": "Failed to delete inventory item"}), 500
