"""Staff-only free-issue receipts and raw stock; owner is a validated customer path."""

from uuid import UUID

from flask import g, jsonify, render_template, request

from app.core.db import db_session
from app.core.db.models.organisation import Organisation
from app.core.security.permissions import requires_auth
from app.features.contract_manufacturing.routes.orders import bp, handled
from app.features.contract_manufacturing.services.material_receipts import (
    customer_materials,
    material_dto,
    receive_material,
)
from app.features.contract_manufacturing.services.orders import ContractOrderService


@bp.get("/api/core/contract-customers/<uuid:customer_id>/materials")
@requires_auth
@handled
def list_materials(customer_id):
    return jsonify(
        {"materials": [material_dto(item) for item in customer_materials(db_session(), UUID(g.org_id), customer_id)]}
    )


@bp.post("/api/core/contract-customers/<uuid:customer_id>/material-receipts")
@requires_auth
@handled
def receive_customer_material(customer_id):
    receipt, replay = receive_material(
        db_session(),
        UUID(g.org_id),
        customer_id,
        g.current_user.id,
        request.headers.get("Idempotency-Key"),
        request.get_json(silent=True),
    )
    db_session.commit()
    return jsonify(
        {
            "receipt_id": str(receipt.id),
            "inventory_item_id": str(receipt.inventory_item_id),
            "quantity_received": str(receipt.quantity),
            "unit": receipt.unit,
            "idempotent_replay": replay,
        }
    ), 200 if replay else 201


@bp.get("/core/contracts/materials")
@requires_auth
@handled
def materials_page():
    org_id = UUID(g.org_id)
    customers = ContractOrderService(db_session(), org_id).customers()
    enabled = db_session.query(Organisation.contract_materials_enabled).filter(Organisation.id == org_id).scalar()
    return render_template(
        "contracts/materials.html", active_page="contracts", customers=customers, materials_enabled=enabled
    )


def install_material_request_guard(app):
    @app.before_request
    def prevent_generic_title_fields():
        if request.method not in {"POST", "PUT", "PATCH"}:
            return None
        if request.endpoint not in {
            "core.create_inventory_item",
            "core.update_inventory_item",
            "core.adjust_inventory_item_quantity",
            "go_live.create_opening_stock",
        }:
            return None
        data = request.get_json(silent=True)
        if isinstance(data, dict):
            extra = data.get("extra_data")
            if set(data) & {
                "contract_customer_id",
                "material_receipt_id",
                "transfer_receipt_id",
                "owner_id",
                "owner",
                "customer_id",
            } or (isinstance(extra, dict) and "contract_customer_id" in extra):
                return jsonify(
                    {
                        "error": "Customer raw title requires a recorded material receipt",
                        "code": "recorded_material_receipt_required",
                    }
                ), 400
        return None
