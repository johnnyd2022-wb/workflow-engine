"""Explicit food registrations and covered activities, independent of Core stock."""

from datetime import date
from uuid import UUID

from flask import Blueprint, g, jsonify, render_template, request
from sqlalchemy.exc import IntegrityError

from app.core.db import db_session
from app.core.db.models.audit_log import AuditLog
from app.core.security.permissions import requires_auth, requires_org_scope
from app.features.compliant.modules.nz_alcohol import food_registrations
from app.features.compliant.routes.page_routes import _nz_alcohol_template_context

food_registration_bp = Blueprint("compliant_food_registrations", __name__, template_folder="../frontend/templates")


def _org():
    return UUID(str(g.current_org_id))


@food_registration_bp.get("/compliant/nz-alcohol/food-registrations")
@requires_auth
@requires_org_scope
def page():
    return render_template("compliant/food_registrations.html", **_nz_alcohol_template_context())


@food_registration_bp.get("/api/compliant/food-registrations")
@requires_auth
@requires_org_scope
def get_registrations():
    return jsonify(food_registrations.overview(db_session, _org()))


def _create(service, entity):
    try:
        row = service(db_session, _org(), request.get_json(silent=True))
        db_session.add(
            AuditLog(
                org_id=_org(), user_id=g.current_user.id, action=f"{entity}_created", entity=entity, entity_id=row.id
            )
        )
        db_session.commit()
    except ValueError as exc:
        db_session.rollback()
        return jsonify({"error": str(exc)}), 400
    except IntegrityError:
        db_session.rollback()
        return jsonify({"error": "This registration or activity scope conflicts with existing records"}), 409
    return jsonify(food_registrations.record_dict(row)), 201


@food_registration_bp.post("/api/compliant/food-registrations")
@requires_auth
@requires_org_scope
def add_registration():
    return _create(
        lambda db, org, data: food_registrations.add_registration(db, org, data, date.today()), "food_registration"
    )


@food_registration_bp.post("/api/compliant/food-registrations/coverage")
@requires_auth
@requires_org_scope
def add_scope():
    return _create(food_registrations.add_scope, "food_registration_scope")
