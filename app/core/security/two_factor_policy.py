"""Owners and admins must use two-factor authentication (plan item 0.2).

An admin who signs in without 2FA still gets a session, but until they enrol every
authenticated request outside the enrolment flow is refused: API calls get a 403 with
``code: two_factor_enrollment_required``, and page loads are sent to Settings, which
opens enrolment. The check reads the live user row on every request, so it also covers
sessions that existed before this policy shipped and users promoted to admin later.

``REQUIRE_ADMIN_2FA`` (set in ``app_factory``) can only be switched off in the local and
test environments, where scripted admin logins (pytest fixtures, the Whistlebird replay)
have no authenticator to hand.
"""

from flask import current_app, g, jsonify, make_response, redirect, request

from app.core.db.models.user import UserRole
from app.observability import get_logger

logger = get_logger(__name__)

ENROLLMENT_PAGE = "/core/settings?enroll2fa=1"
ENROLLMENT_REQUIRED_CODE = "two_factor_enrollment_required"
ENROLLMENT_REQUIRED_MESSAGE = (
    "Your organisation requires administrators to use two-factor authentication. Set it up in Settings to continue."
)

# What an admin without 2FA can still reach: the enrolment flow, the Settings page that
# hosts it and the account reads that page makes, changing password, and signing out.
_ALLOWED_ENDPOINTS = frozenset(
    {
        "auth.enroll_2fa",
        "auth.enable_2fa",
        "auth.cancel_2fa",
        "auth.get_current_user",
        "auth.logout",
        "auth.manage_user_settings",
        "auth.manage_session_timeout",
        "auth.check_password_policy",
        "auth.change_password",
        "core.settings",
    }
)


# Environments where scripted admin logins may switch the policy off. Everywhere else it
# is on, whatever the ini says (same fail-closed allow-list as auth rate-limit relaxing).
_OPT_OUT_ENVIRONMENTS = frozenset({"local", "test"})


def resolve_require_admin_2fa(environment: str, configured: bool) -> bool:
    """The effective policy for ``environment`` given the ini's ``require_admin_2fa``."""
    if (environment or "").strip().lower() not in _OPT_OUT_ENVIRONMENTS:
        return True
    return bool(configured)


def two_factor_required(user) -> bool:
    """Whether the policy applies to ``user`` (enrolled or not)."""
    if user is None or not current_app.config.get("REQUIRE_ADMIN_2FA", True):
        return False
    return getattr(user, "role", None) == UserRole.ADMIN


def enrollment_required(user) -> bool:
    """Whether ``user`` must enrol in 2FA before doing anything else."""
    return two_factor_required(user) and not bool(getattr(user, "two_factor_enabled", False))


def _is_static(endpoint: str) -> bool:
    last = endpoint.rsplit(".", 1)[-1]
    return last == "static" or last.startswith("serve_")


def setup_two_factor_policy(app) -> None:
    """Register the enforcement hook. Must run after tenant context loads ``g.current_user``."""

    @app.before_request
    def enforce_admin_two_factor():
        user = getattr(g, "current_user", None)
        endpoint = request.endpoint
        if user is None or not endpoint or not enrollment_required(user):
            return None
        if endpoint in _ALLOWED_ENDPOINTS or _is_static(endpoint):
            return None

        logger.info("admin_2fa_enrollment_required", endpoint=endpoint, user_id=str(user.id))
        if request.headers.get("HX-Request"):
            # HTMX swaps would drop a redirect's page into the content area; ask for a
            # full navigation instead.
            response = make_response("", 200)
            response.headers["HX-Redirect"] = ENROLLMENT_PAGE
            return response
        is_api = request.path.startswith(("/api/", "/auth/")) or request.is_json
        if request.method == "GET" and not is_api and request.accept_mimetypes.accept_html:
            return redirect(ENROLLMENT_PAGE)
        return (
            jsonify(
                {"error": ENROLLMENT_REQUIRED_MESSAGE, "code": ENROLLMENT_REQUIRED_CODE, "action": ENROLLMENT_PAGE}
            ),
            403,
        )
