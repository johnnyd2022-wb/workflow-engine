"""The OAuth 2.1 authorization server for AI assistants (public MCP 8.2b).

``/.well-known/oauth-authorization-server`` (RFC 8414), ``/oauth/register`` (RFC 7591),
``/oauth/authorize`` and its consent decision, ``/oauth/token`` and ``/oauth/revoke`` (RFC 7009).

Who may call what is in ``access_policy.POLICY`` (``oauth.*``). CSRF: ``token``, ``register`` and
``revoke`` take no cookie and no session, so they are exempt (``app_factory``); the consent form is
an ordinary CSRF-protected form.
"""

from __future__ import annotations

from urllib.parse import quote, urlsplit

from flask import Blueprint, g, jsonify, make_response, redirect, render_template, request
from flask_limiter.util import get_remote_address
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.urls import iri_to_uri

from app.api.routes.auth_routes import limiter
from app.core.db import db_session
from app.core.security.permissions import requires_auth
from app.features.mcp_oauth import SUPPORTED_SCOPES
from app.features.mcp_oauth.routes.request_payloads import (
    AUTHORIZE_SINGLE_FIELDS,
    CONSENT_SINGLE_FIELDS,
    REVOKE_SINGLE_FIELDS,
    TOKEN_SINGLE_FIELDS,
    check_single_fields,
)
from app.features.mcp_oauth.services import authorization, client_registry, pending_authorization, token_service
from app.features.mcp_oauth.services.client_registry import ClientError
from app.features.mcp_oauth.services.token_service import TokenError
from app.observability import get_logger
from app.utils.config_loader import config

logger = get_logger(__name__)

oauth_bp = Blueprint("oauth", __name__, template_folder="../frontend/templates")

MAX_REGISTER_BYTES = 8 * 1024
MAX_OAUTH_FORM_BYTES = 16 * 1024
# These endpoints are called by browser-based MCP clients as well as servers. They carry no cookie
# and trust no origin, so any origin may read the answer; the authorize page never gets this.
_CORS_ENDPOINTS = frozenset({"oauth.metadata", "oauth.register", "oauth.token", "oauth.revoke"})


@oauth_bp.before_request
def _bound_request():
    if request.method == "POST":
        maximum = MAX_REGISTER_BYTES if request.endpoint == "oauth.register" else MAX_OAUTH_FORM_BYTES
        request.max_content_length = maximum
        request.max_form_memory_size = maximum
        request.max_form_parts = 32


@oauth_bp.errorhandler(RequestEntityTooLarge)
def _too_large(_error):
    message = "Request too large"
    if request.endpoint == "oauth.authorize_decision":
        return _error_page(message, 413)
    if request.endpoint == "oauth.revoke":
        return "", 200
    error = "invalid_client_metadata" if request.endpoint == "oauth.register" else "invalid_request"
    return jsonify(error=error, error_description=message), 413


@oauth_bp.after_request
def _headers(response):
    if request.endpoint in _CORS_ENDPOINTS:
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    if request.endpoint in {"oauth.token", "oauth.register", "oauth.authorize", "oauth.authorize_decision"}:
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
    if request.endpoint in {"oauth.authorize", "oauth.authorize_decision"}:
        # The consent form's own POST needs a Referer (Flask-WTF checks it on HTTPS), so this is
        # "same-origin" rather than "no-referrer": the page's address still never reaches another
        # site, including the assistant's callback the form sends the browser on to.
        response.headers["Referrer-Policy"] = "same-origin"
    return response


@oauth_bp.errorhandler(429)
def _rate_limited(error):
    response = jsonify({"error": "rate_limited", "error_description": "Too many requests; try again shortly"})
    response.status_code = 429
    retry = getattr(error, "retry_after", None)
    response.headers["Retry-After"] = str(int(retry)) if retry else "60"
    return response


# --- RFC 8414 metadata --------------------------------------------------------------------------


@oauth_bp.get("/.well-known/oauth-authorization-server")  # nosemgrep: route-missing-requires-auth
def metadata():
    issuer = config.mcp_issuer
    if not issuer:
        return jsonify({"error": "server_error"}), 503
    response = jsonify(
        {
            "issuer": issuer,
            "authorization_endpoint": f"{issuer}/oauth/authorize",
            "token_endpoint": f"{issuer}/oauth/token",
            "registration_endpoint": f"{issuer}/oauth/register",
            "revocation_endpoint": f"{issuer}/oauth/revoke",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"],
            "scopes_supported": list(SUPPORTED_SCOPES),
            "client_id_metadata_document_supported": True,
            "authorization_response_iss_parameter_supported": True,  # RFC 9207
        }
    )
    response.headers["Cache-Control"] = "public, max-age=300"
    return response


# --- RFC 7591 dynamic client registration -------------------------------------------------------


@oauth_bp.route("/oauth/register", methods=["POST", "OPTIONS"])  # nosemgrep: route-missing-requires-auth
@limiter.limit("10 per hour", key_func=get_remote_address, methods=["POST"])
def register():
    if request.method == "OPTIONS":
        return "", 204
    if (request.content_length or 0) > MAX_REGISTER_BYTES:
        return jsonify({"error": "invalid_client_metadata", "error_description": "Request too large"}), 413
    payload = request.get_json(silent=True) if request.is_json else None
    db = db_session()
    try:
        _row, body = client_registry.register_dcr(db, payload)
    except ClientError as err:
        db.rollback()
        return jsonify({"error": err.code, "error_description": err.description}), 400
    logger.info("mcp.client_registered", client=body["client_id"])
    return jsonify(body), 201


# --- authorize and consent ----------------------------------------------------------------------


def _error_page(message: str, status: int):
    return make_response(render_template("oauth_error.html", message=message), status)


def _blocked_page(req, message: str):
    return make_response(
        render_template("oauth_consent.html", req=req, blocked=message, user=g.current_user, org=g.current_org),
        403,
    )


def _callback_host(redirect_uri: str) -> str:
    """Show the ASCII authority Flask uses in the redirect response, including its port."""
    try:
        return urlsplit(iri_to_uri(redirect_uri)).netloc
    except UnicodeError:
        # Some stored callback hostnames cannot be encoded as IDNA.
        return quote(urlsplit(redirect_uri).netloc, safe="[]:%")


def _login_redirect():
    """Send a signed-out visitor to the normal sign-in page; the request waits in their session.

    There is no return address in the URL. After sign-in the app builds ``/oauth/authorize?...``
    from the stored parameters (``pending_authorization``), so nothing here can be turned into a
    redirect to another site.
    """
    if not pending_authorization.remember(request.args):
        return _error_page("The authorization request is too large to continue after sign-in.", 400)
    return redirect("/?login=1")


# A signed-out visitor must reach this route: it sends them to sign in and back (the POST below
# requires a session). Classified SIGNED_IN in POLICY, which only judges signed-in users.
@oauth_bp.get("/oauth/authorize")  # nosemgrep: route-missing-requires-auth
@limiter.limit("60 per minute", key_func=get_remote_address)
def authorize():
    if len(request.query_string) > MAX_OAUTH_FORM_BYTES:
        return _error_page("Request too large", 413)
    try:
        check_single_fields(request.args, AUTHORIZE_SINGLE_FIELDS)
    except ValueError as exc:
        return _error_page(str(exc), 400)
    db = db_session()
    if g.current_user is None and authorization.needs_metadata_fetch(db, request.args.get("client_id")):
        # A stranger must not be able to make this server fetch a URL of their choosing: an unknown
        # metadata-URL client is only looked up after someone has signed in.
        return _login_redirect()
    try:
        req = authorization.parse_authorize(db, request.args)
    except authorization.PageError as err:
        return _error_page(err.message, err.status)
    except authorization.RedirectError as err:
        return redirect(err.location())
    if g.current_user is None:
        return _login_redirect()
    pending_authorization.clear()  # signed in: the request now travels in the consent form
    reason = authorization.consent_block_reason(db, g.current_user, req.client)
    if reason:
        logger.info("mcp.consent_blocked", client=req.client.client_id[:200], reason=reason[:40])
        return _blocked_page(req, reason)
    return render_template(
        "oauth_consent.html",
        req=req,
        blocked=None,
        user=g.current_user,
        org=g.current_org,
        fields=req.form_fields(),
        host=_callback_host(req.redirect_uri),
        covers=authorization.readable_summary(g.current_user),
    )


@oauth_bp.post("/oauth/authorize")
@requires_auth
@limiter.limit("60 per minute", key_func=get_remote_address)
def authorize_decision():
    db = db_session()
    try:
        check_single_fields(request.form, CONSENT_SINGLE_FIELDS)
    except ValueError as exc:
        return _error_page(str(exc), 400)
    try:
        req = authorization.parse_authorize(db, request.form)
    except authorization.PageError as err:
        return _error_page(err.message, err.status)
    except authorization.RedirectError as err:
        return redirect(err.location())
    user = g.current_user
    reason = authorization.consent_block_reason(db, user, req.client)
    if reason:
        logger.info("mcp.consent_blocked", client=req.client.client_id[:200], reason=reason[:40])
        return _blocked_page(req, reason)
    if request.form.get("decision") != "approve":
        return redirect(
            authorization.RedirectError(
                "access_denied", "The user denied the request", req.redirect_uri, req.state
            ).location()
        )
    if request.form.get("access_level") != "read":
        return redirect(
            authorization.RedirectError(
                "invalid_request", "Only read access can be approved", req.redirect_uri, req.state
            ).location()
        )
    return redirect(authorization.approve(db, user, req))


# --- token and revocation -----------------------------------------------------------------------


def _token_key() -> str:
    client_id = (request.form.get("client_id") or "")[:200]
    return f"{client_id}|{get_remote_address()}"


def _token_response(status: int, body: dict):
    response = jsonify(body)
    response.status_code = status
    return response


@oauth_bp.route("/oauth/token", methods=["POST", "OPTIONS"])  # nosemgrep: route-missing-requires-auth
@limiter.limit("60 per minute", key_func=_token_key, methods=["POST"])
def token():
    if request.method == "OPTIONS":
        return "", 204
    db = db_session()
    try:
        check_single_fields(request.form, TOKEN_SINGLE_FIELDS)
    except ValueError as exc:
        return _token_response(400, TokenError("invalid_request", str(exc)).body())
    grant_type = request.form.get("grant_type")
    try:
        if grant_type == "authorization_code":
            issued = token_service.exchange_code(db, request.form)
        elif grant_type == "refresh_token":
            issued = token_service.refresh(db, request.form)
        else:
            raise TokenError("unsupported_grant_type", "Use authorization_code or refresh_token")
    except TokenError as err:
        db.rollback()
        return _token_response(err.status, err.body())
    return _token_response(200, issued.body())


@oauth_bp.route("/oauth/revoke", methods=["POST", "OPTIONS"])  # nosemgrep: route-missing-requires-auth
@limiter.limit("60 per minute", key_func=get_remote_address, methods=["POST"])
def revoke():
    if request.method == "OPTIONS":
        return "", 204
    try:
        check_single_fields(request.form, REVOKE_SINGLE_FIELDS)
    except ValueError:
        return "", 200
    db = db_session()
    try:
        token_service.revoke_presented(db, request.form)
    except Exception:
        db.rollback()
        logger.exception("mcp.revoke_failed")  # RFC 7009: still answer 200
    return "", 200
