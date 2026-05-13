"""OAuth2 routes — connect, callback, status, disconnect, manual sync."""

import logging
from uuid import UUID

from flask import Blueprint, g, jsonify, redirect, request, session

from app.core.db import db_session
from app.core.security.permissions import requires_auth
from app.core.utils.emit_event import emit_event
from app.core.utils.log_action import log_action
from app.features.crm.services.xero_oauth_service import XeroOAuthService, XeroTokenExpiredError
from app.features.crm.services.xero_sync_service import XeroSyncService

logger = logging.getLogger(__name__)

oauth_bp = Blueprint("crm_oauth", __name__)

_XERO_STATE_SESSION_KEY = "_xero_oauth_state"


@oauth_bp.route("/crm/xero/auth", methods=["GET"])
@requires_auth
def xero_auth():
    """Initiate Xero OAuth2 flow."""
    from app.utils.config_loader import config

    if not config.xero_client_id or not config.xero_client_secret:
        return redirect("/core/integrations?error=xero_not_configured")

    state = XeroOAuthService.generate_state()
    session[_XERO_STATE_SESSION_KEY] = state

    service = XeroOAuthService(db_session())
    auth_url = service.build_auth_url(state)
    return redirect(auth_url)


@oauth_bp.route("/crm/xero/callback", methods=["GET"])
@requires_auth
def xero_callback():
    """Handle Xero OAuth2 callback — exchange code, store tokens, run initial sync."""
    org_id = UUID(g.org_id)

    # CSRF validation
    state_param = request.args.get("state", "")
    expected_state = session.pop(_XERO_STATE_SESSION_KEY, None)
    if not expected_state or state_param != expected_state:
        logger.warning("Xero OAuth callback: state mismatch for org %s", org_id)
        return redirect("/core/integrations?error=xero_state_mismatch")

    error = request.args.get("error")
    if error:
        logger.warning("Xero OAuth callback error: %s for org %s", error, org_id)
        return redirect(f"/core/integrations?error=xero_{error}")

    code = request.args.get("code")
    if not code:
        return redirect("/core/integrations?error=xero_no_code")

    db = db_session()
    service = XeroOAuthService(db)

    try:
        token_data = service.exchange_code(code)
        connections = service.get_connections(token_data["access_token"])
        if not connections:
            return redirect("/core/integrations?error=xero_no_tenant")

        service.store_tokens(org_id, token_data, connections)

        emit_event(
            event_type="xero.connected",
            entity_type="xero_tenant",
            entity_id=org_id,
            payload={"tenant_name": connections[0].get("tenantName"), "org_id": str(org_id)},
            org_id=org_id,
            actor_id=UUID(g.user_id) if g.user_id else None,
            actor_label=g.user_email,
        )
        log_action("connect", "xero_tenant", org_id, {"tenant": connections[0].get("tenantName")})
    except Exception:
        logger.exception("Xero OAuth exchange failed for org %s", org_id)
        return redirect("/core/integrations?error=xero_exchange_failed")

    # Trigger initial full sync (synchronous in Phase 1)
    try:
        sync_service = XeroSyncService(db)
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
    """Trigger a manual incremental sync."""
    org_id = UUID(g.org_id)
    db = db_session()

    try:
        sync_service = XeroSyncService(db)
        result = sync_service.incremental_sync(org_id, triggered_by="manual")
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
