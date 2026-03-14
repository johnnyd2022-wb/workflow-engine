"""
Hardened tenant context middleware for multi-tenant support.

Rules:
- Only use authenticated user_id from session (no X-Org-Id header).
- Derive tenant/org from the user record (user.org_id).
- Populate safe primitives in `g` for templates and frontend (/auth/me).
- Abort early on invalid or inactive users or missing tenant.
"""

from uuid import UUID

from flask import abort, current_app, g, request, session

from app.core.db import db_session
from app.core.db.repositories.organisation_repo import OrganisationRepository
from app.core.db.repositories.user_repo import UserRepository

# Public endpoints that do not require tenant context
PUBLIC_ENDPOINTS = {
    "auth.login",
    "auth.signup",
    "auth.verify_two_factor",  # 2FA verification during login (pending session only)
    "auth.cancel_2fa",  # Cancel pending 2FA session (no auth required)
    "healthcheck",
    "static",
}


def setup_tenant_context(app):
    @app.before_request
    def load_tenant_context():
        # Safe defaults
        g.current_user = None
        g.current_org = None
        g.user_id = None
        g.org_id = None
        g.user_email = None
        g.org_name = None
        g.user_role = None
        g.org_status = None

        if not request.endpoint:
            return

        # Skip static and public endpoints
        if request.endpoint in PUBLIC_ENDPOINTS or request.endpoint.endswith(".static"):
            return

        # Session must contain user_id
        raw_user_id = session.get("user_id")
        if not raw_user_id:
            # Unauthenticated request — nothing to load
            return

        # Validate UUID format
        try:
            user_uuid = UUID(raw_user_id)
        except Exception:
            current_app.logger.warning("Invalid user_id UUID in session")
            abort(403, "Invalid session")

        db = db_session()
        try:
            # Load user
            user_repo = UserRepository(db)
            user = user_repo.get_user_by_id(user_uuid)
            if not user or not getattr(user, "is_active", False):
                current_app.logger.warning("Unknown or inactive user attempt", extra={"user_id": str(user_uuid)})
                abort(403, "Access denied")

            # Load organisation
            org_repo = OrganisationRepository(db)
            org = org_repo.get_org_by_id(user.org_id)
            if not org:
                current_app.logger.error("User belongs to missing organisation", extra={"user_id": str(user_uuid)})
                abort(403, "Invalid organisation")

            # Populate g: lightweight primitives + ORM objects
            g.current_user = user
            g.current_org = org

            g.user_id = str(user.id)
            g.user_email = getattr(user, "email", None)
            g.user_role = getattr(user, "role", None).value if getattr(user, "role", None) else None

            g.org_id = str(org.id)
            g.org_name = getattr(org, "name", None)
            g.org_status = getattr(org, "status", None).value if getattr(org, "status", None) else None

            # Optional: cache lightweight primitives in session for performance
            # CRITICAL: Only cache safe, non-sensitive data (no passwords, tokens, or secrets)
            # This cache is used for performance optimization and does not contain sensitive information
            session["_user_cache"] = {
                "user_id": g.user_id,
                "org_id": g.org_id,
                "user_email": g.user_email,
                "user_role": g.user_role,
                "org_name": g.org_name,
                "org_status": g.org_status,
            }

        except Exception:
            current_app.logger.exception("Failed to load tenant context")
            abort(500, "Failed to load tenant context")

    @app.teardown_appcontext
    def close_db_session(error):
        db_session.remove()
