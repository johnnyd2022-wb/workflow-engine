# ruff: noqa: F811 -- Flask app fixture re-export

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
import requests
from sqlalchemy.orm import Session
from werkzeug.datastructures import MultiDict

from app.features.crm.repositories.xero_token_repo import XeroTokenRepository
from app.features.crm.services.xero_oauth_service import XeroOAuthService
from app.features.crm.services.xero_sync_service import XeroSyncService
from tests.test_compliant_routes import _admin_client, flask_app  # noqa: F401 -- fixture re-export
from tests.test_crm_contact_sync import _connect

PICKER = "/crm/xero/select-tenant"
TOKEN_DATA = {"access_token": "oauth-access", "refresh_token": "oauth-refresh", "expires_in": 1800}


@pytest.fixture
def oauth_provider(monkeypatch):
    monkeypatch.setattr(XeroOAuthService, "exchange_code", Mock(return_value=TOKEN_DATA))
    connections = Mock(
        return_value=[
            {"tenantId": "first", "tenantName": "First Test Org"},
            {"tenantId": "selected", "tenantName": "Selected Test Org"},
        ]
    )
    monkeypatch.setattr(XeroOAuthService, "get_connections", connections)
    sync = Mock()
    monkeypatch.setattr(XeroSyncService, "full_sync", sync)
    return connections, sync


def _callback(client):
    with client.session_transaction() as session:
        session["_xero_oauth_state"] = "test-state"
    return client.get("/crm/xero/callback?state=test-state&code=test-code")


@pytest.mark.parametrize("already_connected", [False, True])
def test_multi_organisation_callback_activates_only_the_confirmed_selection(
    db, flask_app, oauth_provider, already_connected
):
    org, client = _admin_client(db, flask_app)
    org_id = org.id
    if already_connected:
        _connect(db, org_id)
    previous_tenant = "fake-tenant-id" if already_connected else None
    _, sync = oauth_provider
    callback = _callback(client)
    assert callback.location == PICKER
    sync.assert_not_called()
    status = client.get("/api/crm/xero/status").get_json()
    assert status["connected"] is already_connected
    assert status.get("tenant_id") == previous_tenant

    with client.session_transaction() as session:
        selection_id = session["_xero_pending_selection"]
    invalid = client.post(PICKER, data={"tenant_id": "unknown", "selection_id": selection_id})
    assert b"Invalid selection" in invalid.data
    assert client.get("/api/crm/xero/status").get_json().get("tenant_id") == previous_tenant
    sync.assert_not_called()

    repeated = client.post(
        PICKER, data=MultiDict([("selection_id", selection_id), ("tenant_id", "selected"), ("tenant_id", "other")])
    )
    assert b"Invalid selection" in repeated.data
    assert client.get("/api/crm/xero/status").get_json().get("tenant_id") == previous_tenant
    sync.assert_not_called()

    selection = {"tenant_id": "selected", "selection_id": selection_id}
    response = client.post(PICKER, data=selection)
    assert response.location == "/crm/customers?xero_connected=1"
    assert client.get("/api/crm/xero/status").get_json()["tenant_id"] == "selected"
    assert XeroTokenRepository(db).get(org_id).xero_tenant_id == "selected"
    with client.session_transaction() as session:
        session["_xero_pending_selection"] = selection_id
    assert client.post(PICKER, data=selection).location.endswith("error=xero_session_expired")
    sync.assert_called_once_with(org_id, triggered_by="oauth_connect")


def test_single_organisation_callback_connects_and_syncs_immediately(db, flask_app, oauth_provider):
    org, client = _admin_client(db, flask_app)
    connections, sync = oauth_provider
    connections.return_value = [{"tenantId": "only", "tenantName": "Only Test Org"}]

    response = _callback(client)

    assert response.location == "/crm/customers?xero_connected=1"
    assert client.get("/api/crm/xero/status").get_json()["tenant_id"] == "only"
    sync.assert_called_once_with(org.id, triggered_by="oauth_connect")


def test_pending_selection_is_scoped_to_the_owner_and_expires(db, flask_app, oauth_provider):
    org, client = _admin_client(db, flask_app)
    other_org, other_client = _admin_client(db, flask_app)
    assert _callback(client).location == PICKER
    with client.session_transaction() as session:
        selection_id = UUID(session["_xero_pending_selection"])
        user_id = UUID(session["user_id"])
    with other_client.session_transaction() as session:
        other_user_id = UUID(session["user_id"])

    repo = XeroOAuthService(db).pending_repo
    assert repo.get(other_org.id, other_user_id, selection_id) is None
    assert repo.get(org.id, uuid4(), selection_id) is None
    pending = repo.get(org.id, user_id, selection_id)
    pending.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()

    selection = {"tenant_id": "selected", "selection_id": str(selection_id)}
    assert client.post(PICKER, data=selection).location.endswith("error=xero_session_expired")
    assert client.get("/api/crm/xero/status").get_json()["connected"] is False
    oauth_provider[1].assert_not_called()


@pytest.mark.parametrize("provider_rejected", [False, True])
def test_an_in_flight_refresh_cannot_change_a_replaced_connection(db, flask_app, monkeypatch, provider_rejected):
    org, _client = _admin_client(db, flask_app)
    org_id = org.id
    service = XeroOAuthService(db)
    service.store_tokens(
        org_id,
        {"access_token": "old-access", "refresh_token": "old-refresh"},
        {"tenantId": "old"},
        expires_at=datetime.now(UTC) + timedelta(minutes=1),
    )

    def respond_to_refresh(*args, **kwargs):
        with Session(db.get_bind()) as other_db:
            XeroOAuthService(other_db).store_tokens(org_id, TOKEN_DATA, {"tenantId": "replacement"})
        response = Mock()
        response.json.return_value = {"access_token": "old-access-rotated", "refresh_token": "old-refresh-rotated"}
        if provider_rejected:
            rejected = requests.Response()
            rejected.status_code = 400
            response.raise_for_status.side_effect = requests.HTTPError(response=rejected)
        return response

    monkeypatch.setattr(requests, "post", respond_to_refresh)

    assert service.get_valid_token(org_id) == ("oauth-access", "replacement")
    assert service.get_valid_token(org_id) == ("oauth-access", "replacement")
