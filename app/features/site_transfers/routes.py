"""Tenant-scoped transfer API and screen; policy integration is fail-closed."""

from uuid import UUID

from flask import Blueprint, g, jsonify, render_template, request
from sqlalchemy.exc import IntegrityError

from app.core.db import db_session
from app.core.db.models.inventory_item import InventoryItem
from app.core.db.models.organisation import Organisation
from app.core.db.models.site import Site
from app.core.db.models.site_transfer import SiteStockReceipt, SiteStockTransfer
from app.core.db.models.stock_location import StockLocation
from app.core.security.access_policy import has_permission
from app.core.security.permissions import requires_auth
from app.features.site_transfers import service

site_transfers_bp = Blueprint(
    "site_transfers",
    __name__,
    template_folder="frontend/templates",
    static_folder="frontend/static",
    static_url_path="/static/site-transfers",
)


def _org():
    return UUID(g.org_id)


def _policy(session, org_id, context):
    try:
        from app.features.compliant.platform.stock_movements import evaluate_stock_movement
    except ImportError:
        raise service.TransferError("Stock movement policies have not been installed yet") from None
    return evaluate_stock_movement(session, org_id, context)


def _requirements():
    try:
        from app.features.compliant.platform.stock_movements import movement_requirements
    except ImportError:
        return {"fields": [], "blocked": True, "authority_permission": None}
    return movement_requirements(db_session, _org())


def _authority():
    requirements = _requirements()
    permission = requirements.get("authority_permission")
    if requirements.get("blocked") or (permission and not has_permission(g.current_user, permission)):
        raise service.TransferError("Movement authority requires a permitted compliance operator")


@site_transfers_bp.errorhandler(ValueError)
def invalid(error):
    db_session.rollback()
    return jsonify({"error": str(error)}), 400


@site_transfers_bp.errorhandler(IntegrityError)
def conflict(_error):
    db_session.rollback()
    return jsonify({"error": "Transfer facts conflict with an existing record"}), 409


@site_transfers_bp.route("/core/site-transfers")
@requires_auth
def page():
    return render_template("site_transfers/transfers.html", active_page="core")


@site_transfers_bp.route("/api/core/site-transfers", methods=["GET"])
@requires_auth
def list_transfers():
    rows = (
        db_session.query(SiteStockTransfer)
        .filter(SiteStockTransfer.org_id == _org())
        .order_by(SiteStockTransfer.created_at.desc(), SiteStockTransfer.id)
        .limit(200)
        .all()
    )
    org = db_session.query(Organisation).filter(Organisation.id == _org()).one()
    return jsonify(
        {
            "operations_available": bool(org.multiple_sites_enabled and org.multiple_site_operations_enabled),
            "transfers": [service.serialise_transfer(row) for row in rows],
        }
    )


@site_transfers_bp.route("/api/core/site-transfers/options", methods=["GET"])
@requires_auth
def options():
    requirements = _requirements()
    permission = requirements.get("authority_permission")
    requirements["can_authorise"] = not requirements.get("blocked") and (
        not permission or has_permission(g.current_user, permission)
    )
    org = db_session.query(Organisation).filter(Organisation.id == _org()).one()
    if not org.multiple_sites_enabled:
        return jsonify({"sites": [], "locations": [], "stock": [], "requirements": requirements})
    sites = db_session.query(Site).filter(Site.org_id == _org(), Site.is_active.is_(True)).order_by(Site.name).all()
    locations = (
        db_session.query(StockLocation)
        .filter(StockLocation.org_id == _org(), StockLocation.is_active.is_(True))
        .order_by(StockLocation.name)
        .all()
    )
    stock = (
        db_session.query(InventoryItem)
        .filter(InventoryItem.org_id == _org(), InventoryItem.quantity > 0)
        .order_by(InventoryItem.name, InventoryItem.id)
        .limit(1000)
        .all()
    )
    return jsonify(
        {
            "requirements": requirements,
            "sites": [{"id": str(row.id), "name": row.name} for row in sites],
            "locations": [{"id": str(row.id), "site_id": str(row.site_id), "name": row.name} for row in locations],
            "stock": [
                {
                    "id": str(row.id),
                    "site_id": str(row.site_id),
                    "location_id": str(row.location_id) if row.location_id else None,
                    "name": row.name,
                    "quantity": str(row.quantity),
                    "unit": row.unit,
                    "batch": row.supplier_batch_number,
                    "barcode": row.barcode or (row.extra_data or {}).get("original_barcode"),
                }
                for row in stock
                if getattr(row, "contract_customer_id", None) is None
                and not (row.extra_data or {}).get("contract_customer_id")
            ],
        }
    )


@site_transfers_bp.route("/api/core/site-transfers", methods=["POST"])
@requires_auth
def dispatch():
    _authority()
    transfer, replay = service.dispatch(
        db_session,
        _org(),
        g.current_user.id,
        request.headers.get("Idempotency-Key"),
        request.get_json(silent=True),
        _policy,
    )
    db_session.commit()
    return jsonify(
        {"transfer": service.serialise_transfer(transfer), "idempotent_replay": replay}
    ), 200 if replay else 201


@site_transfers_bp.route("/api/core/site-transfers/<transfer_id>", methods=["GET"])
@requires_auth
def detail(transfer_id):
    transfer = service.get_transfer(db_session, _org(), transfer_id)
    if transfer is None:
        return jsonify({"error": "Transfer not found"}), 404
    receipts = (
        db_session.query(SiteStockReceipt)
        .filter(SiteStockReceipt.org_id == _org(), SiteStockReceipt.transfer_id == transfer.id)
        .order_by(SiteStockReceipt.created_at, SiteStockReceipt.id)
        .all()
    )
    fragments = (
        {
            row.transfer_receipt_id: row
            for row in db_session.query(InventoryItem)
            .filter(InventoryItem.org_id == _org(), InventoryItem.transfer_receipt_id.in_([row.id for row in receipts]))
            .all()
        }
        if receipts
        else {}
    )
    return jsonify(
        {
            "transfer": service.serialise_transfer(transfer),
            "receipts": [
                {
                    "id": str(row.id),
                    "quantity": str(row.quantity),
                    "damaged_quantity": str(row.damaged_quantity),
                    "short_quantity": str(row.short_quantity),
                    "loss_reason": row.loss_reason,
                    "occurred_on": row.occurred_on.isoformat(),
                    "stock_item_id": str(fragments[row.id].id) if row.id in fragments else None,
                }
                for row in receipts
            ],
        }
    )


@site_transfers_bp.route("/api/core/site-transfers/<transfer_id>/receipts", methods=["POST"])
@requires_auth
def receive(transfer_id):
    if service.get_transfer(db_session, _org(), transfer_id) is None:
        return jsonify({"error": "Transfer not found"}), 404
    receipt, replay = service.receive(
        db_session,
        _org(),
        g.current_user.id,
        transfer_id,
        request.headers.get("Idempotency-Key"),
        request.get_json(silent=True),
        _policy,
    )
    db_session.commit()
    return jsonify({"receipt_id": str(receipt.id), "idempotent_replay": replay}), 200 if replay else 201


@site_transfers_bp.route("/core/site-transfers/<transfer_id>/docket", methods=["GET"])
@requires_auth
def docket(transfer_id):
    transfer = service.get_transfer(db_session, _org(), transfer_id)
    if transfer is None:
        return jsonify({"error": "Transfer not found"}), 404
    # Project bounded, generic evidence fields; never render the raw policy payload.
    evidence = []
    for key, label in (
        ("source_licence", "Source licence"),
        ("destination_licence", "Destination licence"),
        ("authority", "Movement authority"),
    ):
        record = transfer.decision_snapshot.get(key)
        if isinstance(record, dict):
            fields = [
                (name.replace("_", " ").capitalize(), value)
                for name, value in record.items()
                if name
                in {
                    "number",
                    "kind",
                    "legal_entity_reference",
                    "evidence_reference",
                    "valid_from",
                    "valid_until",
                    "authority",
                    "reference",
                    "approved_on",
                }
                and isinstance(value, str)
            ]
            if fields:
                evidence.append((label, fields))
    return render_template(
        "site_transfers/docket.html", transfer=transfer, state=service.serialise_transfer(transfer), evidence=evidence
    )
