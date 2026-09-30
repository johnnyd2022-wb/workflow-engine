"""Production demand workspace; no automatic execution or stock changes."""

from datetime import date, timedelta
from uuid import UUID

from flask import Blueprint, g, jsonify, render_template, request

from app.core.db import db_session
from app.core.db.models.audit_log import AuditLog
from app.core.security.permissions import requires_auth, requires_org_scope
from app.features.planning import batch_service as batches
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


def _planning_error(exc):
    db_session.rollback()
    status = 409 if isinstance(exc, batches.PlanningConflictError) else 400
    return jsonify({"error": str(exc)}), status


def _batch_audit(action, row):
    db_session.add(
        AuditLog(
            org_id=_org_id(),
            user_id=g.current_user.id,
            action=action,
            entity="planning_batch",
            entity_id=row.id,
            meta_data={"demand_id": str(row.demand_id), "revision": row.revision},
        )
    )


@planning_bp.get("/core/planner/board")
@requires_auth
@requires_org_scope
def planner_board():
    return render_template("planning/board.html", active_page="planner")


@planning_bp.get("/api/core/planner/workflows")
@requires_auth
@requires_org_scope
def planning_workflows():
    from app.core.db.models.site import Site
    from app.features.planning.material_adapter import lot_catalog
    from app.features.sites.service import serialise

    lots, truncated = lot_catalog(db_session, _org_id())

    sites = (
        db_session.query(Site)
        .filter(Site.org_id == _org_id(), Site.is_active.is_(True))
        .order_by(Site.is_default.desc(), Site.name)
        .all()
    )
    return jsonify(
        {
            "workflows": batches.workflow_catalog(db_session, _org_id()),
            "sites": [serialise(site) for site in sites] if g.current_org.multiple_sites_enabled else [],
            "material_lots": lots,
            "material_lots_truncated": truncated,
        }
    )


@planning_bp.post("/api/core/planner/workflows/<uuid:process_id>/settings")
@requires_auth
@requires_org_scope
def save_planning_workflow(process_id):
    try:
        row = batches.save_setting(db_session, _org_id(), process_id, request.get_json(silent=True))
        db_session.add(
            AuditLog(
                org_id=_org_id(),
                user_id=g.current_user.id,
                action="planning_settings_saved",
                entity="planning_workflow_setting",
                entity_id=row.id,
                meta_data={"revision": row.revision},
            )
        )
        db_session.commit()
    except ValueError as exc:
        return _planning_error(exc)
    return jsonify(batches.setting_dict(row))


@planning_bp.post("/api/core/planner/demands/<uuid:demand_id>/plan")
@requires_auth
@requires_org_scope
def plan_production_demand(demand_id):
    try:
        rows, changed = batches.plan_demand(
            db_session, _org_id(), demand_id, request.get_json(silent=True), today=date.today()
        )
        if rows is None:
            return jsonify({"error": "Demand not found"}), 404
        if changed:
            for row in rows:
                _batch_audit("planning_batch_created", row)
        db_session.commit()
    except ValueError as exc:
        return _planning_error(exc)
    return jsonify({"batches": [batches.batch_dict(row) for row in rows]}), 201 if changed else 200


@planning_bp.get("/api/core/planner/batches")
@requires_auth
@requires_org_scope
def get_planning_batches():
    try:
        start = date.fromisoformat(request.args.get("start", date.today().isoformat()))
        end = date.fromisoformat(request.args.get("end", (start + timedelta(days=6)).isoformat()))
        result = batches.list_batches(db_session, _org_id(), start, end)
    except (ValueError, OverflowError) as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(result)


@planning_bp.post("/api/core/planner/batches/<uuid:batch_id>/action")
@requires_auth
@requires_org_scope
def change_planning_batch(batch_id):
    try:
        row, changed = batches.update_batch(
            db_session, _org_id(), batch_id, request.get_json(silent=True), today=date.today()
        )
        if row is None:
            return jsonify({"error": "Batch not found"}), 404
        if changed:
            _batch_audit("planning_batch_" + request.get_json()["action"], row)
        db_session.commit()
    except ValueError as exc:
        return _planning_error(exc)
    return jsonify(batches.batch_dict(row))


@planning_bp.post("/api/core/planner/batches/<uuid:batch_id>/start")
@requires_auth
@requires_org_scope
def start_planning_batch(batch_id):
    from app.features.planning import start_service

    try:
        result, changed = start_service.start_batch(
            db_session, _org_id(), batch_id, request.get_json(silent=True), request.headers.get("Idempotency-Key")
        )
        if result is None:
            return jsonify({"error": "Batch not found"}), 404
        if changed:
            db_session.add(
                AuditLog(
                    org_id=_org_id(),
                    user_id=g.current_user.id,
                    action="planning_batch_started",
                    entity="planning_batch",
                    entity_id=batch_id,
                    meta_data={"execution_id": result["execution_id"]},
                )
            )
        db_session.commit()
    except ValueError as exc:
        return _planning_error(exc)
    return jsonify(result), 201 if changed else 200


@planning_bp.get("/api/core/planner/material-assessments")
@requires_auth
@requires_org_scope
def get_material_assessment():
    from app.features.planning.material_adapter import latest

    return jsonify({"assessment": latest(db_session, _org_id())})


@planning_bp.post("/api/core/planner/material-assessments")
@requires_auth
@requires_org_scope
def assess_materials():
    from app.features.planning.material_adapter import assess, latest

    try:
        row = assess(db_session, _org_id(), request.get_json(silent=True), today=date.today())
        db_session.add(
            AuditLog(
                org_id=_org_id(),
                user_id=g.current_user.id,
                action="planning_materials_observed",
                entity="planning_material_assessment",
                entity_id=row.id,
                meta_data={"sequence": row.sequence},
            )
        )
        db_session.commit()
    except (ValueError, OverflowError) as exc:
        return _planning_error(exc)
    return jsonify({"assessment": latest(db_session, _org_id(), assessment_id=row.id)}), 201


@planning_bp.get("/api/core/planner/capacity")
@requires_auth
@requires_org_scope
def get_capacity():
    from app.features.planning.capacity_service import review

    try:
        start = date.fromisoformat(request.args.get("start"))
        end = date.fromisoformat(request.args.get("end"))
        return jsonify(review(db_session, _org_id(), start, end))
    except (ValueError, TypeError) as exc:
        return jsonify({"error": str(exc) or "Choose a capacity period"}), 400


@planning_bp.post("/api/core/planner/capacity/sites/<uuid:site_id>")
@requires_auth
@requires_org_scope
def save_capacity(site_id):
    from app.features.planning.capacity_service import save_setting, setting_dict

    try:
        row = save_setting(db_session, _org_id(), site_id, request.get_json(silent=True))
        db_session.add(
            AuditLog(
                org_id=_org_id(),
                user_id=g.current_user.id,
                action="planning_capacity_settings_saved",
                entity="planning_capacity_setting",
                entity_id=row.id,
                meta_data={"site_id": str(row.site_id), "revision": row.revision},
            )
        )
        db_session.commit()
    except ValueError as exc:
        return _planning_error(exc)
    return jsonify({"setting": setting_dict(row)})
