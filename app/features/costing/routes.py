"""Costing API (live-cogs 8.1a): lot cost, batch cost, manual / free prices, settings.

Permissions come from ``access_policy.POLICY`` (``costing.*``: GET needs ``costs.view``,
everything else ``costs.manage``), enforced app-wide before this blueprint runs. Every route
also 404s unless the org holds the ``costing`` feature.
"""

from __future__ import annotations

from uuid import UUID

from flask import Blueprint, g, jsonify, request

from app.core.db import db_session
from app.core.security.entitlements import org_has_feature
from app.core.security.permissions import requires_auth
from app.features.costing import FEATURE_KEY, service
from app.features.costing.engine import CostEngine
from app.observability import get_logger

logger = get_logger(__name__)

costing_bp = Blueprint("costing", __name__)
API = "/api/core/costing"


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


# Purchases routes (8.1b) attach to costing_bp; imported last so the blueprint and helpers exist.
from app.features.costing import purchase_routes  # noqa: E402, F401
