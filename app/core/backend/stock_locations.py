"""Stock locations and moves between them (plan 2.1).

Customs taxes alcohol when it leaves the licensed (Customs-controlled) area, so stock
needs a place. Lots with no location are in the main licensed area. Moving part of a lot
creates a new lot at the destination with the same batch and lineage; moving it out of
the licensed area is an excise removal on the move date.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from flask import Blueprint, g, jsonify, request

from app.core.db import db_session
from app.core.db.models.stock_location import StockLocation
from app.core.db.repositories.inventory_repo import InventoryRepository
from app.core.security.permissions import requires_auth
from app.core.utils.log_action import log_action

stock_locations_bp = Blueprint("stock_locations", __name__)


def _org_id() -> UUID:
    return UUID(g.org_id)


def _serialise(loc: StockLocation) -> dict:
    return {
        "id": str(loc.id),
        "name": loc.name,
        "inside_licensed_area": bool(loc.inside_licensed_area),
        "is_active": bool(loc.is_active),
    }


@stock_locations_bp.route("/api/core/stock-locations", methods=["GET"])
@requires_auth
def list_locations():
    rows = (
        db_session.query(StockLocation)
        .filter(StockLocation.org_id == _org_id())
        .order_by(StockLocation.name.asc())
        .all()
    )
    return jsonify(
        {
            "locations": [_serialise(r) for r in rows],
            "default": {"id": None, "name": "Licensed area (main)", "inside_licensed_area": True},
        }
    ), 200


@stock_locations_bp.route("/api/core/stock-locations", methods=["POST"])
@requires_auth
def create_location():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name") or "").strip()
    if not name or len(name) > 120:
        return jsonify({"error": "name is required (up to 120 characters)"}), 400
    exists = (
        db_session.query(StockLocation).filter(StockLocation.org_id == _org_id(), StockLocation.name == name).first()
    )
    if exists:
        return jsonify({"error": "A location with that name already exists"}), 409
    loc = StockLocation(org_id=_org_id(), name=name, inside_licensed_area=bool(data.get("inside_licensed_area")))
    db_session.add(loc)
    db_session.commit()
    log_action("create", "stock_location", loc.id, {"name": name, "inside_licensed_area": loc.inside_licensed_area})
    return jsonify(_serialise(loc)), 201


@stock_locations_bp.route("/api/core/inventory/<item_id>/move", methods=["POST"])
@requires_auth
def move_stock(item_id: str):
    data = request.get_json(silent=True) or {}
    try:
        item_uuid = UUID(item_id)
        to_location = UUID(str(data["to_location_id"])) if data.get("to_location_id") else None
        occurred = date.fromisoformat(str(data.get("occurred_on") or date.today().isoformat()))
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid item, location or date"}), 400
    try:
        new_item, transfer = InventoryRepository(db_session).move_lot(
            _org_id(),
            item_uuid,
            data.get("quantity"),
            to_location,
            occurred,
            data.get("note"),
            user_id=g.current_user.id,
            commit=False,
        )
        db_session.commit()
    except ValueError as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 400
    log_action(
        "move",
        "inventory_item",
        item_uuid,
        {"to_item_id": str(new_item.id), "quantity": str(transfer.quantity), "direction": transfer.direction},
    )
    return jsonify(
        {
            "moved_item_id": str(new_item.id),
            "direction": transfer.direction,
            "excise_removal": transfer.direction == "out",
        }
    ), 201
