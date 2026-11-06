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
    return _plan_response(rows, changed)


def _plan_response(rows, changed, **extra):
    body = {"batches": [batches.batch_dict(row) for row in rows], **extra}
    if not rows:
        # Stock on hand and batches already planned meet it: nothing new to make.
        body.update(covered=True, message="Covered by stock on hand")
    return jsonify(body), 201 if changed else 200


@planning_bp.post("/api/core/planner/demand/sync")
@requires_auth
@requires_org_scope
def sync_planning_demand():
    """Bring contract-order demand up to date. The planner page calls it on load."""
    from app.features.planning import contract_sync

    try:
        result = contract_sync.sync_contract_demand(db_session, _org_id())
        for action, row in result["changes"]:
            _audit(action, row)
        db_session.commit()
    except ValueError as exc:
        return _planning_error(exc)
    return jsonify(contract_sync.summary(result))


def _site_arg(value):
    return batches.resolve_planning_site(db_session, g.current_org, value or None)


@planning_bp.get("/api/core/planner/cover")
@requires_auth
@requires_org_scope
def get_stock_cover():
    from app.features.planning import forecast_service

    try:
        weeks = forecast_service.window_weeks(request.args.get("weeks"))
        site = _site_arg(request.args.get("site_id"))
        result = forecast_service.cover(db_session, _org_id(), site, today=date.today(), weeks=weeks)
    except ValueError as exc:
        return _planning_error(exc)
    # Which site this is, and the others to choose from when the business runs several.
    result["site_id"] = str(site.id) if site else None
    result["sites"] = _planning_sites()
    return jsonify(result)


def _planning_sites():
    from app.core.db.models.site import Site

    if not g.current_org.multiple_sites_enabled:
        return []
    rows = (
        db_session.query(Site)
        .filter(Site.org_id == _org_id(), Site.is_active.is_(True))
        .order_by(Site.is_default.desc(), Site.name)
        .all()
    )
    return [{"id": str(row.id), "name": row.name, "is_default": bool(row.is_default)} for row in rows]


@planning_bp.post("/api/core/planner/targets")
@requires_auth
@requires_org_scope
def save_stock_target():
    from app.features.planning import forecast_service

    data = request.get_json(silent=True)
    try:
        site = _site_arg(data.get("site_id") if isinstance(data, dict) else None)
        row = forecast_service.save_target(db_session, _org_id(), site, data)
        db_session.add(
            AuditLog(
                org_id=_org_id(),
                user_id=g.current_user.id,
                action="planning_stock_target_saved" if row else "planning_stock_target_cleared",
                entity="planning_stock_target",
                entity_id=row.id if row else None,
                meta_data={
                    "source_output_id": str(data["source_output_id"]),
                    "weeks_of_cover": str(row.weeks_of_cover) if row else None,
                },
            )
        )
        db_session.commit()
    except ValueError as exc:
        return _planning_error(exc)
    return jsonify({"target": {"weeks_of_cover": format(row.weeks_of_cover.normalize(), "f")} if row else None})


@planning_bp.post("/api/core/planner/cover/plan")
@requires_auth
@requires_org_scope
def plan_stock_cover():
    """'Plan it' on a stock-cover suggestion: one forecast demand, planned in the same request."""
    from app.features.planning import forecast_service

    try:
        demand, rows, changed = forecast_service.plan_forecast(
            db_session,
            _org_id(),
            request.get_json(silent=True),
            request.headers.get("Idempotency-Key"),
            today=date.today(),
        )
        if changed:
            _audit("planning_demand_created", demand)
            for row in rows:
                _batch_audit("planning_batch_created", row)
        db_session.commit()
    except ValueError as exc:
        return _planning_error(exc)
    return _plan_response(rows, changed, demand=service.demand_dict(demand))


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
