"""Stock locations and moves between them (plan 2.1).

Customs taxes alcohol when it leaves the licensed (Customs-controlled) area, so stock
needs a place. Lots with no location are in the main licensed area. Moving part of a lot
creates a new lot at the destination with the same batch and lineage; moving it out of
the licensed area is an excise removal on the move date.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from flask import Blueprint, g, jsonify
from pydantic import Field, StringConstraints
from sqlalchemy.exc import IntegrityError

from app.core.db import db_session
from app.core.db.models.stock_location import StockLocation
from app.core.db.repositories.inventory_repo import InventoryRepository
from app.core.security.permissions import requires_auth
from app.core.utils.log_action import log_action
from app.utils.request_validation import CleanName, InvalidInputError, JsonInput, read_json

stock_locations_bp = Blueprint("stock_locations", __name__)


class CreateLocationInput(JsonInput):
    name: Annotated[CleanName, StringConstraints(max_length=120)]
    inside_licensed_area: bool = False
    site_id: UUID | None = None


class MoveStockInput(JsonInput):
    quantity: Annotated[Decimal, Field(gt=0, max_digits=18, decimal_places=4)]
    to_location_id: UUID | Literal[""] | None = None
    occurred_on: date | Literal[""] | None = None
    note: Annotated[str, StringConstraints(max_length=500, pattern=r"^[^\x00]*$")] | None = None


def _org_id() -> UUID:
    return UUID(g.org_id)


def _serialise(loc: StockLocation) -> dict:
    return {
        "id": str(loc.id),
        "name": loc.name,
        "inside_licensed_area": bool(loc.inside_licensed_area),
        "is_active": bool(loc.is_active),
        "site_id": str(loc.site_id) if loc.site_id else None,
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
    try:
        data = read_json(CreateLocationInput)
    except InvalidInputError as exc:
        return exc.response()
    name = data.name
    loc = StockLocation(
        org_id=_org_id(),
        name=name,
        inside_licensed_area=data.inside_licensed_area,
        site_id=getattr(g, "validated_site_id", None),
    )
    db_session.add(loc)
    # The site guard fills in the default site on flush; the name is unique within that site.
    try:
        db_session.flush()
    except IntegrityError:
        db_session.rollback()
        return jsonify({"error": "This site already has an area with that name"}), 409
    db_session.commit()
    log_action("create", "stock_location", loc.id, {"name": name, "inside_licensed_area": loc.inside_licensed_area})
    return jsonify(_serialise(loc)), 201


@stock_locations_bp.route("/api/core/inventory/<item_id>/move", methods=["POST"])
@requires_auth
def move_stock(item_id: str):
    try:
        item_uuid = UUID(item_id)
    except ValueError:
        return InvalidInputError({"item_id": "Enter a valid item ID."}).response()
    try:
        data = read_json(MoveStockInput)
    except InvalidInputError as exc:
        return exc.response()
    try:
        new_item, transfer = InventoryRepository(db_session).move_lot(
            _org_id(),
            item_uuid,
            data.quantity,
            data.to_location_id or None,
            data.occurred_on or date.today(),
            data.note,
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
