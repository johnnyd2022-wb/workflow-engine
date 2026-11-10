"""Purchases API (live-cogs 8.1b): the list behind the Purchases page.

Routes join the ``costing`` blueprint (``routes.py`` imports this module last), so they share its
feature gate (404 unless the org holds ``costing``), its error handlers, and the ``costing.*``
rows of ``access_policy.POLICY`` (GET needs ``costs.view``). The record / link / skip / bulk /
historical-run writes are 8.1c's.
"""

from __future__ import annotations

from datetime import date

from flask import jsonify, request

from app.core.db import db_session
from app.core.security.permissions import requires_auth
from app.features.costing import purchase_queries, service
from app.features.costing.routes import API, _org, costing_bp


def _date_arg(name: str) -> date | None:
    raw = request.args.get(name)
    if raw in (None, ""):
        return None
    try:
        if len(raw) != 10:
            raise ValueError
        return date.fromisoformat(raw)
    except ValueError:
        raise service.CostingError(f"{name} must be a date like 2026-11-30") from None


def _int_arg(name: str, default: int, *, minimum: int, maximum: int | None = None) -> int:
    raw = request.args.get(name)
    if raw in (None, ""):
        return default
    try:
        value = int(raw)
    except ValueError:
        raise service.CostingError(f"{name} must be a whole number") from None
    if value < minimum or (maximum is not None and value > maximum):
        bound = f"between {minimum} and {maximum}" if maximum is not None else f"{minimum} or more"
        raise service.CostingError(f"{name} must be {bound}")
    return value


@costing_bp.route(f"{API}/purchases", methods=["GET"])
@requires_auth
def list_purchases():
    tab = request.args.get("tab") or "to_record"
    if tab not in purchase_queries.TABS:
        raise service.CostingError(f"tab must be one of: {', '.join(purchase_queries.TABS)}")
    date_from, date_to = _date_arg("from"), _date_arg("to")
    return jsonify(
        purchase_queries.list_cards(
            db_session,
            _org(),
            tab,
            date_from=date_from,
            date_to=date_to,
            limit=_int_arg("limit", purchase_queries.DEFAULT_LIMIT, minimum=1, maximum=purchase_queries.MAX_LIMIT),
            offset=_int_arg("offset", 0, minimum=0),
        )
    )
