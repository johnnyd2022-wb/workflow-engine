"""Portal cookie guard and authentication decorator, independent of the staff session."""

from functools import wraps
from urllib.parse import urlencode

from flask import g, jsonify, redirect, request, session

from app.core.db import db_session
from app.core.security.tenant_scope import activate_request_org_id
from app.features.contract_manufacturing.services.orders import OrderError
from app.features.contract_manufacturing.services.portal_auth import resolve_session

COOKIE_NAME = "__Host-contract_portal_session"
PORTAL_ENDPOINTS = frozenset(
    {
        "contract_portal.login_page",
        "contract_portal.invite_page",
        "contract_portal.login",
        "contract_portal.accept",
        "contract_portal.logout",
        "contract_portal.home",
        "contract_portal.order_page",
        "contract_portal.list_orders",
        "contract_portal.get_order",
        "contract_portal.respond_to_approval",
        "contract_portal.send_message",
        "contract_portal.reorder",
        "contract_portal.download_document",
        "contract_portal.static",
    }
)


def setup_portal_security(app):
    @app.before_request
    def separate_portal_realm():
        # Runs before staff tenant resolution. Even a simultaneous staff cookie cannot
        # turn a portal browsing session into a staff principal.
        if request.cookies.get(COOKIE_NAME) and request.endpoint not in PORTAL_ENDPOINTS:
            if request.endpoint and (
                request.endpoint == "static" or request.endpoint.endswith(".static") or request.endpoint == "favicon"
            ):
                return None
            return jsonify(
                {"error": "Sign out of the customer portal before using staff pages", "code": "portal_realm_only"}
            ), 403
        if request.endpoint == "contracts.portal_upload_document":
            request.max_content_length = 5 * 1024 * 1024 + 64 * 1024
        elif request.endpoint in PORTAL_ENDPOINTS or request.endpoint == "contracts.portal_publish_order":
            request.max_content_length = 64 * 1024
        return None

    @app.after_request
    def private_portal_responses(response):
        if request.endpoint in PORTAL_ENDPOINTS or (
            request.endpoint and request.endpoint.startswith("contracts.portal_")
        ):
            response.headers["Cache-Control"] = "private, no-store"
            response.headers["Referrer-Policy"] = "same-origin"
            response.headers["X-Content-Type-Options"] = "nosniff"
        return response


def requires_portal(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        try:
            principal, customer, portal_session = resolve_session(db_session(), request.cookies.get(COOKIE_NAME))
        except OrderError:
            db_session().rollback()
            if request.endpoint in {"contract_portal.home", "contract_portal.order_page"}:
                hint = session.get("portal_customer_hint")
                query = "?" + urlencode({"customer": hint}) if hint else ""
                response = redirect("/portal/login" + query)
            else:
                response = jsonify({"error": "Sign in to the customer portal", "code": "portal_auth_required"})
            response.delete_cookie(COOKIE_NAME, path="/", secure=True, httponly=True, samesite="Strict")
            return response if response.status_code == 302 else (response, 401)
        g.portal_principal = principal
        g.portal_customer = customer
        g.portal_session = portal_session
        # Enable automatic tenant filtering, without populating any staff identity.
        activate_request_org_id(principal.org_id)
        return function(*args, **kwargs)

    wrapped.portal_guarded = True
    return wrapped
