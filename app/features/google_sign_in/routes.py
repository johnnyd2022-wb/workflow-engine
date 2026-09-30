"""Google login and password-confirmed account linking in a separate feature slice."""

import hashlib
import hmac
import secrets
import time
from datetime import UTC, datetime
from uuid import UUID

from flask import Blueprint, current_app, g, jsonify, redirect, render_template, request, session
from flask_limiter.util import get_remote_address

from app.api.routes.auth_routes import limiter, rotate_session
from app.core.db import db_session
from app.core.db.models.user import User
from app.core.db.models.user_identity import UserIdentity
from app.core.security.auth_service import AuthService
from app.core.security.people import PeopleError, validate_new_password
from app.core.security.permissions import requires_auth
from app.core.security.two_factor_policy import ENROLLMENT_PAGE, enrollment_required
from app.core.utils.log_action import log_action
from app.features.google_sign_in.oidc import exchange_verified_identity, google_client
from app.features.google_sign_in.service import PROVIDER, GoogleSignInError, assert_account_available, resolve_identity
from app.observability import get_logger

logger = get_logger(__name__)
google_auth_bp = Blueprint("google_auth", __name__, url_prefix="/auth/google", template_folder="frontend")
FLOW_SECONDS = 600


def _data():
    data = request.get_json(silent=True) if request.is_json else request.form
    return data if isinstance(data, dict) or hasattr(data, "get") else {}


def _password_version(user):
    return hashlib.sha256(user.password_hash.encode()).hexdigest()


def _error(
    message="Google sign-in could not be completed. Use your password or contact your administrator.", status=400
):
    if request.is_json:
        return jsonify({"error": message}), status
    return render_template("google_sign_in.html", error=message), status


def _begin(mode, *, user=None, invite_token=None):
    client = google_client()
    # Keep only one outstanding flow. CSRF protects this POST; Authlib additionally
    # saves and verifies state, nonce, redirect URI and the S256 code verifier.
    for key in list(session):
        if key.startswith("_state_google_"):
            session.pop(key, None)
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    flow = {"mode": mode, "state": state, "nonce": nonce, "created_at": time.time()}
    if user is not None:
        flow.update(user_id=str(user.id), org_id=str(user.org_id), password_version=_password_version(user))
    if invite_token:
        flow["invite_token"] = invite_token
    # Even a login initiated while signed in must never silently switch accounts.
    flow["current_user_id"] = session.get("user_id")
    session["google_flow"] = flow
    response = client.authorize_redirect(
        current_app.config["GOOGLE_REDIRECT_URI"], state=state, nonce=nonce, prompt="select_account"
    )
    response.headers["Cache-Control"] = "no-store"
    return response


# Deliberately public authentication entry point; classified PUBLIC in POLICY.
# nosemgrep: route-missing-requires-auth
@google_auth_bp.route("/start", methods=["POST"])
@limiter.limit("10 per minute")
def start():
    try:
        return _begin("login")
    except GoogleSignInError:
        return _error()


# Deliberately public authentication entry point; classified PUBLIC in POLICY.
# nosemgrep: route-missing-requires-auth
@google_auth_bp.route("/invite", methods=["POST"])
@limiter.limit("10 per minute")
def invite():
    from app.api.routes.auth_routes import _pending_invite_user

    token = _data().get("token")
    if not isinstance(token, str) or len(token) > 512:
        return _error()
    db = db_session()
    user = _pending_invite_user(db, token)
    if user is None or session.get("user_id"):
        return _error()
    try:
        assert_account_available(db, user, invited=True)
        return _begin("invite", invite_token=token)
    except GoogleSignInError:
        return _error()


@google_auth_bp.route("/link", methods=["POST"])
@requires_auth
@limiter.limit("5 per minute")
def link():
    user = g.current_user
    password = _data().get("password")
    if not isinstance(password, str) or not AuthService.verify_password(password, user.password_hash):
        return _error("Confirm your current password to link Google.", 401)
    try:
        assert_account_available(db_session(), user)
        return _begin("link", user=user)
    except GoogleSignInError:
        return _error()


# Deliberately public authentication entry point; classified PUBLIC in POLICY.
# nosemgrep: route-missing-requires-auth
@google_auth_bp.route("/callback", methods=["GET"])
@limiter.limit("20 per minute")
def callback():
    flow = session.pop("google_flow", None)
    state = request.args.get("state", "")
    if (
        not isinstance(flow, dict)
        or not state
        or not hmac.compare_digest(state, flow.get("state", ""))
        or time.time() - flow.get("created_at", 0) > FLOW_SECONDS
        or flow.get("current_user_id") != session.get("user_id")
    ):
        return _error()
    db = db_session()
    try:
        claims = exchange_verified_identity(flow["nonce"])
        linking_user = None
        if flow["mode"] == "link":
            if session.get("user_id") != flow.get("user_id") or session.get("org_id") != flow.get("org_id"):
                raise GoogleSignInError("Account changed during linking")
            linking_user = db.query(User).filter_by(id=UUID(flow["user_id"]), org_id=UUID(flow["org_id"])).one_or_none()
            if linking_user is None or not hmac.compare_digest(
                _password_version(linking_user), flow["password_version"]
            ):
                raise GoogleSignInError("Password changed during linking")
        user = resolve_identity(
            db,
            claims,
            linking_user=linking_user,
            invite_token=flow.get("invite_token"),
            current_user_id=flow.get("current_user_id"),
        )
        user.failed_login_attempts = 0
        user.account_locked_until = None
        db.commit()
        if flow["mode"] == "link":
            log_action("google_identity_linked", "user", user.id, None, user.org_id, user.id)
            return redirect("/core/settings?google=linked")
        if flow["mode"] == "invite":
            log_action("accept_invite_google", "user", user.id, None, user.org_id, user.id)
        rotate_session()
        if user.two_factor_enabled:
            session["pending_2fa_user_id"] = str(user.id)
            session["pending_2fa_created_at"] = datetime.now(UTC).isoformat()
            session["pending_auth_method"] = "google"
            session["pending_google_sub"] = claims["sub"]
            return redirect("/auth/google/challenge")
        session.update(AuthService(db).generate_session(user))
        session["session_timeout_minutes"] = user.session_timeout_minutes
        record_google_session(user, claims["sub"])
        return redirect(ENROLLMENT_PAGE if enrollment_required(user) else "/dashboard")
    except Exception as exc:
        db.rollback()
        # Provider errors can contain token/code/credentials. Never log their text.
        logger.warning("google_sign_in_rejected", reason=type(exc).__name__)
        return _error()
    finally:
        for key in list(session):
            if key.startswith("_state_google_"):
                session.pop(key, None)


def validate_pending_google(db, user, subject):
    assert_account_available(db, user)
    identity = (
        db.query(UserIdentity)
        .filter_by(org_id=user.org_id, user_id=user.id, provider=PROVIDER, subject=subject)
        .one_or_none()
    )
    if identity is None:
        raise GoogleSignInError("Google identity was unlinked during sign-in")


def record_google_session(user, subject):
    """Called only after the local second-factor gate completes."""
    session["auth_method"] = "google"
    session["google_sub"] = subject
    session["google_authenticated_at"] = time.time()
    log_action(
        "login_google",
        "user",
        user.id,
        {
            "authentication_method": "google",
            "ip_address": get_remote_address(),
            "user_agent": request.headers.get("User-Agent", "")[:200],
        },
        user.org_id,
        user.id,
    )


# Deliberately public authentication entry point; classified PUBLIC in POLICY.
# nosemgrep: route-missing-requires-auth
@google_auth_bp.route("/challenge", methods=["GET"])
def challenge():
    if session.get("pending_auth_method") != "google" or not session.get("pending_2fa_user_id"):
        return redirect("/?login=1")
    return render_template("google_sign_in.html", requires_2fa=True)


@google_auth_bp.route("/methods", methods=["GET"])
@requires_auth
def methods():
    user = g.current_user
    identities = db_session().query(UserIdentity).filter_by(org_id=user.org_id, user_id=user.id).all()
    return jsonify(
        {
            "google_enabled": current_app.config.get("GOOGLE_SIGN_IN_ENABLED", False),
            "password_available": bool(user.password_hash),
            "identities": [{"provider": i.provider, "email": i.email_at_link} for i in identities],
        }
    )


@google_auth_bp.route("/unlink", methods=["POST"])
@requires_auth
@limiter.limit("5 per minute")
def unlink():
    user = g.current_user
    password = _data().get("password")
    if not isinstance(password, str) or not AuthService.verify_password(password, user.password_hash):
        return _error("Confirm your password before unlinking Google. A password must remain available.", 401)
    db = db_session()
    try:
        assert_account_available(db, user)
        db.query(UserIdentity).filter_by(org_id=user.org_id, user_id=user.id, provider=PROVIDER).delete()
        db.commit()
        for key in ("google_sub", "google_authenticated_at"):
            session.pop(key, None)
        log_action("google_identity_unlinked", "user", user.id, None, user.org_id, user.id)
        return redirect("/core/settings?google=unlinked")
    except GoogleSignInError:
        return _error()


@google_auth_bp.route("/password", methods=["POST"])
@requires_auth
@limiter.limit("5 per minute")
def set_password():
    """Google-only invite accounts may add a recovery password after fresh sign-in."""
    user = g.current_user
    db = db_session()
    identity = db.query(UserIdentity).filter_by(org_id=user.org_id, user_id=user.id, provider=PROVIDER).one_or_none()
    if (
        user.password_hash
        or identity is None
        or session.get("auth_method") != "google"
        or session.get("google_sub") != identity.subject
        or time.time() - session.get("google_authenticated_at", 0) > FLOW_SECONDS
    ):
        return _error("Sign in with Google again before adding a password.", 401)
    data = _data()
    try:
        assert_account_available(db, user)
        password, confirm = data.get("password"), data.get("password_confirm")
        if not isinstance(password, str) or not isinstance(confirm, str) or len(password.encode("utf-8")) > 72:
            raise PeopleError("Use a valid password and matching confirmation")
        validate_new_password(password, confirm)
        user.password_hash = AuthService.hash_password(password)
        db.commit()
        log_action("google_account_password_added", "user", user.id, None, user.org_id, user.id)
        rotate_session()
        session.update(AuthService(db).generate_session(user))
        session["session_timeout_minutes"] = user.session_timeout_minutes
        return redirect("/core/settings?google=password-added")
    except (GoogleSignInError, PeopleError):
        return _error("Use a valid password and matching confirmation.")


@google_auth_bp.app_context_processor
def inject_google_account():
    def google_account():
        user = getattr(g, "current_user", None)
        if user is None:
            return {"linked": None, "password_available": False}
        identity = (
            db_session()
            .query(UserIdentity)
            .filter_by(org_id=user.org_id, user_id=user.id, provider=PROVIDER)
            .one_or_none()
        )
        return {"linked": identity, "password_available": bool(user.password_hash)}

    return {"google_account": google_account}


@google_auth_bp.after_request
def secure_response(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response
