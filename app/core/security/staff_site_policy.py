"""Fail-closed endpoint coverage for selected-site staff.

The registry is an audit inventory, not proof that routes can safely return site data.
Selected-site assignment remains unavailable until the operation guards are integrated.
New/unclassified endpoints are denied independently of the ordinary permission policy.
"""

from flask import g, jsonify, request

from app.core.db import db_session
from app.core.security.staff_site_endpoint_registry import ENDPOINT_COVERAGE
from app.core.security.staff_site_roles import SELECTED_SITE_ROLES_ACTIVE
from app.core.security.staff_site_scope import load_staff_site_scope

# Authentication and immutable assets only. The ordinary RBAC PUBLIC classification
# includes /auth/me and broad serve_* handlers; it is not a site-data safety contract.
PUBLIC_REQUESTS = frozenset(
    {
        ("auth.login", "POST"),
        ("auth.signup", "POST"),
        ("auth.logout", "POST"),
        ("auth.verify_two_factor", "POST"),
        ("auth.check_password_policy", "POST"),
        ("auth.accept_invite", "POST"),
        ("invite.accept_invite_page", "GET"),
        ("static", "GET"),
        ("planning.static", "GET"),
        ("core.static", "GET"),
        ("healthcheck", "GET"),
        ("favicon", "GET"),
        ("ingest_faro_telemetry", "POST"),
        ("ingest_posthog_telemetry", "GET"),
        ("ingest_posthog_telemetry", "POST"),
    }
)


def coverage_for(endpoint, method):
    return ENDPOINT_COVERAGE.get((endpoint, "GET" if method == "HEAD" else method), "unclassified")


def setup_staff_site_policy(app):
    @app.before_request
    def enforce_staff_site_policy():
        g.staff_site_scope = None
        user = getattr(g, "current_user", None)
        if user is None or not request.endpoint:
            return None
        method = "GET" if request.method == "HEAD" else request.method
        if (request.endpoint, method) in PUBLIC_REQUESTS:
            return None
        scope = load_staff_site_scope(db_session(), g.current_org_id, user.id)
        g.staff_site_scope = scope
        if scope.mode == "all":
            return None
        # No reviewed site-sensitive handler has been released yet. A code-gate flip
        # alone cannot grant access: every registry entry is still blocked.
        classification = coverage_for(request.endpoint, request.method)
        code = "site_scope_invalid" if scope.mode == "deny" else "site_scope_not_available"
        if scope.mode == "selected" and SELECTED_SITE_ROLES_ACTIVE and classification == "scoped":
            # Future handlers require subject authorization; none are registered here.
            return None
        return jsonify(
            {
                "error": "Access with this site's role is not available. Ask an admin to use an all-sites role.",
                "code": code,
            }
        ), 403

    @app.teardown_request
    def clear_staff_site_scope(_error):
        # g is request-local; explicit cleanup also covers test/reused app contexts.
        g.pop("staff_site_scope", None)
