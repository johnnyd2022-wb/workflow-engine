"""
Hardened tenant context middleware for multi-tenant support.

Rules:
- Only use authenticated user_id from session (no X-Org-Id header).
- Derive tenant/org from the user record (user.org_id).
- Populate safe primitives in `g` for templates and frontend (/auth/me).
- Abort early on invalid or inactive users or missing tenant.
"""

import hmac
from uuid import UUID, uuid4

from flask import abort, g, jsonify, request, session
from werkzeug.exceptions import HTTPException

from app.core.db import db_session
from app.core.db.repositories.organisation_repo import OrganisationRepository
from app.core.db.repositories.user_repo import UserRepository
from app.core.security.auth_service import auth_stamp
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
    # GL-C01/C02: pricing, terms and privacy are readable with no session, or an expired one.
    "legal.pricing",
    "legal.terms",
    "legal.privacy",
    "ingest_faro_telemetry",
    "ingest_posthog_telemetry",
    "static",
    # Public MCP 8.2b: the OAuth endpoints an assistant calls with no session at all. They never
    # load a session user (a cookie must not put a different organisation's scope on a token
    # exchange) and never read a bearer token.
    "oauth.metadata",
    "oauth.register",
    "oauth.token",
    "oauth.revoke",
}


def _json_response(status: int, body: dict, headers: dict | None = None):
    response = jsonify(body)
    response.status_code = status
    for name, value in (headers or {}).items():
        response.headers[name] = value
    return response


# Headers Cloudflare sets on every request it forwards to the origin; a client cannot strip them
# through the edge. The MCP container calls the app over the private Docker network, so its
# requests never carry them (design review S1, spec "Bearer path").
EDGE_HEADERS = ("CF-Connecting-IP", "CF-Ray")


def _came_through_edge() -> bool:
    return any(request.headers.get(name) is not None for name in EDGE_HEADERS)


def _authenticate_bearer(raw_token: str):
    """Resolve an assistant's bearer token into the request's user and organisation (spec "Bearer
    path"). Returns a response to send instead of running the route, or ``None`` on success."""
    from app.features.mcp_oauth.services.bearer_auth import WWW_INVALID_TOKEN, BearerRejectedError, authenticate
    from app.utils.config_loader import config

    if config.mcp_bearer_internal_only and _came_through_edge():
        # A token is only good from the MCP server. Refused before it is looked up, so the edge
        # can't be used to probe which tokens exist; the answer is the same as for a bad token.
        LOGGER.info("mcp.bearer_from_edge", path=request.path, method=request.method)
        return _json_response(401, {"error": "invalid_token"}, {"WWW-Authenticate": WWW_INVALID_TOKEN})

    db = db_session()
    try:
        principal = authenticate(db, raw_token)
    except BearerRejectedError as rejected:
        LOGGER.info("mcp.bearer_rejected", reason=rejected.reason, status=rejected.status)
        return _json_response(rejected.status, {"error": rejected.error}, rejected.headers)
    except Exception:
        db.rollback()
        LOGGER.exception("failed_to_authenticate_bearer")
        return _json_response(500, {"error": "server_error"})

    user, org = principal.user, principal.org
    g.current_user = user
    g.current_org = org
    g.current_org_id = org.id
    activate_request_org_id(org.id)
    g.user_id = str(user.id)
    g.user_email = getattr(user, "email", None)
    g.user_role = getattr(user, "role", None).value if getattr(user, "role", None) else None
    g.org_id = str(org.id)
    g.org_name = getattr(org, "name", None)
    g.org_status = getattr(org, "status", None).value if getattr(org, "status", None) else None
    g.auth_via = "mcp"
    g.mcp_scope = principal.scope
    g.mcp_client_id = principal.client_id
    g.mcp_grant_id = str(principal.grant.id)
    return None


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
        # How this request was authenticated: "session", "mcp" (an assistant's bearer token), or
        # None. The access-policy hook narrows an "mcp" request to read-only routes.
        g.auth_via = None
        g.mcp_scope = None
        g.mcp_client_id = None
        g.mcp_grant_id = None

        if not request.endpoint:
            return

        # Skip static and public endpoints
        if request.endpoint in PUBLIC_ENDPOINTS or request.endpoint.endswith(".static"):
            return

        # Session must contain user_id
        raw_user_id = session.get("user_id")
        if not raw_user_id:
            # No session user. An assistant may be calling with a bearer token (public MCP 8.2b).
            # A request that carries a session user is always a session request, whatever else it
            # carries, so a token can never be used to step around the session's CSRF check.
            from app.features.mcp_oauth.services.bearer_auth import parse_bearer

            raw_token = parse_bearer(request.headers.get("Authorization"))
            if raw_token is not None:
                return _authenticate_bearer(raw_token)
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

            # GL-A02: a session signed in before the password last changed is over. A session with no
            # stamp predates this check, and nothing on the server says which password it signed in
            # with, so it ends too: deploying this signs everyone out once.
            stamp = auth_stamp(user.password_hash)
            current = session.get("auth_stamp")
            if current is None or not hmac.compare_digest(str(current), stamp):
                LOGGER.info(
                    "session_ended_by_password_change" if current is not None else "session_ended_unstamped",
                    user_id=str(user_uuid),
                )
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
            g.auth_via = "session"

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
    def log_mcp_request(response):
        # One event per assistant request: who, which organisation, which app, which route, and the
        # outcome. Never the token, and never the query string's values.
        if getattr(g, "auth_via", None) == "mcp":
            LOGGER.info(
                "mcp.request",
                user_id=g.user_id,
                org_id=g.org_id,
                client=g.mcp_client_id,
                grant_id=g.mcp_grant_id,
                endpoint=request.endpoint,
                method=request.method,
                status=response.status_code,
            )
        return response

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
