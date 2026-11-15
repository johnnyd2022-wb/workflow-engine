"""MCP settings and connected apps API (public MCP 8.2b backend; the Settings page is 8.2e).

``/api/core/mcp/*``. All of it is session-only: a bearer token reaches none of it, because the
policy rules here name ``users.manage`` or signed-in-only (never a view permission) and a token's
method must be GET (``access_policy.token_access``). ``/me`` is the exception: it answers who the
caller is and what they may read, for a session or a token alike.
"""

from __future__ import annotations

from uuid import UUID

from flask import Blueprint, g, jsonify, request

from app.core.db import db_session
from app.core.security.access_policy import READ_PERMISSIONS, has_permission, permissions_for, role_label_for
from app.core.security.permissions import requires_auth
from app.features.mcp_oauth.services import settings_service
from app.features.mcp_oauth.services.settings_service import SettingsError
from app.observability import get_logger

logger = get_logger(__name__)

mcp_bp = Blueprint("mcp", __name__, url_prefix="/api/core/mcp")

MAX_BODY_BYTES = 16 * 1024


def _can_manage_people() -> bool:
    return has_permission(g.current_user, "users.manage")


@mcp_bp.get("/me")
@requires_auth
def get_me():
    """Who is calling, their organisation, and the read permissions they hold (never any other)."""
    user = g.current_user
    name = " ".join(part for part in (user.first_name, user.last_name) if part) or None
    return jsonify(
        {
            "user": {"id": str(user.id), "name": name, "email": user.email},
            "org": {"id": str(g.current_org_id), "name": g.org_name},
            "role_label": role_label_for(user),
            "permissions": sorted(permissions_for(user) & READ_PERMISSIONS),
            "scope": g.mcp_scope if g.auth_via == "mcp" else None,
            "auth": g.auth_via,
        }
    )


@mcp_bp.get("/settings")
@requires_auth
def get_settings():
    return jsonify(settings_service.get_settings(db_session(), g.current_org_id))


@mcp_bp.put("/settings")
@requires_auth
def update_settings():
    if (request.content_length or 0) > MAX_BODY_BYTES:
        return jsonify({"error": "Request body too large"}), 413
    body = request.get_json(silent=True) if request.is_json else None
    db = db_session()
    try:
        return jsonify(settings_service.update_settings(db, g.current_org_id, g.current_user.id, body))
    except SettingsError as err:
        db.rollback()
        return jsonify({"error": str(err)}), 400


@mcp_bp.get("/grants")
@requires_auth
def list_grants():
    grants = settings_service.list_grants(
        db_session(), g.current_org_id, viewer_id=g.current_user.id, can_manage=_can_manage_people()
    )
    return jsonify({"grants": grants})


@mcp_bp.post("/grants/<grant_id>/revoke")
@requires_auth
def revoke_grant(grant_id: str):
    try:
        parsed = UUID(grant_id)
    except ValueError:
        return jsonify({"error": "Not found"}), 404
    done = settings_service.revoke_grant(
        db_session(), g.current_org_id, parsed, g.current_user, can_manage=_can_manage_people()
    )
    if not done:
        # Someone else's, another organisation's, or already revoked: all the same answer.
        return jsonify({"error": "Not found"}), 404
    return jsonify({"revoked": True})
