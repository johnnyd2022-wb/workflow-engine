"""Liquor licensing register API and page (plan 2.5)."""

from datetime import UTC, date, datetime
from uuid import UUID

from flask import Blueprint, Response, g, jsonify, render_template, request

from app.core.db import db_session
from app.core.db.models.organisation import Organisation
from app.core.security.permissions import requires_auth
from app.core.utils.log_action import log_action
from app.features.compliant.licensing_pack_pdf import build_licensing_pack_pdf
from app.features.compliant.models.licensing import LiquorLicence, ManagerCertificate
from app.features.compliant.modules.nz_alcohol import licensing
from app.features.compliant.routes.page_routes import _nz_alcohol_template_context

licensing_bp = Blueprint("compliant_licensing", __name__, template_folder="../frontend/templates")


def _org_id() -> UUID:
    return UUID(str(g.org_id))


def _overview():
    return jsonify(licensing.overview(db_session, _org_id(), date.today())), 200


def _load(model, item_id: str):
    try:
        iid = UUID(item_id)
    except ValueError:
        return None
    return db_session.query(model).filter(model.id == iid, model.org_id == _org_id()).one_or_none()


def _body() -> dict:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _save(action: str, entity: str, entity_id, fn):
    try:
        fn()
        db_session.commit()
    except ValueError as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 400
    log_action(action, entity, entity_id, {})
    return _overview()


@licensing_bp.route("/compliant/nz-alcohol/licensing", methods=["GET"])
@requires_auth
def licensing_page():
    return render_template("compliant/licensing.html", **_nz_alcohol_template_context(active_compliant_tab="licensing"))


@licensing_bp.route("/api/compliant/licensing", methods=["GET"])
@requires_auth
def get_licensing():
    return _overview()


@licensing_bp.route("/api/compliant/licensing/pack.pdf", methods=["GET"])
@requires_auth
def licensing_pack():
    """One download for an inspector: licences, managers, checks, training and the log."""
    data = licensing.overview(db_session, _org_id(), date.today())
    training = [
        {
            "title": r.title,
            "recorded_on": r.created_at.date().isoformat(),
            "due_date": r.due_date.isoformat() if r.due_date else "",
            "evidence_reference": r.evidence_reference or "",
        }
        for r in licensing.training_records(db_session, _org_id())
    ]
    org_name = db_session.query(Organisation.name).filter(Organisation.id == _org_id()).scalar() or "Organisation"
    user = g.current_user
    who = " ".join(p for p in (user.first_name, user.last_name) if p) or user.email
    pdf = build_licensing_pack_pdf(org_name, data, training, who)
    log_action("download_licensing_pack", "organisation", _org_id(), {})
    return Response(
        pdf,
        mimetype="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="licensing-records-{date.today().isoformat()}.pdf"'},
    )


# --- licences ---------------------------------------------------------------------------------


@licensing_bp.route("/api/compliant/licensing/licences", methods=["POST"])
@requires_auth
def create_licence():
    licence = LiquorLicence(org_id=_org_id(), created_by_user_id=g.current_user.id, endorsements=[])

    def run():
        licensing.assign_licence_site(db_session, licence, _body())
        licensing.apply_licence(licence, _body())
        db_session.add(licence)
        db_session.flush()

    resp = _save("create_liquor_licence", "liquor_licence", None, run)
    return (resp[0], 201) if resp[1] == 200 else resp


@licensing_bp.route("/api/compliant/licensing/licences/<licence_id>", methods=["PUT"])
@requires_auth
def update_licence(licence_id: str):
    licence = _load(LiquorLicence, licence_id)
    if licence is None:
        return jsonify({"error": "Licence not found"}), 404

    def run():
        licensing.assign_licence_site(db_session, licence, _body())
        licensing.apply_licence(licence, _body())

    return _save("update_liquor_licence", "liquor_licence", licence.id, run)


def _date_arg(field: str) -> date:
    value = _body().get(field) or date.today().isoformat()
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise ValueError(f"{field} must be a date (YYYY-MM-DD)") from None


@licensing_bp.route("/api/compliant/licensing/licences/<licence_id>/renewal-lodged", methods=["POST"])
@requires_auth
def lodge_licence_renewal(licence_id: str):
    licence = _load(LiquorLicence, licence_id)
    if licence is None:
        return jsonify({"error": "Licence not found"}), 404
    return _save(
        "lodge_licence_renewal",
        "liquor_licence",
        licence.id,
        lambda: licensing.lodge_renewal(licence, _date_arg("lodged_on"), date.today()),
    )


@licensing_bp.route("/api/compliant/licensing/licences/<licence_id>/renewed", methods=["POST"])
@requires_auth
def licence_renewed(licence_id: str):
    licence = _load(LiquorLicence, licence_id)
    if licence is None:
        return jsonify({"error": "Licence not found"}), 404

    def run():
        if not _body().get("expires_on"):
            raise ValueError("Give the renewed licence's expiry date")
        licensing.renewal_granted(licence, _date_arg("expires_on"))

    return _save("licence_renewed", "liquor_licence", licence.id, run)


@licensing_bp.route("/api/compliant/licensing/licences/<licence_id>/fee-paid", methods=["POST"])
@requires_auth
def licence_fee_paid(licence_id: str):
    licence = _load(LiquorLicence, licence_id)
    if licence is None:
        return jsonify({"error": "Licence not found"}), 404
    return _save("licence_fee_paid", "liquor_licence", licence.id, lambda: licensing.pay_annual_fee(licence))


@licensing_bp.route("/api/compliant/licensing/licences/<licence_id>/end", methods=["POST"])
@requires_auth
def end_licence(licence_id: str):
    licence = _load(LiquorLicence, licence_id)
    if licence is None:
        return jsonify({"error": "Licence not found"}), 404
    return _save("end_liquor_licence", "liquor_licence", licence.id, lambda: setattr(licence, "status", "ended"))


# --- managers ---------------------------------------------------------------------------------


@licensing_bp.route("/api/compliant/licensing/managers", methods=["POST"])
@requires_auth
def create_manager():
    cert = ManagerCertificate(org_id=_org_id())

    def run():
        licensing.apply_manager(db_session, _org_id(), cert, _body())
        db_session.add(cert)
        db_session.flush()

    resp = _save("create_manager_certificate", "manager_certificate", None, run)
    return (resp[0], 201) if resp[1] == 200 else resp


@licensing_bp.route("/api/compliant/licensing/managers/<cert_id>", methods=["PUT"])
@requires_auth
def update_manager(cert_id: str):
    cert = _load(ManagerCertificate, cert_id)
    if cert is None:
        return jsonify({"error": "Certificate not found"}), 404
    return _save(
        "update_manager_certificate",
        "manager_certificate",
        cert.id,
        lambda: licensing.apply_manager(db_session, _org_id(), cert, _body()),
    )


@licensing_bp.route("/api/compliant/licensing/managers/<cert_id>/renewal-lodged", methods=["POST"])
@requires_auth
def lodge_manager_renewal(cert_id: str):
    cert = _load(ManagerCertificate, cert_id)
    if cert is None:
        return jsonify({"error": "Certificate not found"}), 404
    return _save(
        "lodge_manager_renewal",
        "manager_certificate",
        cert.id,
        lambda: licensing.lodge_manager_renewal(cert, _date_arg("lodged_on"), date.today()),
    )


@licensing_bp.route("/api/compliant/licensing/managers/<cert_id>/renewed", methods=["POST"])
@requires_auth
def manager_renewed(cert_id: str):
    cert = _load(ManagerCertificate, cert_id)
    if cert is None:
        return jsonify({"error": "Certificate not found"}), 404

    def run():
        if not _body().get("expires_on"):
            raise ValueError("Give the renewed certificate's expiry date")
        licensing.manager_renewed(cert, _date_arg("expires_on"))

    return _save("manager_renewed", "manager_certificate", cert.id, run)


@licensing_bp.route("/api/compliant/licensing/managers/<cert_id>/end", methods=["POST"])
@requires_auth
def end_manager(cert_id: str):
    cert = _load(ManagerCertificate, cert_id)
    if cert is None:
        return jsonify({"error": "Certificate not found"}), 404
    return _save("end_manager_certificate", "manager_certificate", cert.id, lambda: setattr(cert, "active", False))


# --- log ----------------------------------------------------------------------------------------


@licensing_bp.route("/api/compliant/licensing/log", methods=["POST"])
@requires_auth
def add_log_entry():
    def run():
        db_session.add(licensing.new_log_entry(_org_id(), _body(), g.current_user.id, datetime.now(UTC)))

    resp = _save("add_licensing_log_entry", "licensing_log_entry", None, run)
    return (resp[0], 201) if resp[1] == 200 else resp
