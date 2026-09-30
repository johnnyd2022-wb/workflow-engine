"""Customer routes use only a portal principal and published order projections."""

from datetime import UTC, datetime
from io import BytesIO

from flask import Blueprint, g, jsonify, make_response, render_template, request, send_file, session
from flask_limiter.util import get_remote_address

from app.api.routes.auth_routes import limiter
from app.core.db import db_session
from app.core.security.tenant_scope import unscoped
from app.features.contract_manufacturing.models.portal import PortalSession
from app.features.contract_manufacturing.portal_security import COOKIE_NAME, requires_portal
from app.features.contract_manufacturing.routes.orders import handled
from app.features.contract_manufacturing.services.orders import OrderError
from app.features.contract_manufacturing.services.portal_approvals import respond_approval
from app.features.contract_manufacturing.services.portal_auth import (
    SESSION_LIFETIME,
    accept_invite,
    audit,
    authenticate,
    token_hash,
)
from app.features.contract_manufacturing.services.portal_sharing import shared_document, shared_order, shared_orders

bp = Blueprint(
    "contract_portal",
    __name__,
    url_prefix="/portal",
    template_folder="../frontend/templates",
    static_folder="../frontend/static",
    static_url_path="/static",
)


def signed_in_response(principal, token):
    # Rotate the Flask CSRF session and remove every staff/pending-2FA key. The opaque
    # portal cookie is authenticated separately; it is never stored as staff user_id.
    previous = request.cookies.get(COOKIE_NAME)
    if previous:
        try:
            digest = token_hash(previous)
        except OrderError:
            digest = None
        if digest:
            with unscoped():
                # The opaque token hash is globally unique; no org is known before lookup.
                db_session().query(PortalSession).filter(
                    PortalSession.token_hash == digest, PortalSession.revoked_at.is_(None)
                ).update({"revoked_at": datetime.now(UTC)}, synchronize_session=False)
            db_session().commit()
    session.clear()
    session.permanent = True
    g.pop("csrf_token", None)
    session["portal_customer_hint"] = str(principal.customer_id)
    response = make_response(jsonify({"redirect": "/portal"}))
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=int(SESSION_LIFETIME.total_seconds()),
        path="/",
        secure=True,
        httponly=True,
        samesite="Strict",
    )
    return response


@bp.get("/login")  # nosemgrep: route-missing-requires-auth -- public sign-in page
def login_page():
    return render_template(
        "portal/login.html", customer_key=request.args.get("customer") or session.get("portal_customer_hint")
    )


@bp.get("/invite")  # nosemgrep: route-missing-requires-auth -- public invitation page
def invite_page():
    return render_template("portal/invite.html")


@bp.post("/api/login")  # nosemgrep: route-missing-requires-auth -- credential exchange
@limiter.limit("10 per minute; 50 per hour", key_func=get_remote_address)
@handled
def login():
    principal, raw = authenticate(db_session(), request.get_json(silent=True))
    db_session().commit()
    return signed_in_response(principal, raw)


@bp.post("/api/accept")  # nosemgrep: route-missing-requires-auth -- invitation exchange
@limiter.limit("10 per minute; 30 per hour", key_func=get_remote_address)
@handled
def accept():
    principal, raw = accept_invite(db_session(), request.get_json(silent=True))
    db_session().commit()
    return signed_in_response(principal, raw)


@bp.post("/api/logout")
@limiter.limit("30 per minute", key_func=get_remote_address)
@requires_portal
@handled
def logout():
    g.portal_session.revoked_at = datetime.now(UTC)
    audit(db_session(), g.portal_principal.org_id, "signed_out", g.portal_principal)
    db_session().commit()
    session.clear()
    session.permanent = True
    g.pop("csrf_token", None)
    session["portal_customer_hint"] = str(g.portal_principal.customer_id)
    response = make_response(jsonify({"redirect": f"/portal/login?customer={g.portal_principal.customer_id}"}))
    response.delete_cookie(COOKIE_NAME, path="/", secure=True, httponly=True, samesite="Strict")
    return response


@bp.get("")
@requires_portal
@handled
def home():
    orders = shared_orders(db_session(), g.portal_principal)
    return render_template(
        "portal/home.html",
        customer_name=g.portal_customer.name,
        producer_name=orders[0]["producer_name"] if orders else None,
        orders=orders,
    )


@bp.get("/orders/<uuid:order_id>")
@requires_portal
@handled
def order_page(order_id):
    payload = shared_order(db_session(), g.portal_principal, order_id)
    return render_template(
        "portal/order.html",
        customer_name=payload["customer_name"],
        producer_name=payload["producer_name"],
        order=payload,
    )


@bp.get("/api/orders")
@requires_portal
@handled
def list_orders():
    return jsonify({"orders": shared_orders(db_session(), g.portal_principal)})


@bp.get("/api/orders/<uuid:order_id>")
@requires_portal
@handled
def get_order(order_id):
    return jsonify({"order": shared_order(db_session(), g.portal_principal, order_id)})


@bp.post("/api/orders/<uuid:order_id>/approvals/<uuid:approval_id>")
@limiter.limit("20 per minute", key_func=get_remote_address)
@requires_portal
@handled
def respond_to_approval(order_id, approval_id):
    row = respond_approval(db_session(), g.portal_principal, order_id, approval_id, request.get_json(silent=True))
    db_session().commit()
    return jsonify({"approval_id": str(row.id), "decision": row.decision})


@bp.get("/api/orders/<uuid:order_id>/documents/<uuid:document_id>")
@requires_portal
@handled
def download_document(order_id, document_id):
    row = shared_document(db_session(), g.portal_principal, order_id, document_id)
    extensions = {"application/pdf": "pdf", "image/png": "png", "image/jpeg": "jpg", "text/plain": "txt"}
    return send_file(
        BytesIO(row.content),
        mimetype=row.content_type,
        as_attachment=True,
        download_name=f"shared-document-{row.id}.{extensions[row.content_type]}",
        conditional=False,
        max_age=0,
    )
