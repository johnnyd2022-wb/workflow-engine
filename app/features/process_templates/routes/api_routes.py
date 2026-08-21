"""JSON API for the industry process template catalogue."""

from __future__ import annotations

from uuid import UUID

from flask import Blueprint, g, jsonify, request

from app.core.db import db_session
from app.core.security.permissions import requires_auth
from app.features.process_templates.services import process_templates_service as service

api_bp = Blueprint("process_templates_api", __name__)


def _org_id() -> UUID:
    return UUID(g.org_id)


@api_bp.route("/api/core/process-templates", methods=["GET"])
@requires_auth
def list_process_templates():
    org_id = _org_id()
    family_filter = request.args.get("family") or None
    result = service.list_catalog(db_session(), org_id, family_filter)
    service.emit_catalog_viewed(db_session(), org_id)
    return jsonify(result), 200


@api_bp.route("/api/core/process-templates/<template_id>", methods=["GET"])
@requires_auth
def get_process_template(template_id: str):
    org_id = _org_id()
    detail = service.get_template_detail(db_session(), org_id, template_id)
    if detail is None:
        return jsonify({"error": "Template not found"}), 404
    service.emit_template_selected(db_session(), org_id, template_id)
    return jsonify(detail), 200


@api_bp.route("/api/core/process-templates/<template_id>/copy", methods=["POST"])
@requires_auth
def copy_process_template(template_id: str):
    org_id = _org_id()
    process = service.copy_template(db_session(), org_id, template_id)
    if process is None:
        return jsonify({"error": "Template not found"}), 404
    return jsonify({"process_id": str(process.id)}), 201
