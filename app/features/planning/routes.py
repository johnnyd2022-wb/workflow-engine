"""Production demand workspace; no automatic execution or stock changes."""

from uuid import UUID

from flask import Blueprint, g, jsonify, render_template, request

from app.core.db import db_session
from app.core.db.models.audit_log import AuditLog
from app.core.security.permissions import requires_auth, requires_org_scope
from app.features.planning import demand_service as service

planning_bp = Blueprint(
    "planning",
    __name__,
    template_folder="frontend/templates",
    static_folder="frontend/static",
    static_url_path="/planning/static",
)


def _org_id():
    return UUID(str(g.current_org_id))


def _audit(action, row):
    # Demand and actor evidence commit together.
    db_session.add(
        AuditLog(
            org_id=_org_id(),
            user_id=g.current_user.id,
            action=action,
            entity="planning_demand",
            entity_id=row.id,
            meta_data={"source_output_id": str(row.source_output_id)},
        )
    )


@planning_bp.get("/core/planner")
@requires_auth
@requires_org_scope
def planner_page():
    return render_template("planning/demand.html", active_page="planner")


@planning_bp.get("/api/core/planner/demands")
@requires_auth
@requires_org_scope
def get_demands():
    return jsonify(
        {
            "demands": service.list_demands(db_session, _org_id()),
            "outputs": service.output_catalog(db_session, _org_id()),
        }
    )


@planning_bp.post("/api/core/planner/demands")
@requires_auth
@requires_org_scope
def add_demand():
    try:
        row = service.create_demand(db_session, _org_id(), request.get_json(silent=True))
        _audit("planning_demand_created", row)
        db_session.commit()
    except ValueError as exc:
        db_session.rollback()
        return jsonify({"error": str(exc)}), 400
    return jsonify(service.demand_dict(row)), 201


@planning_bp.post("/api/core/planner/demands/<uuid:demand_id>/cancel")
@requires_auth
@requires_org_scope
def cancel_demand(demand_id):
    try:
        row = service.cancel_demand(db_session, _org_id(), demand_id)
        if row is None:
            return jsonify({"error": "Demand not found"}), 404
        _audit("planning_demand_cancelled", row)
        db_session.commit()
    except ValueError as exc:
        db_session.rollback()
        return jsonify({"error": str(exc)}), 400
    return jsonify(service.demand_dict(row))
