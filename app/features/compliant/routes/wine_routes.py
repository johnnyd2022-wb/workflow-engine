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
