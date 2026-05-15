"""OAuth2 routes — connect, callback, tenant picker, status, disconnect, manual sync."""

import logging
from uuid import UUID

from flask import Blueprint, g, jsonify, redirect, render_template, request, session

from app.core.db import db_session
from app.core.security.permissions import requires_auth
from app.core.utils.emit_event import emit_event
from app.core.utils.log_action import log_action
from app.features.crm.services.xero_api_client import XeroInsufficientScopeError
from app.features.crm.services.xero_oauth_service import XeroOAuthService, XeroTokenExpiredError
from app.features.crm.services.xero_sync_service import XeroSyncService

logger = logging.getLogger(__name__)

oauth_bp = Blueprint("crm_oauth", __name__)

_XERO_STATE_SESSION_KEY = "_xero_oauth_state"
_XERO_PENDING_CONNECTIONS_KEY = "_xero_pending_connections"


@oauth_bp.route("/crm/xero/auth", methods=["GET"])
@requires_auth
def xero_auth():
    """Initiate Xero OAuth2 flow."""
    from app.utils.config_loader import config

    if not config.xero_client_id or not config.xero_client_secret:
        return redirect("/crm/configuration?error=xero_not_configured")

    state = XeroOAuthService.generate_state()
    session[_XERO_STATE_SESSION_KEY] = state

    service = XeroOAuthService(db_session())
    auth_url = service.build_auth_url(state)
    return redirect(auth_url)


@oauth_bp.route("/crm/xero/callback", methods=["GET"])
@requires_auth
def xero_callback():
    """Handle Xero OAuth2 callback — exchange code, store tokens, run initial sync (or show tenant picker)."""
    org_id = UUID(g.org_id)

    # CSRF validation
    state_param = request.args.get("state", "")
    expected_state = session.pop(_XERO_STATE_SESSION_KEY, None)
    if not expected_state or state_param != expected_state:
        logger.warning("Xero OAuth callback: state mismatch for org %s", org_id)
        return redirect("/crm/configuration?error=xero_state_mismatch")

    error = request.args.get("error")
    if error:
        logger.warning("Xero OAuth callback error: %s for org %s", error, org_id)
        return redirect(f"/crm/configuration?error=xero_{error}")

    code = request.args.get("code")
    if not code:
        return redirect("/crm/configuration?error=xero_no_code")

    db = db_session()
    service = XeroOAuthService(db)

    try:
        token_data = service.exchange_code(code)
        connections = service.get_connections(token_data["access_token"])
        if not connections:
            return redirect("/crm/configuration?error=xero_no_tenant")

    except Exception:
        logger.exception("Xero OAuth exchange failed for org %s", org_id)
        return redirect("/crm/configuration?error=xero_exchange_failed")

    if len(connections) == 1:
        # Single tenant — auto-connect immediately
        return _complete_connection(org_id, service, token_data, connections[0])

    # Multiple tenants — store tokens with a placeholder (first entry's tenant),
    # then let the user choose which org to use.
    try:
        service.store_tokens(org_id, token_data, connections[0])
    except Exception:
        logger.exception("Failed to store pending Xero tokens for org %s", org_id)
        return redirect("/crm/configuration?error=xero_exchange_failed")

    # Store only non-sensitive connection metadata in the session cookie
    session[_XERO_PENDING_CONNECTIONS_KEY] = [
        {
            "id": c.get("id", ""),
            "tenantId": c["tenantId"],
            "tenantName": c.get("tenantName", "Unknown Organisation"),
            "tenantType": c.get("tenantType", "ORGANISATION"),
        }
        for c in connections
    ]

    return redirect("/crm/xero/select-tenant")


@oauth_bp.route("/crm/xero/select-tenant", methods=["GET"])
@requires_auth
def xero_select_tenant_page():
    """Show the Xero tenant picker when the user has multiple Xero organisations."""
    connections = session.get(_XERO_PENDING_CONNECTIONS_KEY)
    if not connections:
        # Nothing pending — they may have arrived here directly
        return redirect("/crm/configuration")

    return render_template("crm/select_tenant.html", connections=connections)


@oauth_bp.route("/crm/xero/select-tenant", methods=["POST"])
@requires_auth
def xero_select_tenant_submit():
    """Complete the Xero connection with the user-chosen tenant."""
    org_id = UUID(g.org_id)
    connections = session.get(_XERO_PENDING_CONNECTIONS_KEY)
    if not connections:
        return redirect("/crm/configuration?error=xero_session_expired")

    selected_tenant_id = request.form.get("tenant_id", "").strip()
    connection = next((c for c in connections if c["tenantId"] == selected_tenant_id), None)
    if not connection:
        return render_template(
            "crm/select_tenant.html",
            connections=connections,
            error="Invalid selection — please choose one of the listed organisations.",
        )

    db = db_session()
    service = XeroOAuthService(db)

    try:
        service.finalize_tenant_selection(org_id, connection)
    except Exception:
        logger.exception("Failed to finalise Xero tenant selection for org %s", org_id)
        return render_template(
            "crm/select_tenant.html",
            connections=connections,
            error="Something went wrong saving your selection. Please try again.",
        )

    # Clear pending session data
    session.pop(_XERO_PENDING_CONNECTIONS_KEY, None)

    emit_event(
        event_type="xero.connected",
        entity_type="xero_tenant",
        entity_id=org_id,
        payload={"tenant_name": connection.get("tenantName"), "org_id": str(org_id)},
        org_id=org_id,
        actor_id=UUID(g.user_id) if g.user_id else None,
        actor_label=g.user_email,
    )
    log_action("connect", "xero_tenant", org_id, {"tenant": connection.get("tenantName")})

    try:
        sync_service = XeroSyncService(db)
        sync_service.full_sync(org_id, triggered_by="oauth_connect")
    except Exception:
        logger.exception("Initial Xero sync failed for org %s (continuing anyway)", org_id)

    return redirect("/crm/customers?xero_connected=1")


def _complete_connection(org_id: UUID, service: XeroOAuthService, token_data: dict, connection: dict):
    """Store tokens, emit events, and trigger initial sync for a single-tenant connect."""
    try:
        service.store_tokens(org_id, token_data, connection)

        emit_event(
            event_type="xero.connected",
            entity_type="xero_tenant",
            entity_id=org_id,
            payload={"tenant_name": connection.get("tenantName"), "org_id": str(org_id)},
            org_id=org_id,
            actor_id=UUID(g.user_id) if g.user_id else None,
            actor_label=g.user_email,
        )
        log_action("connect", "xero_tenant", org_id, {"tenant": connection.get("tenantName")})
    except Exception:
        logger.exception("Xero OAuth exchange failed for org %s", org_id)
        return redirect("/crm/configuration?error=xero_exchange_failed")

    try:
        sync_service = XeroSyncService(service.db)
        sync_service.full_sync(org_id, triggered_by="oauth_connect")
        logger.info("Initial Xero sync completed for org %s", org_id)
    except Exception:
        logger.exception("Initial Xero sync failed for org %s (continuing anyway)", org_id)

    return redirect("/crm/customers?xero_connected=1")


@oauth_bp.route("/api/crm/xero/status", methods=["GET"])
@requires_auth
def xero_status():
    from app.features.crm.services.crm_service import CRMService

    org_id = UUID(g.org_id)
    service = CRMService(db_session())
    return jsonify(service.get_xero_status(org_id)), 200


@oauth_bp.route("/api/crm/xero/sync", methods=["POST"])
@requires_auth
def xero_sync():
    """Trigger a manual sync.

    Defaults to full sync so deleted/missing invoice reconciliation is applied.
    Pass ?mode=incremental to run a lighter incremental sync.
    """
    org_id = UUID(g.org_id)
    db = db_session()
    mode = (request.args.get("mode") or "full").strip().lower()

    try:
        sync_service = XeroSyncService(db)
        if mode == "incremental":
            result = sync_service.incremental_sync(org_id, triggered_by="manual_incremental")
        else:
            result = sync_service.full_sync(org_id, triggered_by="manual_full")
        log_action(
            "sync", "xero_tenant", org_id, {"contacts": result.contacts_synced, "invoices": result.invoices_synced}
        )
        return jsonify(
            {
                "ok": True,
                "contacts_synced": result.contacts_synced,
                "invoices_synced": result.invoices_synced,
                "errors": result.errors,
            }
        ), 200
    except XeroTokenExpiredError:
        return jsonify({"error": "reconnect_required", "message": "Xero token expired — please reconnect."}), 401
    except XeroInsufficientScopeError as e:
        return jsonify({"error": "xero_insufficient_scope", "message": str(e), "action": "reconnect_xero"}), 401
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.exception("Manual sync failed for org %s", org_id)
        return jsonify({"error": "Sync failed", "message": str(e)}), 500


@oauth_bp.route("/api/crm/xero/disconnect", methods=["POST"])
@requires_auth
def xero_disconnect():
    org_id = UUID(g.org_id)
    db = db_session()

    try:
        service = XeroOAuthService(db)
        service.disconnect(org_id)

        emit_event(
            event_type="xero.disconnected",
            entity_type="xero_tenant",
            entity_id=org_id,
            payload={"org_id": str(org_id)},
            org_id=org_id,
            actor_id=UUID(g.user_id) if g.user_id else None,
            actor_label=g.user_email,
        )
        log_action("disconnect", "xero_tenant", org_id)
        return jsonify({"ok": True}), 200
    except Exception as e:
        logger.exception("Xero disconnect failed for org %s", org_id)
        return jsonify({"error": str(e)}), 500
