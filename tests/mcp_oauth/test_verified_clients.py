"""Design review S3: consent must tell a real client from an impostor.

.agents/reports/design-review/2026-11-17-mcp-costing-planning-analytics.md §S3. Before the fix every
client was created with ``verified=False`` and registration was open, so a DCR client named
"Claude" with an attacker's redirect URI looked exactly like Claude on the consent page, and an
admin who followed a crafted link granted rolling 30-day read access.

Now a short list of verified clients lives in code (``services/verified_clients.py``), matched by
redirect URIs (and the metadata document URL), never by name; and each organisation allows only
verified clients unless an admin turns on ``allow_unverified_clients``.
"""

from __future__ import annotations

import json
from unittest import mock

import pytest

from app.core.db.models.audit_log import AuditLog
from app.features.mcp_oauth.models import McpOrgSettings, OAuthClient, OAuthGrant
from app.features.mcp_oauth.services import client_registry
from tests.mcp_oauth.support import (
    authorize_params,
    authorize_url,
    bearer,
    make_client,
    mint_grant,
    pkce_pair,
)

CLAUDE_REDIRECT = "https://claude.ai/api/mcp/auth_callback"
CHATGPT_REDIRECT = "https://chatgpt.com/connector_platform_oauth_redirect"
CHATGPT_CIMD = "https://chatgpt.com/oauth/client.json"
ATTACKER_REDIRECT = "https://claude-ai.attacker.example.test/api/mcp/auth_callback"
PUBLIC_IP = "93.184.216.34"
UNVERIFIED_MESSAGE = "only allows apps Biz-E has verified"


@pytest.fixture
def created_clients(db):
    """Client ids registered by a test under a real vendor name; deleted afterwards (the world
    fixture only cleans up names starting with MCPTEST)."""
    ids: list[str] = []
    yield ids
    db.rollback()
    if ids:
        db.query(OAuthClient).filter(OAuthClient.client_id.in_(ids)).delete(synchronize_session=False)
        db.commit()


def _register(world, created, name, redirect_uris):
    resp = world.anon().post("/oauth/register", json={"client_name": name, "redirect_uris": redirect_uris})
    assert resp.status_code == 201, resp.get_json()
    body = resp.get_json()
    created.append(body["client_id"])
    return body


def _consent(world, client_id, redirect_uri, who="admin"):
    _verifier, challenge = pkce_pair()
    params = authorize_params(client_id, challenge, redirect_uri=redirect_uri)
    session = world.session(who)
    return session, params, session.get(authorize_url(params))


def _approve(session, params):
    return session.post("/oauth/authorize", data={**params, "decision": "approve", "access_level": "read"})


def _row(db, client_id) -> OAuthClient:
    db.expire_all()
    return db.query(OAuthClient).filter_by(client_id=client_id).one()


# --- the impostor (the finding itself) ----------------------------------------------------------


def test_s3_a_dcr_client_named_claude_with_an_attacker_redirect_is_unverified_and_blocked_by_default(
    world, db, created_clients
):
    world.enable(allow_unverified=False)  # the default for every organisation
    body = _register(world, created_clients, "Claude", [ATTACKER_REDIRECT])
    row = _row(db, body["client_id"])
    assert row.verified is False
    assert row.client_name == "Claude"  # shown as-is, but only ever as an unverified app

    session, params, resp = _consent(world, body["client_id"], ATTACKER_REDIRECT)
    assert resp.status_code == 403
    html = resp.get_data(as_text=True)
    assert UNVERIFIED_MESSAGE in html
    assert 'value="approve"' not in html
    # Posting an approval anyway is refused too, and nothing is granted.
    assert _approve(session, params).status_code == 403
    assert db.query(OAuthGrant).filter_by(org_id=world.org.id, client_pk=row.id).count() == 0


def test_s3_a_claude_name_with_one_attacker_redirect_among_claudes_stays_unverified(world, db, created_clients):
    body = _register(world, created_clients, "Claude", [CLAUDE_REDIRECT, ATTACKER_REDIRECT])
    assert _row(db, body["client_id"]).verified is False


def test_s3_a_new_organisation_allows_verified_clients_only(world, db, created_clients):
    # No settings row yet, then an admin turns assistants on through the API without mentioning
    # unverified apps: still verified only.
    db.query(McpOrgSettings).filter_by(org_id=world.org.id).delete()
    db.commit()
    admin = world.session("admin")
    assert admin.get("/api/core/mcp/settings").get_json()["allow_unverified_clients"] is False
    saved = admin.put("/api/core/mcp/settings", json={"enabled": True, "allowed_roles": ["builtin:admin"]})
    assert saved.status_code == 200, saved.get_json()
    assert saved.get_json()["allow_unverified_clients"] is False
    body = _register(world, created_clients, "Claude", [ATTACKER_REDIRECT])
    assert _consent(world, body["client_id"], ATTACKER_REDIRECT)[2].status_code == 403


# --- the verified list --------------------------------------------------------------------------


def test_s3_a_dcr_client_with_claudes_redirect_is_verified_and_named_from_the_list(world, db, created_clients):
    world.enable(allow_unverified=False)
    body = _register(world, created_clients, "MCP connector", [CLAUDE_REDIRECT])
    row = _row(db, body["client_id"])
    assert row.verified is True
    assert row.client_name == "Claude"
    assert body["client_name"] == "Claude"

    session, params, resp = _consent(world, body["client_id"], CLAUDE_REDIRECT)
    assert resp.status_code == 200, resp.get_data(as_text=True)[:400]
    html = resp.get_data(as_text=True)
    assert "Verified" in html and "Unverified app" not in html
    assert _approve(session, params).status_code == 302


def test_s3_a_dcr_client_with_chatgpts_redirect_is_verified(world, db, created_clients):
    body = _register(world, created_clients, "anything", [CHATGPT_REDIRECT])
    row = _row(db, body["client_id"])
    assert (row.verified, row.client_name) == (True, "ChatGPT")


def test_s3_a_loopback_only_client_is_never_verified(world, db, created_clients):
    # Any local process can listen on a loopback port and claim to be the client.
    body = _register(world, created_clients, "MCP Inspector", ["http://localhost:6274/oauth/callback"])
    assert _row(db, body["client_id"]).verified is False


def _cimd(monkeypatch, doc):
    monkeypatch.setattr(
        client_registry.socket, "getaddrinfo", lambda host, port, *a, **k: [(2, 1, 6, "", (PUBLIC_IP, 443))]
    )
    spy = mock.Mock(
        return_value=client_registry.FetchResult(
            status=200, headers={"content-type": "application/json"}, body=json.dumps(doc).encode()
        )
    )
    monkeypatch.setattr(client_registry, "http_get_pinned", spy)
    return spy


def test_s3_chatgpts_metadata_document_resolves_to_a_verified_client(world, db, monkeypatch, created_clients):
    world.enable(allow_unverified=False)
    created_clients.append(CHATGPT_CIMD)
    _cimd(
        monkeypatch,
        {
            "client_id": CHATGPT_CIMD,
            "client_name": "ChatGPT connector",
            "redirect_uris": [CHATGPT_REDIRECT],
            "token_endpoint_auth_method": "none",
        },
    )
    resp = _consent(world, CHATGPT_CIMD, CHATGPT_REDIRECT)[2]
    assert resp.status_code == 200, resp.get_data(as_text=True)[:400]
    row = _row(db, CHATGPT_CIMD)
    assert (row.verified, row.client_name) == (True, "ChatGPT")


def test_s3_a_metadata_document_named_chatgpt_elsewhere_is_unverified(world, db, monkeypatch, created_clients):
    world.enable(allow_unverified=False)
    url = "https://chatgpt.attacker.example.test/oauth/client.json"
    created_clients.append(url)
    _cimd(
        monkeypatch,
        {"client_id": url, "client_name": "ChatGPT", "redirect_uris": [ATTACKER_REDIRECT]},
    )
    resp = _consent(world, url, ATTACKER_REDIRECT)[2]
    assert resp.status_code == 403
    assert UNVERIFIED_MESSAGE in resp.get_data(as_text=True)
    assert _row(db, url).verified is False


def test_s3_the_code_list_not_the_database_decides_verified(world, db):
    # A row flagged verified in the database but matching no entry in the list is unverified.
    world.enable(allow_unverified=False)
    world.client_row.verified = True
    db.commit()
    resp = _consent(world, world.client_row.client_id, world.client_row.redirect_uris[0])[2]
    assert resp.status_code == 403
    assert _row(db, world.client_row.client_id).verified is False


# --- the org setting: consent -------------------------------------------------------------------


def test_s3_allowing_unverified_apps_lets_the_consent_through_and_turning_it_off_blocks_it(world, db):
    client_id, redirect = world.client_row.client_id, world.client_row.redirect_uris[0]
    world.enable(allow_unverified=True)
    session, params, resp = _consent(world, client_id, redirect)
    assert resp.status_code == 200
    assert "Unverified app" in resp.get_data(as_text=True)

    world.enable(allow_unverified=False)
    resp = _consent(world, client_id, redirect)[2]
    assert resp.status_code == 403
    assert UNVERIFIED_MESSAGE in resp.get_data(as_text=True)
    # The form rendered while it was allowed can't be posted now.
    assert _approve(session, params).status_code == 403


# --- the org setting: the bearer path ----------------------------------------------------------


def test_s3_a_grant_to_an_unverified_client_gets_403_while_unverified_apps_are_off(world, db):
    grant, access, _r = mint_grant(db, world.users["member"], world.client_row)
    world.enable(allow_unverified=True)
    assert world.anon().get("/api/core/inventory", headers=bearer(access)).status_code == 200

    world.enable(allow_unverified=False)
    off = world.anon().get("/api/core/inventory", headers=bearer(access))
    assert off.status_code == 403
    assert off.get_json() == {"error": "mcp_not_allowed"}
    db.expire_all()
    assert db.get(OAuthGrant, grant.id).revoked_at is None  # blocked, not revoked

    world.enable(allow_unverified=True)
    assert world.anon().get("/api/core/inventory", headers=bearer(access)).status_code == 200  # same token


def test_s3_a_grant_to_a_verified_client_works_while_unverified_apps_are_off(world, db):
    client = make_client(db, name="MCPTEST Claude", redirect_uris=[CLAUDE_REDIRECT])
    _g, access, _r = mint_grant(db, world.users["member"], client)
    world.enable(allow_unverified=False)
    assert world.anon().get("/api/core/inventory", headers=bearer(access)).status_code == 200


# --- the settings API ---------------------------------------------------------------------------


def test_s3_the_settings_api_saves_the_setting_and_writes_an_audit_row(world, db):
    world.enable(allow_unverified=False)
    admin = world.session("admin")
    resp = admin.put(
        "/api/core/mcp/settings",
        json={"enabled": True, "allowed_roles": ["builtin:admin"], "allow_unverified_clients": True},
    )
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["allow_unverified_clients"] is True
    db.expire_all()
    assert db.get(McpOrgSettings, world.org.id).allow_unverified_clients is True
    audit = (
        db.query(AuditLog)
        .filter_by(org_id=world.org.id, action="mcp_settings_updated")
        .order_by(AuditLog.timestamp.desc())
        .first()
    )
    assert audit is not None
    assert audit.user_id == world.users["admin"].id
    assert audit.meta_data["allow_unverified_clients"] is True

    # Saving without the key keeps the current value (older clients of the API).
    kept = admin.put("/api/core/mcp/settings", json={"enabled": True, "allowed_roles": ["builtin:admin"]})
    assert kept.get_json()["allow_unverified_clients"] is True
    off = admin.put(
        "/api/core/mcp/settings",
        json={"enabled": True, "allowed_roles": ["builtin:admin"], "allow_unverified_clients": False},
    )
    assert off.get_json()["allow_unverified_clients"] is False


@pytest.mark.parametrize("value", ["yes", 1, None, []])
def test_s3_the_setting_must_be_a_boolean(world, value):
    resp = world.session("admin").put(
        "/api/core/mcp/settings",
        json={"enabled": True, "allowed_roles": [], "allow_unverified_clients": value},
    )
    assert resp.status_code == 400


def test_s3_only_users_manage_can_change_the_setting(world):
    resp = world.session("member").put(
        "/api/core/mcp/settings",
        json={"enabled": True, "allowed_roles": [], "allow_unverified_clients": True},
    )
    assert resp.status_code == 403


# --- the settings page --------------------------------------------------------------------------


def test_s3_the_settings_page_gives_an_admin_the_unverified_apps_toggle_and_its_confirm(world):
    html = world.session("admin").get("/core/ai-assistants").get_data(as_text=True)
    assert "data-ai-unverified" in html
    assert "Allow apps Biz-E hasn&#39;t verified" in html or "Allow apps Biz-E hasn't verified" in html
    assert "data-ai-unverified-dialog" in html


def test_s3_a_member_gets_no_unverified_apps_toggle(world):
    html = world.session("member").get("/core/ai-assistants").get_data(as_text=True)
    assert "data-ai-unverified" not in html
