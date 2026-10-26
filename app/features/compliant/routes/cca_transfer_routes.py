"""Sales to other businesses' CCAs: the destinations, the movement register and its page (GL-P08)."""

from datetime import date
from uuid import UUID

from flask import Blueprint, g, jsonify, render_template, request
from sqlalchemy.exc import IntegrityError

from app.core.db import db_session
from app.core.security.permissions import requires_auth, requires_org_scope
from app.core.utils.log_action import log_action
from app.features.compliant.modules.nz_alcohol import cca_transfers
from app.features.compliant.routes.page_routes import _nz_alcohol_template_context

cca_transfer_bp = Blueprint("compliant_cca_transfers", __name__, template_folder="../frontend/templates")


def _org() -> UUID:
    return UUID(str(g.current_org_id))


def _uuid(value) -> UUID | None:
    try:
        return UUID(str(value))
    except ValueError:
        return None


def _save(action, entity, write):
    try:
        row = write()
        db_session.commit()
    except LookupError as exc:
        db_session.rollback()
        return None, (jsonify({"error": str(exc)}), 404)
    except ValueError as exc:
        db_session.rollback()
        return None, (jsonify({"error": str(exc)}), 400)
    except IntegrityError:
        db_session.rollback()
        return None, (jsonify({"error": "That conflicts with a movement or destination already recorded"}), 409)
    if row is not None:
        log_action(action, entity, row.id)
    return row, None


@cca_transfer_bp.get("/compliant/nz-alcohol/customs/transfers")
@requires_auth
@requires_org_scope
def transfers_page():
    """Sales that went to another CCA: what moved, when, who carried it and the receipt."""
    return render_template("compliant/customs_transfers.html", **_nz_alcohol_template_context(customs_view="transfers"))


@cca_transfer_bp.get("/api/compliant/nz-alcohol/cca-transfers")
@requires_auth
@requires_org_scope
def get_transfers():
    since = None
    if request.args.get("since"):
        try:
            since = date.fromisoformat(request.args["since"])
        except ValueError:
            return jsonify({"error": "since must be a date like 2026-01-01"}), 400
    result = cca_transfers.register(db_session, _org(), since=since)
    result["destinations"] = cca_transfers.destinations(db_session, _org())
    return jsonify(result)


@cca_transfer_bp.get("/api/compliant/nz-alcohol/cca-transfers/sales")
@requires_auth
@requires_org_scope
def search_sales():
    return jsonify({"sales": cca_transfers.sales_to_mark(db_session, _org(), request.args.get("q", ""))})


@cca_transfer_bp.post("/api/compliant/nz-alcohol/cca-transfers")
@requires_auth
@requires_org_scope
def record_transfer():
    data = request.get_json(silent=True)
    row, error = _save(
        "cca_departure_recorded",
        "cca_departure",
        lambda: cca_transfers.record_departure(db_session, _org(), data, g.current_user.id),
    )
    return error or (jsonify(cca_transfers.departure_dict(row)), 201)


@cca_transfer_bp.put("/api/compliant/nz-alcohol/cca-transfers/<departure_id>/receipt")
@requires_auth
@requires_org_scope
def record_transfer_receipt(departure_id):
    ident = _uuid(departure_id)
    if ident is None:
        return jsonify({"error": "No such movement"}), 404
    data = request.get_json(silent=True)
    row, error = _save(
        "cca_departure_received",
        "cca_departure",
        lambda: cca_transfers.record_receipt(db_session, _org(), ident, data),
    )
    return error or (jsonify(cca_transfers.departure_dict(row)), 200)


@cca_transfer_bp.delete("/api/compliant/nz-alcohol/cca-transfers/<departure_id>")
@requires_auth
@requires_org_scope
def remove_transfer(departure_id):
    ident = _uuid(departure_id)
    if ident is None:
        return jsonify({"error": "No such movement"}), 404
    _row, error = _save(
        "cca_departure_removed", "cca_departure", lambda: cca_transfers.remove_departure(db_session, _org(), ident)
    )
    if error:
        return error
    log_action("cca_departure_removed", "cca_departure", ident)
    return "", 204


@cca_transfer_bp.get("/api/compliant/nz-alcohol/cca-destinations")
@requires_auth
@requires_org_scope
def get_destinations():
    return jsonify(
        {
            "destinations": cca_transfers.destinations(db_session, _org()),
            "kinds": cca_transfers.KIND_LABELS,
            "customers": cca_transfers.customers(db_session, _org()),
        }
    )


@cca_transfer_bp.post("/api/compliant/nz-alcohol/cca-destinations")
@requires_auth
@requires_org_scope
def add_destination():
    data = request.get_json(silent=True)
    row, error = _save(
        "cca_destination_created", "cca_destination", lambda: cca_transfers.save_destination(db_session, _org(), data)
    )
    return error or (jsonify(cca_transfers.destination_dict(row)), 201)


@cca_transfer_bp.put("/api/compliant/nz-alcohol/cca-destinations/<destination_id>")
@requires_auth
@requires_org_scope
def update_destination(destination_id):
    ident = _uuid(destination_id)
    if ident is None:
        return jsonify({"error": "No such destination"}), 404
    data = request.get_json(silent=True)
    row, error = _save(
        "cca_destination_updated",
        "cca_destination",
        lambda: cca_transfers.save_destination(db_session, _org(), data, ident),
    )
    return error or (jsonify(cca_transfers.destination_dict(row)), 200)
