"""OAuth2 routes — connect, callback, tenant picker, status, disconnect, manual sync."""

from uuid import UUID

from flask import Blueprint, g, jsonify, make_response, redirect, render_template, request, session

from app.core.db import db_session
from app.core.security.permissions import requires_auth
from app.core.utils.emit_event import emit_event
from app.features.crm.services.xero_api_client import XeroInsufficientScopeError
from app.features.crm.services.xero_oauth_service import XeroOAuthService, XeroTokenExpiredError
from app.features.crm.services.xero_sync_service import XeroSyncService
from app.observability import get_logger
from app.utils.config_loader import config

logger = get_logger(__name__)

oauth_bp = Blueprint("crm_oauth", __name__)

_XERO_STATE_SESSION_KEY = "_xero_oauth_state"
_XERO_SELECTION_SESSION_KEY = "_xero_pending_selection"


@oauth_bp.route("/crm/xero/auth", methods=["GET"])
@requires_auth
def xero_auth():
    """Initiate Xero OAuth2 flow."""
    service = XeroOAuthService(db_session())
    client_id = config.xero_client_id
    redirect_uri = config.xero_redirect_uri
    if not client_id or not redirect_uri:
        logger.error(
            "xero_oauth_config_missing",
            environment=config.environment,
            has_client_id=bool(client_id),
            has_redirect_uri=bool(redirect_uri),
        )
        return redirect("/core/integrations?error=xero_not_configured")

    state = XeroOAuthService.generate_state()
    session[_XERO_STATE_SESSION_KEY] = state

    auth_url = service.build_auth_url(state)
    return redirect(auth_url)


@oauth_bp.route("/api/crm/xero/auth-url", methods=["GET"])
@requires_auth
def xero_auth_url():
    """Return the Xero OAuth authorization URL for client-side redirect flows."""
    client_id = config.xero_client_id
    redirect_uri = config.xero_redirect_uri
    if not client_id or not redirect_uri:
        logger.error(
            "xero_auth_url_config_missing",
            environment=config.environment,
            has_client_id=bool(client_id),
            has_redirect_uri=bool(redirect_uri),
        )
        return jsonify(
            {"error": "xero_not_configured", "message": "Xero client_id/redirect_uri is not configured"}
        ), 400

    logger.info(
        "xero_auth_url_requested",
        environment=config.environment,
        client_id_suffix=client_id[-6:] if len(client_id) >= 6 else client_id,
        redirect_uri=redirect_uri,
    )

    state = XeroOAuthService.generate_state()
    session[_XERO_STATE_SESSION_KEY] = state

    service = XeroOAuthService(db_session())
    auth_url = service.build_auth_url(state)
    response = make_response(jsonify({"auth_url": auth_url}), 200)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@oauth_bp.route("/crm/xero/callback", methods=["GET"])
@requires_auth
def xero_callback():
    """Handle Xero OAuth2 callback — exchange code, store tokens, run initial sync (or show tenant picker)."""
    org_id = g.current_org_id

    # CSRF validation
    state_param = request.args.get("state", "")
    expected_state = session.pop(_XERO_STATE_SESSION_KEY, None)
    if not expected_state or state_param != expected_state:
        logger.warning("xero_oauth_state_mismatch", org_id=str(org_id))
        return redirect("/core/integrations?error=xero_state_mismatch")

    error = request.args.get("error")
    if error:
        logger.warning("xero_oauth_callback_error", org_id=str(org_id), error=error)
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

    except Exception:
        logger.exception("xero_oauth_exchange_failed", org_id=str(org_id))
        return redirect("/core/integrations?error=xero_exchange_failed")

    if len(connections) == 1:
        # Single tenant — auto-connect immediately
        return _complete_connection(org_id, service, token_data, connections[0])

    choices = [
        {
            "id": c.get("id", ""),
            "tenantId": c["tenantId"],
            "tenantName": c.get("tenantName", "Unknown Organisation"),
            "tenantType": c.get("tenantType", "ORGANISATION"),
        }
        for c in connections
    ]
    try:
        selection_id = service.stage_selection(org_id, g.current_user.id, token_data, choices)
    except Exception:
        db.rollback()
        logger.exception("xero_pending_token_store_failed", org_id=str(org_id))
        return redirect("/core/integrations?error=xero_exchange_failed")

    session[_XERO_SELECTION_SESSION_KEY] = str(selection_id)
    return redirect("/crm/xero/select-tenant")


def _selection_id() -> UUID | None:
    raw_id = session.get(_XERO_SELECTION_SESSION_KEY)
    return UUID(raw_id) if raw_id else None


def _render_selection(selection_id, connections, error=None):
    response = make_response(
        render_template(
            "crm/select_tenant.html",
            selection_id=str(selection_id),
            connections=connections,
            error=error,
        )
    )
    response.headers["Cache-Control"] = "private, no-store"
    return response


@oauth_bp.route("/crm/xero/select-tenant", methods=["GET"])
@requires_auth
def xero_select_tenant_page():
    """Show the Xero tenant picker when the user has multiple Xero organisations."""
    selection_id = _selection_id()
    if selection_id:
        service = XeroOAuthService(db_session())
        pending = service.pending_repo.get(g.current_org_id, g.current_user.id, selection_id)
        if pending is not None:
            return _render_selection(selection_id, pending.connections)
    return redirect("/core/integrations")


@oauth_bp.route("/crm/xero/select-tenant", methods=["POST"])
@requires_auth
def xero_select_tenant_submit():
    """Complete the Xero connection with the user-chosen tenant."""
    org_id = g.current_org_id
    selection_id = _selection_id()
    if selection_id is None or request.form.get("selection_id") != str(selection_id):
        return redirect("/core/integrations?error=xero_session_expired")

    db = db_session()
    service = XeroOAuthService(db)
    pending = service.pending_repo.get(org_id, g.current_user.id, selection_id, lock=True)
    if pending is None:
        return redirect("/core/integrations?error=xero_session_expired")

    connections = pending.connections
    selected_tenant_id = request.form.get("tenant_id", "").strip()
    connection = next((c for c in connections if c["tenantId"] == selected_tenant_id), None)
    if not connection:
        return _render_selection(
            selection_id, connections, "Invalid selection — please choose one of the listed organisations."
        )

    try:
        service.activate_selection(pending, connection)
    except Exception:
        db.rollback()
        logger.exception("xero_tenant_selection_finalize_failed", org_id=str(org_id))
        return _render_selection(
            selection_id, connections, "Something went wrong saving your selection. Please try again."
        )

    session.pop(_XERO_SELECTION_SESSION_KEY, None)
    return _finish_connection(org_id, service, connection)


def _complete_connection(org_id: UUID, service: XeroOAuthService, token_data: dict, connection: dict):
    """Store tokens, emit events, and trigger initial sync for a single-tenant connect."""
    try:
        service.store_tokens(org_id, token_data, connection)
    except Exception:
        service.db.rollback()
        logger.exception("xero_oauth_complete_connection_failed", org_id=str(org_id))
        return redirect("/core/integrations?error=xero_exchange_failed")

    session.pop(_XERO_SELECTION_SESSION_KEY, None)
    return _finish_connection(org_id, service, connection)


def _finish_connection(org_id: UUID, service: XeroOAuthService, connection: dict):
    try:
        emit_event(
            event_type="crm_xero.connected",
            entity_type="xero_tenant",
            entity_id=org_id,
            payload={"tenant_name": connection.get("tenantName"), "org_id": str(org_id)},
            org_id=org_id,
            actor_id=UUID(g.user_id) if g.user_id else None,
            actor_label=g.user_email,
        )
    except Exception:
        logger.exception("xero_connection_event_failed", org_id=str(org_id))

    try:
        sync_service = XeroSyncService(service.db)
        sync_service.full_sync(org_id, triggered_by="oauth_connect")
        logger.info("xero_initial_sync_completed", org_id=str(org_id))
    except Exception:
        logger.exception("xero_initial_sync_failed", org_id=str(org_id))

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
        body = {
            "ok": result.success,
            "contacts_synced": result.contacts_synced,
            "invoices_synced": result.invoices_synced,
            "credit_notes_synced": result.credit_notes_synced,
            "sales_allocated": result.sales_allocated,
            "sales_unmapped": result.sales_unmapped,
            "sales_insufficient_stock": result.sales_insufficient_stock,
            "errors": result.errors,
        }
        if result.success:
            return jsonify(body), 200
        more = len(result.errors) - 1
        body["error"] = f"The Xero sync did not finish: {result.errors[0]}" + (f" (and {more} more)" if more else "")
        # A sync that brought nothing in failed; one that brought some in is reported with its errors.
        return jsonify(body), 200 if result.partial else 502
    except XeroTokenExpiredError:
        return jsonify({"error": "reconnect_required", "message": "Xero token expired — please reconnect."}), 401
    except XeroInsufficientScopeError as e:
        return jsonify({"error": "xero_insufficient_scope", "message": str(e), "action": "reconnect_xero"}), 401
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.exception("xero_manual_sync_failed", org_id=str(org_id))
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
            event_type="crm_xero.disconnected",
            entity_type="xero_tenant",
            entity_id=org_id,
            payload={"org_id": str(org_id)},
            org_id=org_id,
            actor_id=UUID(g.user_id) if g.user_id else None,
            actor_label=g.user_email,
        )
        return jsonify({"ok": True}), 200
    except Exception as e:
        logger.exception("xero_disconnect_failed", org_id=str(org_id))
        return jsonify({"error": str(e)}), 500
