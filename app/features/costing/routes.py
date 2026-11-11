"""Costing API (live-cogs 8.1a): lot cost, batch cost, manual / free prices, settings.

Permissions come from ``access_policy.POLICY`` (``costing.*``: GET needs ``costs.view``,
everything else ``costs.manage``), enforced app-wide before this blueprint runs. Every route
also 404s unless the org holds the ``costing`` feature.
"""

from __future__ import annotations

from uuid import UUID

from flask import Blueprint, g, jsonify, request

from app.core.backend.idempotency import idempotent_write
from app.core.db import db_session
from app.core.security.access_policy import has_permission
from app.core.security.entitlements import org_has_feature
from app.core.security.permissions import requires_auth, requires_permission
from app.features.costing import FEATURE_KEY, service
from app.features.costing.engine import CostEngine
from app.observability import get_logger

logger = get_logger(__name__)

costing_bp = Blueprint("costing", __name__)
API = "/api/core/costing"
MAX_BODY_BYTES = 16 * 1024


def _org() -> UUID:
    return UUID(str(g.org_id))


def _user_id():
    raw = getattr(g, "user_id", None)
    try:
        return UUID(str(raw)) if raw else None
    except (ValueError, TypeError):
        return None


@costing_bp.before_request
def _require_costing_feature():
    request.max_content_length = MAX_BODY_BYTES
    if request.content_length is not None and request.content_length > MAX_BODY_BYTES:
        return jsonify({"error": "Request body too large"}), 413
    # No tenant yet: let @requires_auth answer (401) rather than turning it into a 404.
    org_id = getattr(g, "current_org_id", None)
    if not org_id:
        return None
    if not org_has_feature(db_session(), org_id, FEATURE_KEY):
        logger.info("access_denied", reason="org_not_subscribed", feature=FEATURE_KEY, path=request.path)
        return jsonify({"error": "Not found"}), 404
    return None


@costing_bp.errorhandler(service.CostingError)
def _bad_request(error):
    db_session.rollback()
    return jsonify({"error": str(error)}), 400


@costing_bp.errorhandler(service.CostingNotFoundError)
def _not_found(error):
    db_session.rollback()
    return jsonify({"error": str(error)}), 404


def _body() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise service.CostingError("Send a JSON object")
    return data


@costing_bp.route(f"{API}/lots/<item_id>/cost", methods=["GET"])
@requires_auth
def get_lot_cost(item_id):
    return jsonify(CostEngine(db_session, _org()).lot(item_id))


@costing_bp.route(f"{API}/lots/<item_id>/cost", methods=["PUT"])
@requires_auth
def put_lot_cost(item_id):
    data = _body()
    unknown = set(data) - {"kind", "amount", "quantity", "cost_flow_id", "note"}
    if unknown:
        raise service.CostingError(f"Unknown field(s): {', '.join(sorted(unknown))}")
    service.set_lot_price(
        db_session,
        _org(),
        item_id,
        amount=data.get("amount"),
        quantity=data.get("quantity"),
        kind=data.get("kind") or "manual",
        cost_flow_id=data.get("cost_flow_id"),
        note=data.get("note"),
        user_id=_user_id(),
    )
    db_session.commit()
    return jsonify(CostEngine(db_session, _org()).lot(item_id))


@costing_bp.route(f"{API}/lots/<item_id>/cost/<entry_id>", methods=["DELETE"])
@requires_auth
def delete_lot_cost(item_id, entry_id):
    service.deactivate_entry(db_session, _org(), item_id, entry_id)
    db_session.commit()
    return jsonify(CostEngine(db_session, _org()).lot(item_id))


@costing_bp.route(f"{API}/executions/<execution_id>/cost", methods=["GET"])
@requires_auth
def get_execution_cost(execution_id):
    return jsonify(CostEngine(db_session, _org()).execution(execution_id))


@costing_bp.route(f"{API}/settings", methods=["GET"])
@requires_auth
def get_settings():
    return jsonify(service.get_settings(db_session, _org()))


@costing_bp.route(f"{API}/settings", methods=["PUT"])
@requires_auth
def put_settings():
    result = service.set_settings(db_session, _org(), **_body())
    db_session.commit()
    return jsonify(result)


# --- 8.1b: account treatments --------------------------------------------------------------


@costing_bp.route(f"{API}/accounts", methods=["GET"])
@requires_auth
def get_accounts():
    from app.features.costing.purchase_sources import list_accounts

    return jsonify({"accounts": list_accounts(db_session, _org())})


@costing_bp.route(f"{API}/accounts/<xero_account_id>", methods=["PUT"])
@requires_auth
def put_account(xero_account_id):
    from app.features.costing.purchase_sources import PurchaseSourceError, list_accounts, set_account_treatment

    data = _body()
    if set(data) != {"treatment"}:
        raise service.CostingError('Send only {"treatment": ...}')
    try:
        set_account_treatment(db_session, _org(), xero_account_id, data["treatment"])
    except PurchaseSourceError as error:
        raise service.CostingError(str(error)) from None
    except LookupError:
        raise service.CostingNotFoundError("Account not found") from None
    db_session.commit()
    row = next((a for a in list_accounts(db_session, _org()) if a["xero_account_id"] == str(xero_account_id)), None)
    return jsonify(row)


# --- 8.1c-1: recording purchases into stock ---------------------------------------------------------


def _purchase_card(line_id):
    from app.features.costing import actions

    line = actions.get_line(db_session, _org(), line_id, for_update=False)
    return jsonify(actions.card(db_session, line, actions._document(db_session, line)))


def _parse_date(raw):
    from datetime import date

    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise service.CostingError("Dates are YYYY-MM-DD") from None


@costing_bp.route(f"{API}/purchases", methods=["GET"])
@requires_auth
def list_purchases():
    from app.features.costing import actions

    return jsonify(
        actions.list_purchases(
            db_session,
            _org(),
            request.args.get("tab", "to_record"),
            _parse_date(request.args.get("from")),
            _parse_date(request.args.get("to")),
        )
    )


@costing_bp.route(f"{API}/purchases/<line_id>/candidates", methods=["GET"])
@requires_auth
def purchase_candidates(line_id):
    from app.features.costing import actions

    return jsonify({"candidates": actions.candidates(db_session, _org(), line_id)})


@costing_bp.route(f"{API}/purchases/<line_id>/record", methods=["POST"])
@requires_auth
@requires_permission("inventory.adjust")  # creates stock: costs.manage (policy) AND inventory.adjust
@idempotent_write("costing_purchase_record")
def record_purchase(line_id):
    from app.features.costing import actions

    data = _body()
    actions.record(db_session, _org(), line_id, data.get("rows"), data.get("rest"), user_id=_user_id())
    db_session.commit()
    return _purchase_card(line_id)


@costing_bp.route(f"{API}/purchases/<line_id>/link", methods=["POST"])
@requires_auth
@requires_permission("inventory.adjust")
@idempotent_write("costing_purchase_link")
def link_purchase(line_id):
    from app.features.costing import actions

    data = _body()
    actions.link(db_session, _org(), line_id, data.get("lots"), data.get("rest"), user_id=_user_id())
    db_session.commit()
    return _purchase_card(line_id)


@costing_bp.route(f"{API}/purchases/<line_id>/refund", methods=["POST"])
@requires_auth
@idempotent_write("costing_purchase_refund")
def refund_purchase(line_id):
    from app.features.costing import actions

    actions.refund(db_session, _org(), line_id, _body().get("lots"), user_id=_user_id())
    db_session.commit()
    return _purchase_card(line_id)


@costing_bp.route(f"{API}/purchases/<line_id>/<action>", methods=["POST"])
@requires_auth
def simple_purchase_action(line_id, action):
    from app.features.costing import actions

    handlers = {"not-stock": actions.not_stock, "skip": actions.skip, "reopen": actions.reopen}
    if action == "review":
        choice = _body().get("action")
        if choice == "unlink" and not has_permission(g.current_user, "inventory.adjust"):
            return jsonify({"error": "Unlinking a purchase from stock needs inventory.adjust"}), 403
        actions.review(db_session, _org(), line_id, choice)
    elif action in handlers:
        handlers[action](db_session, _org(), line_id)
    else:
        return jsonify({"error": "Not found"}), 404
    db_session.commit()
    return _purchase_card(line_id)


@costing_bp.route(f"{API}/purchases/<line_id>/allocations", methods=["PUT"])
@requires_auth
@requires_permission("inventory.adjust")
def edit_purchase_allocations(line_id):
    from app.features.costing import actions

    actions.edit_allocations(db_session, _org(), line_id, _body().get("allocations"))
    db_session.commit()
    return _purchase_card(line_id)
