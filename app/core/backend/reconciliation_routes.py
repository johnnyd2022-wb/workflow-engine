"""
API routes for untracked inventory reconciliation (Path A and Path B).

Register with: reconciliation_routes.register_routes(core_bp)
"""

from __future__ import annotations

from uuid import UUID

from flask import g, jsonify, request

from app.core.backend.reconciliation_service import (
    get_matching_untracked,
    reconcile_via_addition,
    reconcile_via_execution,
)
from app.core.db import db_session
from app.core.security.permissions import requires_auth


def register_routes(bp):
    """Register reconciliation routes on the given blueprint."""

    @bp.route("/api/core/inventory/reconcile/matching-untracked", methods=["GET"])
    @requires_auth
    def get_matching_untracked_for_add():
        """Return untracked items matching query params name and unit (and optional process_id, execution_id)."""
        org_id = UUID(g.org_id)
        name = (request.args.get("name") or "").strip()
        unit = (request.args.get("unit") or "").strip()
        process_id_str = request.args.get("process_id")
        process_id = None
        if process_id_str:
            try:
                process_id = UUID(process_id_str)
            except ValueError:
                return jsonify({"error": "Invalid process_id"}), 400
        execution_id_str = request.args.get("execution_id")
        execution_id = None
        if execution_id_str:
            try:
                execution_id = UUID(execution_id_str)
            except ValueError:
                pass
        if not name or not unit:
            return jsonify({"matching_untracked": []}), 200
        session = db_session()
        try:
            items = get_matching_untracked(org_id, session, name, unit, process_id, execution_id)
            return jsonify({"matching_untracked": items}), 200
        finally:
            session.close()

    @bp.route("/api/core/inventory/reconcile/via-addition", methods=["POST"])
    @requires_auth
    def reconcile_via_addition_route():
        """Path A: Add to inventory with optional mapping to an untracked item."""
        org_id = UUID(g.org_id)
        user_id = getattr(g, "user_id", None)
        user_email = getattr(g, "user_email", None)
        if user_id is not None:
            user_id = str(user_id)
        data = request.get_json() or {}
        name = (data.get("name") or "").strip()
        quantity = data.get("quantity")
        unit = (data.get("unit") or "").strip()
        inventory_type = (data.get("inventory_type") or "raw_material").strip()
        untracked_item_id_str = data.get("untracked_item_id")
        untracked_item_id = None
        if untracked_item_id_str:
            try:
                untracked_item_id = UUID(untracked_item_id_str)
            except ValueError:
                return jsonify({"error": "Invalid untracked_item_id"}), 400
        if not name:
            return jsonify({"error": "name is required"}), 400
        if quantity is None:
            return jsonify({"error": "quantity is required"}), 400
        if not unit:
            return jsonify({"error": "unit is required"}), 400

        session = db_session()
        try:
            result = reconcile_via_addition(
                org_id=org_id,
                session=session,
                user_id=user_id,
                user_email=user_email,
                name=name,
                quantity=quantity,
                unit=unit,
                inventory_type=inventory_type,
                untracked_item_id=untracked_item_id,
                purchase_date=data.get("purchase_date"),
                supplier=data.get("supplier"),
                supplier_batch_number=data.get("supplier_batch_number"),
                expiry_date=data.get("expiry_date"),
            )
        finally:
            session.close()

        if "error" in result:
            return jsonify({"error": result["error"]}), 400
        return jsonify(result), 201

    @bp.route("/api/core/inventory/reconcile/via-execution", methods=["POST"])
    @requires_auth
    def reconcile_via_execution_route():
        """Path B: Map untracked item to an execution output (creates execution and inventory)."""
        org_id = UUID(g.org_id)
        user_id = getattr(g, "user_id", None)
        user_email = getattr(g, "user_email", None)
        if user_id is not None:
            user_id = str(user_id)
        data = request.get_json() or {}
        untracked_item_id_str = data.get("untracked_item_id")
        process_id_str = data.get("process_id")
        step_id_str = data.get("step_id")
        output_name = (data.get("output_name") or data.get("name") or "").strip()
        output_quantity = data.get("output_quantity") or data.get("quantity")
        output_unit = (data.get("output_unit") or data.get("unit") or "").strip()

        if not untracked_item_id_str:
            return jsonify({"error": "untracked_item_id is required"}), 400
        if not process_id_str:
            return jsonify({"error": "process_id is required"}), 400
        if not step_id_str:
            return jsonify({"error": "step_id is required"}), 400
        if not output_name:
            return jsonify({"error": "output_name (or name) is required"}), 400
        if output_quantity is None:
            return jsonify({"error": "output_quantity (or quantity) is required"}), 400
        if not output_unit:
            return jsonify({"error": "output_unit (or unit) is required"}), 400

        try:
            untracked_item_id = UUID(untracked_item_id_str)
            process_id = UUID(process_id_str)
            step_id = UUID(step_id_str)
        except ValueError as e:
            return jsonify({"error": f"Invalid UUID: {e}"}), 400

        session = db_session()
        try:
            result = reconcile_via_execution(
                org_id=org_id,
                session=session,
                user_id=user_id,
                user_email=user_email,
                untracked_item_id=untracked_item_id,
                process_id=process_id,
                step_id=step_id,
                output_name=output_name,
                output_quantity=output_quantity,
                output_unit=output_unit,
                output_date=data.get("output_date"),
            )
        finally:
            session.close()

        if "error" in result:
            return jsonify({"error": result["error"]}), 400
        return jsonify(result), 201
