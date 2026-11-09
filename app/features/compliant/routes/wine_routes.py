"""Compliance -> Wine: WSMP status, this vintage, label claims and bottling pre-flight."""

from uuid import UUID

from flask import Blueprint, g, jsonify, render_template, request

from app.core.db import db_session
from app.core.db.models.audit_log import AuditLog
from app.core.security.permissions import requires_auth, requires_org_scope
from app.features.compliant.modules.nz_alcohol.wine import service as wine
from app.features.compliant.routes.page_routes import _nz_alcohol_template_context

wine_bp = Blueprint("compliant_wine", __name__, template_folder="../frontend/templates")


def _org() -> UUID:
    return UUID(str(g.current_org_id))


@wine_bp.get("/compliant/nz-alcohol/wine")
@requires_auth
@requires_org_scope
def page():
    return render_template("compliant/wine.html", **_nz_alcohol_template_context())


@wine_bp.get("/api/compliant/wine")
@requires_auth
@requires_org_scope
def get_overview():
    return jsonify(wine.overview(db_session, _org()))


@wine_bp.put("/api/compliant/wine/plan")
@requires_auth
@requires_org_scope
def update_plan():
    try:
        plan = wine.update_plan(db_session, _org(), request.get_json(silent=True))
        db_session.add(
            AuditLog(org_id=_org(), user_id=g.current_user.id, action="wine_plan_updated", entity="compliance_profile")
        )
        db_session.commit()
    except ValueError as exc:
        db_session.rollback()
        return jsonify({"error": str(exc)}), 400
    return jsonify({"plan": plan})


def _settings() -> dict:
    from app.features.compliant.service import ComplianceService

    profile = ComplianceService(db_session).get_profile(_org())
    if profile is None or not profile.enabled:
        return {}
    return dict(profile.settings or {})


def _body() -> dict:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _done(result, status=201):
    db_session.commit()
    return jsonify(result), status


def _refused(exc):
    db_session.rollback()
    return jsonify({"error": str(exc)}), 400


@wine_bp.post("/api/compliant/wine/records")
@requires_auth
@requires_org_scope
def add_record():
    from app.features.compliant.modules.nz_alcohol.wine import register

    try:
        row = register.add_control_record(db_session, _org(), g.current_user.id, _settings(), _body())
    except ValueError as exc:
        return _refused(exc)
    return _done({"record": register.record_dict(row)})


@wine_bp.post("/api/compliant/wine/problems")
@requires_auth
@requires_org_scope
def report_problem():
    from app.features.compliant.modules.nz_alcohol.wine import register

    try:
        result = register.report_problem(db_session, _org(), g.current_user.id, _body())
    except ValueError as exc:
        return _refused(exc)
    return _done(result)


@wine_bp.post("/api/compliant/wine/lots/<lot_id>/label-approval")
@requires_auth
@requires_org_scope
def approve_label(lot_id: str):
    from app.features.compliant.modules.nz_alcohol.wine import register

    overview = wine.overview(db_session, _org())
    pf = next((p for p in overview.get("preflight", []) if p["lot"]["id"] == lot_id), None)
    if pf is None:
        return jsonify({"error": "Bottled wine lot not found"}), 404
    try:
        row = register.approve_label(db_session, _org(), g.current_user.id, pf["lot"], pf, _body())
    except ValueError as exc:
        return _refused(exc)
    return _done({"record": register.record_dict(row)})


@wine_bp.get("/api/compliant/wine/lots/<lot_id>/trace")
@requires_auth
@requires_org_scope
def lot_trace(lot_id: str):
    from flask import Response

    from app.features.compliant.modules.nz_alcohol.wine import roles
    from app.features.compliant.modules.nz_alcohol.wine import trace as wine_trace

    try:
        lot_uuid = UUID(lot_id)
    except ValueError:
        return jsonify({"error": "Wine lot not found"}), 404
    result = wine_trace.lot_trace(db_session, _org(), lot_uuid, roles.roles_for_org(db_session, _org(), _settings()))
    if result is None:
        return jsonify({"error": "Wine lot not found"}), 404
    if request.args.get("format") == "csv":
        safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in result["lot"]["name"])[:60] or "wine-lot"
        return Response(
            wine_trace.as_csv(result),
            mimetype="text/csv",
            headers={"Content-Disposition": f'attachment; filename="trace-{safe}.csv"'},
        )
    return jsonify(result)


@wine_bp.post("/api/compliant/wine/export/eligibility")
@requires_auth
@requires_org_scope
def add_eligibility():
    from datetime import date

    from app.features.compliant.modules.nz_alcohol.wine import register

    data = _body()
    lot = wine.lot_info(db_session, _org(), data.get("lot_id"))
    if lot is None:
        return jsonify({"error": "Choose a wine lot"}), 400
    try:
        row = register.add_eligibility(db_session, _org(), g.current_user.id, _settings(), lot, data, date.today())
    except ValueError as exc:
        return _refused(exc)
    return _done({"record": register.record_dict(row)})


@wine_bp.post("/api/compliant/wine/export/consignments")
@requires_auth
@requires_org_scope
def add_consignment():
    from datetime import date

    from app.features.compliant.modules.nz_alcohol.wine import register

    try:
        row = register.add_consignment(
            db_session, _org(), g.current_user.id, _settings(), _body(), date.today(),
            lambda lot_id: wine.lot_info(db_session, _org(), lot_id),
        )  # fmt: skip
    except ValueError as exc:
        return _refused(exc)
    return _done({"record": register.record_dict(row)})
