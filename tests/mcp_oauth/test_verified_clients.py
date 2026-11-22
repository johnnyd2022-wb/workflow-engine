"""Client verification labels and access for clients outside the verified list."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest import mock

import pytest

from app.features.mcp_oauth.models import McpOrgSettings, OAuthClient, OAuthGrant
from app.features.mcp_oauth.services import client_registry
from tests.mcp_oauth.support import (
    authorize_params,
    authorize_url,
    bearer,
    mint_grant,
    pkce_pair,
    redirect_params,
)

CLAUDE_REDIRECT = "https://claude.ai/api/mcp/auth_callback"
CHATGPT_REDIRECT = "https://chatgpt.com/connector_platform_oauth_redirect"
CHATGPT_CIMD = "https://chatgpt.com/oauth/client.json"
ATTACKER_REDIRECT = "https://claude-ai.attacker.example.test/api/mcp/auth_callback"
PUBLIC_IP = "93.184.216.34"


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
    return db.query(OAuthClient).filter(OAuthClient.client_id == client_id).one()  # global table


# --- the impostor (the finding itself) ----------------------------------------------------------


def test_a_dcr_client_named_claude_needs_consent_and_shows_its_callback_host(world, db, created_clients):
    body = _register(world, created_clients, "Claude", [ATTACKER_REDIRECT])
    row = _row(db, body["client_id"])
    assert row.verified is False
    assert row.client_name == "Claude"  # shown as-is, but only ever as an unverified app

    session, params, resp = _consent(world, body["client_id"], ATTACKER_REDIRECT)
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Unverified app" in html
    assert "claude-ai.attacker.example.test" in html
    assert "badge is-verified" not in html
    grants = db.query(OAuthGrant).filter_by(org_id=world.org.id, client_pk=row.id)
    assert grants.count() == 0

    approved = _approve(session, params)
    assert approved.status_code == 302
    assert redirect_params(approved)["code"].startswith("bzc_")
    assert grants.one().scope == "bize.read"


def test_unverified_unicode_callback_is_displayed_as_punycode_with_port(world, created_clients):
    redirect = "https://cl\u0430ude.example.test:8443/callback"
    body = _register(world, created_clients, "Claude", [redirect])
    session, params, resp = _consent(world, body["client_id"], redirect)
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert '<strong dir="ltr">xn--clude-5ve.example.test:8443</strong>' in html
    assert f'name="redirect_uri" value="{redirect}"' in html
    approved = _approve(session, params)
    assert approved.headers["Location"].startswith("https://xn--clude-5ve.example.test:8443/callback?")


def test_s3_a_claude_name_with_one_attacker_redirect_among_claudes_stays_unverified(world, db, created_clients):
    body = _register(world, created_clients, "Claude", [CLAUDE_REDIRECT, ATTACKER_REDIRECT])
    assert _row(db, body["client_id"]).verified is False


def test_admin_can_enable_mcp_without_a_client_verification_setting(world, db, created_clients):
    db.query(McpOrgSettings).filter_by(org_id=world.org.id).delete()
    db.commit()
    admin = world.session("admin")
    saved = admin.put("/api/core/mcp/settings", json={"enabled": True, "allowed_roles": ["builtin:admin"]})
    assert saved.status_code == 200, saved.get_json()
    body = _register(world, created_clients, "Custom connector", [ATTACKER_REDIRECT])
    assert _consent(world, body["client_id"], ATTACKER_REDIRECT)[2].status_code == 200
    assert _consent(world, body["client_id"], ATTACKER_REDIRECT, who="member")[2].status_code == 403
    assert "allow_unverified_clients" not in saved.get_json()


# --- the verified list --------------------------------------------------------------------------


def test_s3_a_dcr_client_with_claudes_redirect_is_verified_and_named_from_the_list(world, db, created_clients):
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
    url = "https://chatgpt.attacker.example.test/oauth/client.json"
    created_clients.append(url)
    _cimd(
        monkeypatch,
        {"client_id": url, "client_name": "ChatGPT", "redirect_uris": [ATTACKER_REDIRECT]},
    )
    resp = _consent(world, url, ATTACKER_REDIRECT)[2]
    assert resp.status_code == 200
    assert "Unverified app" in resp.get_data(as_text=True)
    assert _row(db, url).verified is False


def test_s3_the_code_list_not_the_database_decides_verified(world, db):
    # A row flagged verified in the database but matching no entry in the list is unverified.
    world.client_row.verified = True
    db.commit()
    resp = _consent(world, world.client_row.client_id, world.client_row.redirect_uris[0])[2]
    assert resp.status_code == 200
    assert "Unverified app" in resp.get_data(as_text=True)
    assert _row(db, world.client_row.client_id).verified is False


@pytest.mark.parametrize("revoked", [False, True])
def test_legacy_unverified_grant_must_still_be_active(world, db, revoked):
    settings = db.get(McpOrgSettings, world.org.id)
    settings.allow_unverified_clients = True
    grant, access, refresh = mint_grant(db, world.users["member"], world.client_row)

    # Under the previous policy, this change blocked use of the grant without revoking it.
    settings.allow_unverified_clients = False
    if revoked:
        grant.revoked_at = datetime.now(UTC)
    db.commit()

    anon = world.anon()
    resp = anon.get("/api/core/inventory", headers=bearer(access))
    refreshed = anon.post(
        "/oauth/token",
        data={"grant_type": "refresh_token", "refresh_token": refresh, "client_id": world.client_row.client_id},
    )
    if revoked:
        assert resp.status_code == 401
        assert resp.get_json() == {"error": "invalid_token"}
        assert refreshed.status_code == 400
        assert refreshed.get_json()["error"] == "invalid_grant"
    else:
        assert resp.status_code == 200
        assert "Org A Juniper" in resp.get_data(as_text=True)
        assert "Org B Secret Botanical" not in resp.get_data(as_text=True)
        assert refreshed.status_code == 200
        assert refreshed.get_json()["scope"] == "bize.read"


# --- review follow-ups ---------------------------------------------------------------------------


def test_s3_the_grants_list_reads_verified_from_the_code_list_without_writing(world, db):
    # Flagged verified in the database but on no list entry: the Settings list says unverified, and
    # the GET leaves the row as it was.
    world.client_row.verified = True
    db.commit()
    mint_grant(db, world.users["member"], world.client_row)
    grants = world.session("admin").get("/api/core/mcp/grants").get_json()["grants"]
    assert [g["verified"] for g in grants] == [False]
    db.expire_all()
    assert db.get(OAuthClient, world.client_row.id).verified is True


def test_s3_an_unverified_client_on_a_vendor_host_is_logged_as_a_near_miss(world, created_clients, monkeypatch):
    from app.features.mcp_oauth.services import client_registry as registry

    seen = []
    monkeypatch.setattr(registry.logger, "warning", lambda event, **kw: seen.append((event, kw)))
    _register(world, created_clients, "Claude", ["https://claude.ai/api/mcp/other_callback"])
    assert seen and seen[0][0] == "mcp.client_verification_near_miss"
    assert seen[0][1]["vendor_host"] == "claude.ai"
