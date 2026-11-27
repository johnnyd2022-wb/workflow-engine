"""Read the per-CCA physical movement register; this API cannot lodge or move stock."""

from datetime import date
from uuid import UUID

from flask import Blueprint, g, jsonify

from app.core.db import db_session
from app.core.security.permissions import requires_auth, requires_org_scope
from app.features.compliant.modules.nz_alcohol.movement_excise import cca_movement_register, cca_period_review
from app.utils.request_validation import InvalidInputError, query_text

cca_movement_bp = Blueprint("compliant_cca_movements", __name__)


def _movement_date(field):
    raw = query_text(field, max_length=10)
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise InvalidInputError({field: "Enter a date like 2026-01-01."}) from None


@cca_movement_bp.get("/api/compliant/nz-alcohol/excise/cca-movements")
@requires_auth
@requires_org_scope
def get_register():
    try:
        start, end = _movement_date("start"), _movement_date("end")
        result = cca_movement_register(db_session, UUID(str(g.current_org_id)), start, end)
    except InvalidInputError as exc:
        return exc.response()
    except ValueError as exc:
        return jsonify({"error": str(exc) or "Choose valid movement dates"}), 400
    return jsonify(result)


@cca_movement_bp.get("/api/compliant/nz-alcohol/excise/cca-period-review")
@requires_auth
@requires_org_scope
def get_period_review():
    try:
        start, end = _movement_date("start"), _movement_date("end")
        raw_licence = query_text("licence_id", max_length=36)
        try:
            licence_id = UUID(raw_licence)
        except ValueError:
            raise InvalidInputError({"licence_id": "Choose a valid Customs licence."}) from None
        result = cca_period_review(db_session, UUID(str(g.current_org_id)), licence_id, start, end)
    except InvalidInputError as exc:
        return exc.response()
    except ValueError as exc:
        return jsonify({"error": str(exc) or "Choose a valid CCA and movement period"}), 400
    return jsonify(result)
