"""
API routes for untracked inventory reconciliation (Path A and Path B).

Register with: reconciliation_routes.register_routes(core_bp)
"""

from __future__ import annotations

from uuid import UUID

from flask import g, jsonify, request
from pydantic import AliasChoices, Field

from app.core.db import db_session
from app.core.db.models.inventory_item import InventoryType
from app.core.security.permissions import requires_auth
from app.features.inventory.inventory_payloads import (
    InventoryDate,
    LotName,
    LotText,
    LotUnit,
    OptionalId,
    PositiveQuantity,
)
from app.features.reconciliation.service import (
    get_matching_untracked,
    reconcile_via_addition,
    reconcile_via_execution,
)
from app.observability import get_logger
from app.utils.request_validation import InvalidInputError, JsonInput, read_json

logger = get_logger(__name__)


class ReconcileAdditionInput(JsonInput):
    name: LotName
    quantity: PositiveQuantity
    unit: LotUnit
    inventory_type: InventoryType = InventoryType.RAW_MATERIAL
    untracked_item_id: OptionalId = None
    purchase_date: InventoryDate = None
    supplier: LotText | None = None
    supplier_batch_number: LotText | None = None
    expiry_date: InventoryDate = None


class ReconcileExecutionInput(JsonInput):
    untracked_item_id: UUID
    process_id: UUID
    step_id: UUID
    output_name: LotName = Field(validation_alias=AliasChoices("output_name", "name"))
    output_quantity: PositiveQuantity = Field(validation_alias=AliasChoices("output_quantity", "quantity"))
    output_unit: LotUnit = Field(validation_alias=AliasChoices("output_unit", "unit"))
    output_date: InventoryDate = None


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
        try:
            data = read_json(ReconcileAdditionInput)
        except InvalidInputError as exc:
            return exc.response()
        fields = data.model_dump(mode="json")

        session = db_session()
        try:
            result = reconcile_via_addition(
                org_id=org_id,
                session=session,
                user_id=user_id,
                user_email=user_email,
                name=data.name,
                quantity=data.quantity,
                unit=data.unit,
                inventory_type=data.inventory_type.value,
                untracked_item_id=data.untracked_item_id or None,
                purchase_date=fields["purchase_date"],
                supplier=data.supplier,
                supplier_batch_number=data.supplier_batch_number,
                expiry_date=fields["expiry_date"],
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
        try:
            data = read_json(ReconcileExecutionInput)
        except InvalidInputError as exc:
            return exc.response()
        fields = data.model_dump(mode="json")

        session = db_session()
        try:
            result = reconcile_via_execution(
                org_id=org_id,
                session=session,
                user_id=user_id,
                user_email=user_email,
                untracked_item_id=data.untracked_item_id,
                process_id=data.process_id,
                step_id=data.step_id,
                output_name=data.output_name,
                output_quantity=data.output_quantity,
                output_unit=data.output_unit,
                output_date=fields["output_date"],
            )
        finally:
            session.close()

        if "error" in result:
            return jsonify({"error": result["error"]}), 400
        return jsonify(result), 201
