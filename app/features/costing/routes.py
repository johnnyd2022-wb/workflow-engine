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
from app.features.costing.rules import RuleConflictError
from app.observability import get_logger

logger = get_logger(__name__)

costing_bp = Blueprint(
    "costing",
    __name__,
    template_folder="frontend/templates",
    static_folder="frontend/static",
    static_url_path="/static/costing",
)
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
            historical=request.args.get("historical") in ("1", "true"),
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


def _simple(action_name):
    def view(line_id):
        from app.features.costing import actions

        if action_name == "review":
            choice = _body().get("action")
            if choice == "unlink" and not has_permission(g.current_user, "inventory.adjust"):
                return jsonify({"error": "Unlinking a purchase from stock needs inventory.adjust"}), 403
            actions.review(db_session, _org(), line_id, choice)
        elif action_name == "not-stock":
            body = request.get_json(silent=True) or {}
            if not isinstance(body, dict) or set(body) - {"always"} or not isinstance(body.get("always", False), bool):
                raise service.CostingError('Send nothing, or {"always": true}')
            line = actions.not_stock(db_session, _org(), line_id)
            if body.get("always"):
                from app.features.costing import rules

                rules.not_stock_rule(db_session, _org(), line, actions._document(db_session, line), user_id=_user_id())
        else:
            {"skip": actions.skip, "reopen": actions.reopen}[action_name](db_session, _org(), line_id)
        db_session.commit()
        return _purchase_card(line_id)

    view.__name__ = f"purchase_{action_name.replace('-', '_')}"
    return view


for _action in ("not-stock", "skip", "reopen", "review"):
    costing_bp.add_url_rule(
        f"{API}/purchases/<line_id>/{_action}",
        endpoint=f"purchase_{_action.replace('-', '_')}",
        view_func=requires_auth(idempotent_write(f"costing_purchase_{_action}")(_simple(_action))),
        methods=["POST"],
    )


@costing_bp.route(f"{API}/purchases/<line_id>/allocations", methods=["PUT"])
@requires_auth
@requires_permission("inventory.adjust")
def edit_purchase_allocations(line_id):
    from app.features.costing import actions

    actions.edit_allocations(db_session, _org(), line_id, _body().get("allocations"))
    db_session.commit()
    return _purchase_card(line_id)


# --- 8.1c-2: rules, remember, bulk, historical runs ---------------------------------------------------


@costing_bp.errorhandler(RuleConflictError)
def _conflict(error):
    db_session.rollback()
    return jsonify({"error": str(error)}), 409


@costing_bp.route(f"{API}/rules", methods=["GET"])
@requires_auth
def list_rules():
    from app.features.costing import rules
    from app.features.costing.models import PurchaseRule

    rows = (
        db_session.query(PurchaseRule)
        .filter(PurchaseRule.org_id == _org())
        .order_by(PurchaseRule.created_at, PurchaseRule.id)
        .all()
    )
    return jsonify({"rules": [rules.as_dict(r) for r in rows]})


@costing_bp.route(f"{API}/rules", methods=["POST"])
@requires_auth
def create_rule():
    from app.features.costing import rules

    rule = rules.create(db_session, _org(), _body(), user_id=_user_id())
    db_session.commit()
    return jsonify(rules.as_dict(rule)), 201


@costing_bp.route(f"{API}/rules/<rule_id>", methods=["PUT"])
@requires_auth
def update_rule(rule_id):
    from app.features.costing import rules

    rule = rules.update(db_session, _org(), rule_id, _body())
    db_session.commit()
    return jsonify(rules.as_dict(rule))


@costing_bp.route(f"{API}/rules/<rule_id>", methods=["DELETE"])
@requires_auth
def delete_rule(rule_id):
    from app.features.costing import rules

    rules.delete(db_session, _org(), rule_id)
    db_session.commit()
    return jsonify({"deleted": True})


@costing_bp.route(f"{API}/purchases/<line_id>/remember", methods=["POST"])
@requires_auth
@idempotent_write("costing_purchase_remember")
def remember_purchase(line_id):
    from app.features.costing import rules

    rule = rules.remember(db_session, _org(), line_id, user_id=_user_id())
    db_session.commit()
    return jsonify(rules.as_dict(rule)), 201


BULK_ACTIONS = ("skip", "not_stock", "apply_rule")


@costing_bp.route(f"{API}/purchases/bulk", methods=["POST"])
@requires_auth
def bulk_purchases():
    from app.features.costing import actions, rules
    from app.features.costing.purchase_sources import classify_line
    from app.features.crm.models.xero_account import XeroAccount

    data = _body()
    ids, action = data.get("line_ids"), data.get("action")
    if action not in BULK_ACTIONS:
        raise service.CostingError(f"action must be one of {', '.join(BULK_ACTIONS)}")
    if not isinstance(ids, list) or not 1 <= len(ids) <= 200:
        raise service.CostingError("Send 1 to 200 line_ids")
    if len({str(i) for i in ids}) != len(ids):
        raise service.CostingError("Each line can appear only once")
    org = _org()
    active = rules.active_rules(db_session, org) if action == "apply_rule" else None
    results = []
    for raw in ids:
        try:
            with db_session.begin_nested():
                if action == "skip":
                    actions.skip(db_session, org, raw)
                    results.append({"line_id": str(raw), "ok": True})
                elif action == "not_stock":
                    actions.not_stock(db_session, org, raw)
                    results.append({"line_id": str(raw), "ok": True})
                else:
                    line = actions.get_line(db_session, org, raw)
                    doc = actions._document(db_session, line)
                    account = (
                        db_session.query(XeroAccount)
                        .filter(XeroAccount.org_id == org, XeroAccount.id == line.account_id)
                        .one()
                    )
                    before = line.treatment
                    classify_line(line, account, payee=doc.payee_name, rules=active)
                    actions.on_line_treatment_changed(db_session, line, before, line.treatment)
                    db_session.flush()
                    results.append(
                        {"line_id": str(raw), "ok": True, "card": actions.card(db_session, line, doc, rules=active)}
                    )
        except service.CostingNotFoundError:
            results.append({"line_id": str(raw), "ok": False, "error": "not found"})
        except service.CostingError as error:
            results.append({"line_id": str(raw), "ok": False, "error": str(error)})
    db_session.commit()
    return jsonify({"results": results})


@costing_bp.route(f"{API}/purchases/historical-run", methods=["POST"])
@requires_auth
def historical_run():
    from datetime import timedelta

    from app.features.costing.purchase_sources import nz_today
    from app.features.crm.services.xero_sync_service import PurchasesNeedReconnectError, XeroSyncService

    data = _body()
    if set(data) - {"from", "to"} or not data.get("from") or not data.get("to"):
        raise service.CostingError("Send from and to (YYYY-MM-DD)")
    date_from, date_to = _parse_date(data["from"]), _parse_date(data["to"])
    if date_from > date_to:
        raise service.CostingError("from is after to")
    if date_to > nz_today():
        raise service.CostingError("to can't be in the future")
    if date_to - date_from > timedelta(days=3 * 366):
        raise service.CostingError("A historical run covers at most 3 years")
    try:
        stats = XeroSyncService(db_session).historical_purchases(_org(), date_from, date_to)
    except PurchasesNeedReconnectError as error:
        db_session.rollback()
        return jsonify({"error": str(error), "code": "needs_reconnect"}), 409
    db_session.commit()
    return jsonify(
        {
            "documents": stats["documents"],
            "lines": stats["lines"],
            "from": date_from.isoformat(),
            "to": date_to.isoformat(),
        }
    )


# --- 8.1e-1: readiness --------------------------------------------------------------------------------


@costing_bp.route(f"{API}/readiness", methods=["GET"])
@requires_auth
def readiness_list():
    from app.features.costing import readiness

    return jsonify({"products": readiness.list_products(db_session, _org())})


@costing_bp.route(f"{API}/readiness/<path:key>", methods=["GET"])
@requires_auth
def readiness_detail(key):
    from app.features.costing import readiness

    return jsonify(readiness.product_detail(db_session, _org(), key))


# --- 8.1d: the Purchases page -----------------------------------------------------------------------


@costing_bp.route("/core/costing/purchases", methods=["GET"])
@requires_auth
def purchases_page():
    from flask import render_template

    return render_template("costing/purchases.html", active_page="core")
