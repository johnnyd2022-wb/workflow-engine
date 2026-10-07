"""Admin sign-in: Google only, and only for the people on the allow-list.

The Google flow is the customer app's (authorization code, PKCE, a verified ID token:
`app.features.google_sign_in.oidc`). What differs is what happens to the verified
identity: there is no account to look up, only a short list of permitted addresses.

Access is denied by default. `require_admin` runs before every request and lets through
only the endpoints named in `PUBLIC_ENDPOINTS`; a new route is protected without having
to remember a decorator.
"""

from __future__ import annotations

import hmac
import secrets
import time

from flask import Blueprint, current_app, g, redirect, render_template, request, session, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from app.admin_site.settings import IDLE_MINUTES, SESSION_HOURS, AdminSettings
from app.features.google_sign_in.oidc import exchange_verified_identity, google_client
from app.features.google_sign_in.service import authoritative_email
from app.observability import get_logger

logger = get_logger(__name__)
limiter = Limiter(key_func=get_remote_address)
admin_auth_bp = Blueprint("admin_auth", __name__)

FLOW_SECONDS = 600
PUBLIC_ENDPOINTS = frozenset(
    {"admin_auth.sign_in", "admin_auth.start", "admin_auth.callback", "healthcheck", "static", "shared_style"}
)
REJECTED = "That Google account can't use the biz-e admin site."


def settings() -> AdminSettings:
    return current_app.extensions["admin_settings"]


def permitted_email(claims: dict, admin_settings: AdminSettings) -> str | None:
    """The allow-listed address these verified claims prove, or None.

    Google will issue a token for any address someone has verified with a personal Google
    account, so by default the address must also be one Google is the authority for: a
    Workspace domain (the `hd` claim) or gmail.com.
    """
    email = claims.get("email")
    if claims.get("email_verified") is not True or not admin_settings.permits(email):
        return None
    if admin_settings.require_authoritative_email and not authoritative_email(claims):
        return None
    return email.strip().lower()


def _start_session(email: str, subject: str) -> None:
    session.clear()
    session.permanent = True
    now = time.time()
    session.update(admin_email=email, admin_sub=subject, signed_in_at=now, last_seen_at=now)


def _end_session() -> None:
    session.clear()
    session.permanent = True


def current_admin() -> str | None:
    """The signed-in admin's email, re-checked against the allow-list and both time limits."""
    email = session.get("admin_email")
    now = time.time()
    signed_in_at = session.get("signed_in_at")
    last_seen_at = session.get("last_seen_at")
    if (
        not settings().permits(email)
        or not isinstance(signed_in_at, (int, float))
        or not isinstance(last_seen_at, (int, float))
        or now - signed_in_at > SESSION_HOURS * 3600
        or now - last_seen_at > IDLE_MINUTES * 60
    ):
        return None
    return email


def require_admin():
    """before_request for the whole app: no admin session, no page."""
    if request.endpoint in PUBLIC_ENDPOINTS:
        return None
    email = current_admin()
    if email is None:
        if "admin_email" in session:
            _end_session()
        if request.method == "GET":
            return redirect(url_for("admin_auth.sign_in"))
        return render_template("admin/sign_in.html", error="Your session ended. Sign in again."), 401
    session["last_seen_at"] = time.time()
    g.admin_email = email
    return None


@admin_auth_bp.route("/sign-in", methods=["GET"])
def sign_in():
    if current_admin():
        return redirect(url_for("admin.organisations"))
    return render_template("admin/sign_in.html")


@admin_auth_bp.route("/auth/google/start", methods=["POST"])
@limiter.limit("10 per minute")
def start():
    # Keep only one outstanding flow. CSRF protects this POST; Authlib additionally
    # saves and verifies state, nonce, redirect URI and the S256 code verifier.
    for key in list(session):
        if key.startswith("_state_google_"):
            session.pop(key, None)
    state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    session["google_flow"] = {"state": state, "nonce": nonce, "created_at": time.time()}
    return google_client().authorize_redirect(
        current_app.config["GOOGLE_REDIRECT_URI"], state=state, nonce=nonce, prompt="select_account"
    )


@admin_auth_bp.route("/auth/google/callback", methods=["GET"])
@limiter.limit("20 per minute")
def callback():
    flow = session.pop("google_flow", None)
    state = request.args.get("state", "")
    try:
        if (
            not isinstance(flow, dict)
            or not state
            or not hmac.compare_digest(state, flow.get("state", ""))
            or time.time() - flow.get("created_at", 0) > FLOW_SECONDS
        ):
            raise ValueError("stale or mismatched sign-in flow")
        claims = exchange_verified_identity(flow["nonce"])
        email = permitted_email(claims, settings())
        if email is None:
            # A verified identity that is not on the list: worth seeing in the logs.
            logger.warning("admin_sign_in_refused", email=str(claims.get("email"))[:255], ip=get_remote_address())
            _end_session()
            return render_template("admin/sign_in.html", error=REJECTED), 403
        _start_session(email, claims["sub"])
        logger.info("admin_signed_in", email=email, ip=get_remote_address())
        return redirect(url_for("admin.organisations"))
    except Exception as exc:
        # Provider errors can contain token/code/credentials. Never log their text.
        logger.warning("admin_sign_in_failed", reason=type(exc).__name__)
        _end_session()
        return render_template("admin/sign_in.html", error="Sign-in was not completed. Try again."), 400
    finally:
        for key in list(session):
            if key.startswith("_state_google_"):
                session.pop(key, None)


@admin_auth_bp.route("/sign-out", methods=["POST"])
def sign_out():
    logger.info("admin_signed_out", email=session.get("admin_email"))
    _end_session()
    return redirect(url_for("admin_auth.sign_in"))
