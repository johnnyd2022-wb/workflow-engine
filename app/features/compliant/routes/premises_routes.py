"""Manage Customs licences and their dated physical coverage (7.1c)."""

from uuid import UUID

from flask import Blueprint, g, jsonify, render_template
from sqlalchemy.exc import IntegrityError

from app.core.db import db_session
from app.core.db.models.audit_log import AuditLog
from app.core.security.permissions import requires_auth, requires_org_scope
from app.features.compliant.modules.nz_alcohol import premises
from app.features.compliant.routes.page_routes import _nz_alcohol_template_context
from app.features.compliant.routes.register_payloads import CustomsCoverageInput, CustomsLicenceInput
from app.utils.request_validation import InvalidInputError, read_json

premises_bp = Blueprint("compliant_premises", __name__, template_folder="../frontend/templates")


def _org():
    return UUID(str(g.current_org_id))


@premises_bp.get("/compliant/nz-alcohol/premises")
@requires_auth
@requires_org_scope
def premises_page():
    return render_template("compliant/premises.html", **_nz_alcohol_template_context())


@premises_bp.get("/api/compliant/nz-alcohol/premises")
@requires_auth
@requires_org_scope
def get_premises():
    return jsonify(premises.overview(db_session, _org()))


def _create(kind, service, schema):
    try:
        row = service(db_session, _org(), read_json(schema).model_dump(mode="json"))
        db_session.add(
            AuditLog(
                org_id=_org(),
                user_id=g.current_user.id,
                action=f"customs_{kind}_created",
                entity=f"customs_{kind}",
                entity_id=row.id,
            )
        )
        db_session.commit()
    except InvalidInputError as exc:
        return exc.response()
    except ValueError as exc:
        db_session.rollback()
        return jsonify({"error": str(exc)}), 400
    except IntegrityError:
        db_session.rollback()
        return jsonify({"error": "This record conflicts with existing Customs coverage or licence details"}), 409
    return jsonify(premises.record_dict(row)), 201


@premises_bp.post("/api/compliant/nz-alcohol/cca-licences")
@requires_auth
@requires_org_scope
def add_licence():
    return _create("licence", premises.add_licence, CustomsLicenceInput)


@premises_bp.post("/api/compliant/nz-alcohol/cca-coverage")
@requires_auth
@requires_org_scope
def add_coverage():
    return _create("coverage", premises.add_coverage, CustomsCoverageInput)
