"""GL-P02: quality hold and release on a lot.

Anyone who can adjust stock can hold a lot (holding is the safe direction). Releasing it
back into use needs ``compliance.manage``: an authorised person signs it off with a note.
"""

from __future__ import annotations

from uuid import UUID

from flask import Blueprint, g, jsonify
from pydantic import Field

from app.core.db import db_session
from app.core.db.models.inventory_item import InventoryItem
from app.core.db.models.lot_hold import LotHold
from app.core.security.permissions import requires_auth, requires_org_scope
from app.core.services import lot_holds
from app.core.utils.log_action import log_action
from app.utils.request_validation import InvalidInputError, JsonInput, read_json

lot_holds_bp = Blueprint("lot_holds", __name__)


def _uuid(value):
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


class HoldInput(JsonInput):
    reason: str = Field(max_length=lot_holds.MAX_REASON, pattern=r"^[^\x00]*$")
    also_hold: list[UUID] | None = Field(default=None, max_length=500)


class ReleaseInput(JsonInput):
    note: str = Field(max_length=lot_holds.MAX_REASON, pattern=r"^[^\x00]*$")


@lot_holds_bp.errorhandler(InvalidInputError)
def invalid_input(error):
    db_session().rollback()
    return error.response()


@lot_holds_bp.get("/api/core/inventory/<item_id>/holds")
@requires_auth
@requires_org_scope
def get_lot_holds(item_id):
    item_uuid = _uuid(item_id)
    if item_uuid is None:
        return jsonify({"error": "Lot not found"}), 404
    session = db_session()
    org_id = g.current_org_id
    try:
        past = lot_holds.history(session, org_id, item_uuid)
        made_from = lot_holds.made_from(session, org_id, item_uuid)
    except LookupError:
        return jsonify({"error": "Lot not found"}), 404
    current = next((h for h in past if h.released_at is None), None)
    return jsonify(
        {
            "open": lot_holds.serialise(current) if current else None,
            "history": [lot_holds.serialise(h) for h in past],
            "made_from": made_from,
        }
    )


@lot_holds_bp.post("/api/core/inventory/<item_id>/holds")
@requires_auth
@requires_org_scope
def place_lot_hold(item_id):
    item_uuid = _uuid(item_id)
    if item_uuid is None:
        return jsonify({"error": "Lot not found"}), 404
    data = read_json(HoldInput)
    session = db_session()
    org_id = g.current_org_id
    try:
        holds = lot_holds.place_hold(session, org_id, item_uuid, data.reason, g.current_user.id, data.also_hold or [])
        session.commit()
    except LookupError:
        session.rollback()
        return jsonify({"error": "Lot not found"}), 404
    except lot_holds.LotHoldError as exc:
        session.rollback()
        return jsonify({"error": str(exc)}), 400
    log_action(
        "lot_hold_placed",
        "inventory_item",
        item_uuid,
        {"hold_ids": [str(h.id) for h in holds], "lots": len(holds)},
        org_id,
        g.current_user.id,
    )
    return jsonify({"holds": [lot_holds.serialise(h) for h in holds]}), 201


@lot_holds_bp.post("/api/core/holds/<hold_id>/release")
@requires_auth
@requires_org_scope
def release_lot_hold(hold_id):
    hold_uuid = _uuid(hold_id)
    if hold_uuid is None:
        return jsonify({"error": "Hold not found"}), 404
    session = db_session()
    org_id = g.current_org_id
    try:
        hold = lot_holds.release_hold(session, org_id, hold_uuid, read_json(ReleaseInput).note, g.current_user.id)
        session.commit()
    except LookupError:
        session.rollback()
        return jsonify({"error": "Hold not found"}), 404
    except lot_holds.LotHoldError as exc:
        session.rollback()
        return jsonify({"error": str(exc)}), 400
    log_action("lot_hold_released", "inventory_item", hold.inventory_item_id, {"hold_id": str(hold.id)})
    return jsonify({"hold": lot_holds.serialise(hold)})


@lot_holds_bp.get("/api/core/holds")
@requires_auth
@requires_org_scope
def list_open_holds():
    """Every lot on hold now, with its name and quantity: the quality board."""
    session = db_session()
    org_id = g.current_org_id
    query = (
        session.query(LotHold, InventoryItem)
        .join(InventoryItem, (InventoryItem.id == LotHold.inventory_item_id) & (InventoryItem.org_id == LotHold.org_id))
        .filter(LotHold.org_id == org_id, LotHold.released_at.is_(None))
    )
    rows = query.order_by(LotHold.placed_at.desc()).limit(1000)
    return jsonify(
        {
            "total_count": query.count(),
            "holds": [
                {
                    **lot_holds.serialise(hold),
                    "lot": {
                        "name": item.display_label or item.name,
                        "quantity": str(item.quantity),
                        "unit": item.unit,
                    },
                }
                for hold, item in rows
            ],
        }
    )


@lot_holds_bp.app_errorhandler(lot_holds.LotOnHoldError)
def lot_on_hold(error):
    """Any route whose flush hit a held lot: nothing was taken; say which lot and why."""
    db_session().rollback()
    return jsonify({"error": str(error), "code": "lot_on_hold"}), 409
