"""
Hardened tenant context middleware for multi-tenant support.

Rules:
- Only use authenticated user_id from session (no X-Org-Id header).
- Derive tenant/org from the user record (user.org_id).
- Populate safe primitives in `g` for templates and frontend (/auth/me).
- Abort early on invalid or inactive users or missing tenant.
"""

from uuid import UUID, uuid4

from flask import abort, g, request, session
from werkzeug.exceptions import HTTPException

from app.core.db import db_session
from app.core.db.repositories.organisation_repo import OrganisationRepository
from app.core.db.repositories.user_repo import UserRepository
from app.core.security.tenant_scope import activate_request_org_id, clear_request_org_id, unscoped
from app.observability import get_logger

LOGGER = get_logger(__name__)

# Public endpoints that do not require tenant context
PUBLIC_ENDPOINTS = {
    "auth.login",
    "auth.signup",
    "auth.verify_two_factor",  # 2FA verification during login (pending session only)
    "auth.cancel_2fa",  # Cancel pending 2FA session (no auth required)
    "healthcheck",
    "ingest_faro_telemetry",
    "ingest_posthog_telemetry",
    "static",
}


def setup_tenant_context(app):
    @app.before_request
    def load_tenant_context():
        # Clear any leftover tenant scope FIRST, before this request's own bootstrapping
        # lookups (get_user_by_id below) run. Without this, a request sharing a reused/
        # borrowed Flask app context with a PRIOR request (see tenant_scope.py's module
        # docstring -- this codebase's own test fixtures do this, e.g. test_org_routes.py's
        # two_org_world wraps two different users' logins in one `with app.app_context():`)
        # would have its own user lookup silently filtered by the PREVIOUS request's org,
        # since the global filter (tenant_filter.py) is still active from that request at the
        # exact moment this one starts -- before this request has had any chance to activate
        # its own context. Confirmed empirically: test_org_routes.py's second client's login
        # succeeds (the login endpoint is public) but its first authenticated request then
        # 403s with "unknown_or_inactive_user_attempt", because get_user_by_id ran under the
        # first client's still-active org filter.
        clear_request_org_id()

        # Unique ID for this HTTP request — shared by all events emitted during it
        g.correlation_id = uuid4()

        # Safe defaults
        g.current_user = None
        g.current_org = None
        g.current_org_id = None
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
            LOGGER.warning("invalid_session_user_id_uuid")
            abort(403, "Invalid session")

        db = db_session()
        try:
            # Load user
            user_repo = UserRepository(db)
            # Resolving a session's user is the one query that must happen before an
            # organisation can be known. Mark it explicitly unscoped rather than
            # relying on the filter's fail-open fallback (and its warning log).
            with unscoped():
                user = user_repo.get_user_by_id(user_uuid)
            if not user or not getattr(user, "is_active", False):
                LOGGER.warning("unknown_or_inactive_user_attempt", user_id=str(user_uuid))
                # A deleted/deactivated account leaves a valid-but-stale cookie in
                # the browser. End that session so the next request is anonymous,
                # then use the existing 401 handler to return the normal re-login
                # response instead of converting this expected state into a 500.
                session.clear()  # nosemgrep: bize-session-clear-without-rotate
                session.modified = True
                abort(401, "Session expired or account is unavailable")

            # Load organisation
            org_repo = OrganisationRepository(db)
            org = org_repo.get_org_by_id(user.org_id)
            if not org:
                LOGGER.error("user_belongs_to_missing_organisation", user_id=str(user_uuid))
                abort(403, "Invalid organisation")

            # Populate g: lightweight primitives + ORM objects
            g.current_user = user
            g.current_org = org
            # Backwards-compatible alias used by org routes / decorators.
            g.current_org_id = org.id

            # Activate the global ORM tenant filter (app/core/db/tenant_filter.py) for the
            # rest of this request. Paired with clear_request_org_id() in teardown_appcontext
            # below, NOT a per-request Token reset -- see tenant_scope.py's module docstring
            # for why: Flask reuses this app context (instead of pushing a fresh one) when a
            # request runs inside an already-active app_context() for the same app, which
            # this codebase's own test fixtures do (e.g. tests/test_wastage.py's app_client).
            # A Token-based reset silently breaks in that scenario; unconditional clear does not.
            activate_request_org_id(org.id)

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

        except HTTPException:
            # abort() raises an HTTPException. It is an intentional response, not a
            # middleware failure, so it must not be logged as an error or rewritten
            # to a 500 by the broad exception handler below.
            raise
        except Exception:
            LOGGER.exception("failed_to_load_tenant_context")
            abort(500, "Failed to load tenant context")

    @app.after_request
    def clear_tenant_context(response):
        # The primary clear point, not teardown_appcontext below: after_request fires once
        # per REQUEST regardless of app-context reuse (see tenant_scope.py's module
        # docstring), so this is what actually stops a stale org_id from leaking into
        # whatever runs next on a shared/reused app context -- including, confirmed while
        # building this, a TEST's own cross-org fixture cleanup and assertion queries
        # running immediately after the last `client.get(...)`/`client.post(...)` call
        # inside a `with app.app_context():` block. Clearing only in teardown_appcontext
        # left those queries silently scoped to whichever org's request happened to run
        # last, instead of seeing everything the way un-scoped test code expects to.
        clear_request_org_id()
        return response

    @app.teardown_appcontext
    def close_db_session(error):
        # Belt-and-braces: covers exception paths that skip after_request, and the
        # eventual pop of a manually-pushed/reused app context.
        clear_request_org_id()
        db_session.remove()
