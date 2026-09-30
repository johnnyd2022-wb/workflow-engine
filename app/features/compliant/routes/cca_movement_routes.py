"""Read the per-CCA physical movement register; this API cannot lodge or move stock."""

from datetime import date
from uuid import UUID

from flask import Blueprint, g, jsonify, request

from app.core.db import db_session
from app.core.security.permissions import requires_auth, requires_org_scope
from app.features.compliant.modules.nz_alcohol.movement_excise import cca_movement_register, cca_period_review

cca_movement_bp = Blueprint("compliant_cca_movements", __name__)


@cca_movement_bp.get("/api/compliant/nz-alcohol/excise/cca-movements")
@requires_auth
@requires_org_scope
def get_register():
    try:
        start, end = date.fromisoformat(request.args.get("start")), date.fromisoformat(request.args.get("end"))
        result = cca_movement_register(db_session, UUID(str(g.current_org_id)), start, end)
    except (ValueError, TypeError) as exc:
        return jsonify({"error": str(exc) or "Choose valid movement dates"}), 400
    return jsonify(result)


@cca_movement_bp.get("/api/compliant/nz-alcohol/excise/cca-period-review")
@requires_auth
@requires_org_scope
def get_period_review():
    try:
        start = date.fromisoformat(request.args.get("start"))
        end = date.fromisoformat(request.args.get("end"))
        licence_id = UUID(request.args.get("licence_id"))
        result = cca_period_review(db_session, UUID(str(g.current_org_id)), licence_id, start, end)
    except (ValueError, TypeError) as exc:
        return jsonify({"error": str(exc) or "Choose a valid CCA and movement period"}), 400
    return jsonify(result)
