"""Native apps on loopback: a port-less registered redirect matches any port (RFC 8252 7.3).

Claude Code publishes a client ID metadata document whose redirect URIs are
``http://localhost/callback`` and ``http://127.0.0.1/callback`` and then listens on whichever port
is free. Biz-E used to refuse that document outright, so Claude Code could not connect at all.
"""

from __future__ import annotations

import json

import pytest

from app.features.mcp_oauth.services import client_registry
from tests.mcp_oauth.support import (
    RESOURCE,
    TEST_NAME_PREFIX,
    authorize_params,
    authorize_url,
    make_client,
    pkce_pair,
    redirect_params,
)

PUBLIC_IP = "93.184.216.34"
CLAUDE_CODE_CLIENT_ID = "https://claude.ai/oauth/claude-code-client-metadata"
# Verbatim from https://claude.ai/oauth/claude-code-client-metadata, fetched 2026-11-23.
CLAUDE_CODE_DOCUMENT = {
    "client_id": CLAUDE_CODE_CLIENT_ID,
    "client_name": "Claude Code",
    "client_uri": "https://claude.ai",
    "redirect_uris": ["http://localhost/callback", "http://127.0.0.1/callback"],
    "grant_types": ["authorization_code", "refresh_token"],
    "response_types": ["code"],
    "token_endpoint_auth_method": "none",
}


@pytest.fixture
def claude_code_document(monkeypatch):
    monkeypatch.setattr(
        client_registry.socket, "getaddrinfo", lambda host, port, *a, **k: [(2, 1, 6, "", (PUBLIC_IP, 443))]
    )
    monkeypatch.setattr(
        client_registry,
        "http_get_pinned",
        lambda *a, **k: client_registry.FetchResult(
            status=200, headers={"content-type": "application/json"}, body=json.dumps(CLAUDE_CODE_DOCUMENT).encode()
        ),
    )


@pytest.mark.parametrize("uri", ["http://localhost/callback", "http://127.0.0.1/cb", "http://[::1]/cb"])
def test_dcr_accepts_a_loopback_redirect_uri_without_a_port(world, uri):
    resp = world.anon().post(
        "/oauth/register", json={"client_name": f"{TEST_NAME_PREFIX} portless", "redirect_uris": [uri]}
    )
    assert resp.status_code == 201, resp.get_json()


def test_claude_codes_real_metadata_document_signs_in_and_gets_a_token(world, claude_code_document):
    redirect_uri = "http://localhost:53817/callback"
    verifier, challenge = pkce_pair()
    params = authorize_params(CLAUDE_CODE_CLIENT_ID, challenge, redirect_uri=redirect_uri)
    session = world.session("member")
    consent = session.get(authorize_url(params))
    assert consent.status_code == 200, consent.get_data(as_text=True)[:300]
    assert "Claude Code" in consent.get_data(as_text=True)

    resp = session.post("/oauth/authorize", data={**params, "decision": "approve", "access_level": "read"})
    assert resp.status_code == 302
    assert resp.headers["Location"].startswith(redirect_uri + "?")
    form = {
        "grant_type": "authorization_code",
        "code": redirect_params(resp)["code"],
        "code_verifier": verifier,
        "redirect_uri": redirect_uri,
        "client_id": CLAUDE_CODE_CLIENT_ID,
        "resource": RESOURCE,
    }
    token = world.anon().post("/oauth/token", data=form)
    assert token.status_code == 200, token.get_json()
    assert token.get_json()["access_token"]


def test_the_token_exchange_still_needs_the_exact_redirect_uri_used_to_sign_in(world, claude_code_document):
    verifier, challenge = pkce_pair()
    params = authorize_params(CLAUDE_CODE_CLIENT_ID, challenge, redirect_uri="http://localhost:53817/callback")
    session = world.session("member")
    assert session.get(authorize_url(params)).status_code == 200
    resp = session.post("/oauth/authorize", data={**params, "decision": "approve", "access_level": "read"})
    form = {
        "grant_type": "authorization_code",
        "code": redirect_params(resp)["code"],
        "code_verifier": verifier,
        "redirect_uri": "http://localhost:60000/callback",  # registered shape, but not the one signed in with
        "client_id": CLAUDE_CODE_CLIENT_ID,
        "resource": RESOURCE,
    }
    assert world.anon().post("/oauth/token", data=form).status_code == 400


@pytest.mark.parametrize(
    "requested",
    [
        "http://localhost:53817/other",  # different path
        "http://localhost:53817/callback?x=1",  # different query
        "http://127.0.0.1:53817/callback",  # different loopback host from the one registered
        "https://localhost:53817/callback",  # different scheme
        "http://localhost.evil.example:53817/callback",  # not loopback
        "http://user@localhost:53817/callback",
        "http://localhost:53817/callback#frag",
        "http://localhost:99999/callback",  # invalid port
    ],
)
def test_only_the_port_of_a_loopback_redirect_may_differ(world, db, requested):
    client = make_client(db, redirect_uris=["http://localhost/callback"])
    _verifier, challenge = pkce_pair()
    resp = world.session("admin").get(
        authorize_url(authorize_params(client.client_id, challenge, redirect_uri=requested))
    )
    assert resp.status_code == 400
    assert "Location" not in resp.headers


def test_an_https_redirect_never_matches_on_a_different_port():
    registered = ["https://assistant.example.test/callback"]
    assert client_registry.redirect_uri_matches("https://assistant.example.test/callback", registered)
    assert not client_registry.redirect_uri_matches("https://assistant.example.test:8443/callback", registered)


def test_a_loopback_redirect_registered_with_a_port_matches_any_port():
    registered = ["http://127.0.0.1:9000/cb"]
    assert client_registry.redirect_uri_matches("http://127.0.0.1:9000/cb", registered)
    assert client_registry.redirect_uri_matches("http://127.0.0.1:51000/cb", registered)
    assert client_registry.redirect_uri_matches("http://127.0.0.1/cb", registered)
