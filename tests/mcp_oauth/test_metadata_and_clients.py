"""AC1-AC3: authorization-server metadata, client registration, metadata-URL clients."""

from __future__ import annotations

import json
from unittest import mock

import pytest

from app.features.mcp_oauth.models import OAuthClient
from app.features.mcp_oauth.services import client_registry
from tests.mcp_oauth.support import (
    ISSUER,
    REDIRECT,
    TEST_NAME_PREFIX,
    authorize_params,
    authorize_url,
    pkce_pair,
)


def test_ac1_metadata_returns_the_documented_fields_with_the_configured_issuer(world):
    resp = world.anon().get("/.well-known/oauth-authorization-server")
    assert resp.status_code == 200
    body = resp.get_json()
    assert ISSUER.startswith("http")
    assert body["issuer"] == ISSUER
    assert body["authorization_endpoint"] == f"{ISSUER}/oauth/authorize"
    assert body["token_endpoint"] == f"{ISSUER}/oauth/token"
    assert body["registration_endpoint"] == f"{ISSUER}/oauth/register"
    assert body["revocation_endpoint"] == f"{ISSUER}/oauth/revoke"
    assert body["response_types_supported"] == ["code"]
    assert body["grant_types_supported"] == ["authorization_code", "refresh_token"]
    assert body["code_challenge_methods_supported"] == ["S256"]
    assert body["token_endpoint_auth_methods_supported"] == ["none"]
    assert body["scopes_supported"] == ["bize.read"]
    assert body["client_id_metadata_document_supported"] is True


def test_ac1_metadata_needs_no_sign_in_and_no_session_cookie(world):
    resp = world.anon().get("/.well-known/oauth-authorization-server")
    assert resp.status_code == 200
    assert "Set-Cookie" not in resp.headers


def _register(client, payload, **kwargs):
    return client.post("/oauth/register", json=payload, **kwargs)


def test_ac2_dcr_with_one_https_redirect_uri_returns_201_and_a_client_id(world, db):
    resp = _register(world.anon(), {"client_name": f"{TEST_NAME_PREFIX} DCR", "redirect_uris": [REDIRECT]})
    assert resp.status_code == 201, resp.get_json()
    body = resp.get_json()
    assert body["client_id"]
    assert body["redirect_uris"] == [REDIRECT]
    assert body["token_endpoint_auth_method"] == "none"
    row = db.query(OAuthClient).filter_by(client_id=body["client_id"]).one()
    assert row.verified is False
    assert row.registration == "dcr"
    assert "Set-Cookie" not in resp.headers


def test_ac2_dcr_needs_no_csrf_token_and_no_session(world, flask_app, monkeypatch):
    monkeypatch.setitem(flask_app.config, "WTF_CSRF_ENABLED", True)
    resp = _register(world.anon(), {"client_name": f"{TEST_NAME_PREFIX} CSRF", "redirect_uris": [REDIRECT]})
    assert resp.status_code == 201


@pytest.mark.parametrize(
    "uri",
    [
        "javascript:alert(1)",
        "http://evil.example/callback",
        "http://localhost/callback",  # a loopback redirect carries its port
        "ftp://files.example/cb",
        "https://assistant.example.test/cb#fragment",
        "https://user:secret@assistant.example.test/cb",
        "//assistant.example.test/cb",
        "/relative/path",
        "https://",
        "",
        "x" * 3000,
    ],
)
def test_ac2_dcr_rejects_an_unsafe_redirect_uri(world, uri):
    resp = _register(world.anon(), {"client_name": f"{TEST_NAME_PREFIX} bad", "redirect_uris": [uri]})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "invalid_redirect_uri"


@pytest.mark.parametrize("uri", ["http://localhost:8123/cb", "http://127.0.0.1:9000/cb"])
def test_ac2_dcr_accepts_a_loopback_http_redirect_uri_with_a_port(world, uri):
    resp = _register(world.anon(), {"client_name": f"{TEST_NAME_PREFIX} loop", "redirect_uris": [uri]})
    assert resp.status_code == 201


def test_ac2_dcr_allows_one_to_five_redirect_uris(world):
    five = [f"https://assistant.example.test/cb{i}" for i in range(5)]
    assert (
        _register(world.anon(), {"client_name": f"{TEST_NAME_PREFIX} five", "redirect_uris": five}).status_code == 201
    )
    six = [*five, "https://assistant.example.test/cb5"]
    resp = _register(world.anon(), {"client_name": f"{TEST_NAME_PREFIX} six", "redirect_uris": six})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "invalid_redirect_uri"
    none = _register(world.anon(), {"client_name": f"{TEST_NAME_PREFIX} none", "redirect_uris": []})
    assert none.status_code == 400


@pytest.mark.parametrize(
    "payload",
    [
        {"redirect_uris": [REDIRECT]},  # no name
        {"client_name": "", "redirect_uris": [REDIRECT]},
        {"client_name": 7, "redirect_uris": [REDIRECT]},
        {"client_name": "n" * 200, "redirect_uris": [REDIRECT]},
        {"client_name": "ok", "redirect_uris": REDIRECT},  # not a list
        {"client_name": "ok", "redirect_uris": [REDIRECT], "token_endpoint_auth_method": "client_secret_basic"},
        {"client_name": "ok", "redirect_uris": [REDIRECT], "grant_types": ["password"]},
    ],
)
def test_ac2_dcr_rejects_invalid_client_metadata(world, payload):
    resp = _register(world.anon(), payload)
    assert resp.status_code == 400
    assert resp.get_json()["error"] in {"invalid_client_metadata", "invalid_redirect_uri"}


def test_ac2_dcr_rejects_a_non_json_body(world):
    resp = world.anon().post("/oauth/register", data="not json", content_type="text/plain")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "invalid_client_metadata"


def test_ac2_the_11th_registration_from_one_ip_in_an_hour_is_429(world):
    client = world.anon()
    for i in range(10):
        resp = _register(client, {"client_name": f"{TEST_NAME_PREFIX} rl{i}", "redirect_uris": [REDIRECT]})
        assert resp.status_code == 201, (i, resp.get_json())
    eleventh = _register(client, {"client_name": f"{TEST_NAME_PREFIX} rl10", "redirect_uris": [REDIRECT]})
    assert eleventh.status_code == 429
    # A different address is not affected.
    other = _register(world.anon(), {"client_name": f"{TEST_NAME_PREFIX} other", "redirect_uris": [REDIRECT]})
    assert other.status_code == 201


# --- AC3: metadata-URL clients (SSRF) -----------------------------------------------------------

PUBLIC_IP = "93.184.216.34"


@pytest.fixture
def fetch_spy(monkeypatch):
    """Replace the network layer: any call is recorded, and none leaves the process."""
    spy = mock.Mock(name="http_get_pinned")
    monkeypatch.setattr(client_registry, "http_get_pinned", spy)
    return spy


def _authorize_with_client_id(world, client_id):
    _verifier, challenge = pkce_pair()
    session = world.session("admin")
    return session.get(authorize_url(authorize_params(client_id, challenge)))


@pytest.mark.parametrize(
    "client_id",
    [
        "https://127.0.0.1/client.json",
        "https://10.1.2.3/client.json",
        "https://192.168.1.10/client.json",
        "https://172.16.0.5/client.json",
        "https://169.254.169.254/latest/meta-data",
        "https://[::1]/client.json",
        "https://[::ffff:127.0.0.1]/client.json",
        "https://0.0.0.0/client.json",
        "https://100.64.0.1/client.json",
        "https://localhost/client.json",
        "https://user:pw@assistant.example.test/client.json",
        "http://assistant.example.test/client.json",  # not https: treated as an unknown plain client_id
    ],
)
def test_ac3_a_metadata_url_client_id_pointing_at_a_private_address_is_refused(world, db, fetch_spy, client_id):
    resp = _authorize_with_client_id(world, client_id)
    assert resp.status_code == 400
    assert "Location" not in resp.headers
    assert fetch_spy.call_count == 0
    assert db.query(OAuthClient).filter(OAuthClient.client_id == client_id).count() == 0


def test_ac3_a_hostname_that_resolves_to_a_private_address_is_refused(world, db, fetch_spy, monkeypatch):
    def fake_getaddrinfo(host, port, *args, **kwargs):
        return [(2, 1, 6, "", ("10.0.0.7", 443))]

    monkeypatch.setattr(client_registry.socket, "getaddrinfo", fake_getaddrinfo)
    url = "https://rebind.example.test/client.json"
    resp = _authorize_with_client_id(world, url)
    assert resp.status_code == 400
    assert fetch_spy.call_count == 0
    assert db.query(OAuthClient).filter(OAuthClient.client_id == url).count() == 0


def test_ac3_one_private_address_among_public_ones_refuses_the_whole_name(world, fetch_spy, monkeypatch):
    def fake_getaddrinfo(host, port, *args, **kwargs):
        return [(2, 1, 6, "", (PUBLIC_IP, 443)), (2, 1, 6, "", ("127.0.0.1", 443))]

    monkeypatch.setattr(client_registry.socket, "getaddrinfo", fake_getaddrinfo)
    assert _authorize_with_client_id(world, "https://mixed.example.test/c.json").status_code == 400
    assert fetch_spy.call_count == 0


def _public_dns(monkeypatch):
    monkeypatch.setattr(
        client_registry.socket, "getaddrinfo", lambda host, port, *a, **k: [(2, 1, 6, "", (PUBLIC_IP, 443))]
    )


def _doc(url, **overrides):
    doc = {
        "client_id": url,
        "client_name": f"{TEST_NAME_PREFIX} Document Client",
        "redirect_uris": [REDIRECT],
        "token_endpoint_auth_method": "none",
    }
    doc.update(overrides)
    return doc


def _result(status=200, body=None, headers=None):
    return client_registry.FetchResult(
        status=status, headers=headers or {"content-type": "application/json"}, body=json.dumps(body).encode()
    )


def test_ac3_a_redirecting_metadata_url_is_refused(world, db, fetch_spy, monkeypatch):
    _public_dns(monkeypatch)
    fetch_spy.return_value = _result(302, {}, {"location": "https://127.0.0.1/steal"})
    url = "https://redirector.example.test/client.json"
    resp = _authorize_with_client_id(world, url)
    assert resp.status_code == 400
    assert "Location" not in resp.headers
    assert db.query(OAuthClient).filter(OAuthClient.client_id == url).count() == 0
    kwargs = fetch_spy.call_args.kwargs
    assert kwargs.get("timeout") == 5
    assert kwargs.get("max_bytes") == 64 * 1024


def test_ac3_a_document_whose_client_id_differs_from_its_url_is_refused(world, db, fetch_spy, monkeypatch):
    _public_dns(monkeypatch)
    url = "https://liar.example.test/client.json"
    fetch_spy.return_value = _result(200, _doc("https://someone-else.example.test/client.json"))
    assert _authorize_with_client_id(world, url).status_code == 400
    assert db.query(OAuthClient).filter(OAuthClient.client_id == url).count() == 0


def test_ac3_a_document_with_an_unsafe_redirect_uri_is_refused(world, fetch_spy, monkeypatch):
    _public_dns(monkeypatch)
    url = "https://unsafe.example.test/client.json"
    fetch_spy.return_value = _result(200, _doc(url, redirect_uris=["javascript:alert(1)"]))
    assert _authorize_with_client_id(world, url).status_code == 400


def test_ac3_a_valid_document_creates_an_unverified_client_cached_for_a_day(world, db, fetch_spy, monkeypatch):
    _public_dns(monkeypatch)
    url = "https://good.example.test/client.json"
    fetch_spy.return_value = _result(200, _doc(url))
    first = _authorize_with_client_id(world, url)
    assert first.status_code == 200, first.get_data(as_text=True)[:400]
    row = db.query(OAuthClient).filter_by(client_id=url).one()
    assert row.registration == "metadata_url"
    assert row.metadata_url == url
    assert row.verified is False
    assert row.redirect_uris == [REDIRECT]
    _authorize_with_client_id(world, url)
    assert fetch_spy.call_count == 1  # second request served from the cache
    # Past 24 hours the document is fetched again.
    from datetime import UTC, datetime, timedelta

    row.metadata_fetched_at = datetime.now(UTC) - timedelta(hours=25)
    db.commit()
    _authorize_with_client_id(world, url)
    assert fetch_spy.call_count == 2


@pytest.mark.parametrize(
    "address,public",
    [
        ("93.184.216.34", True),
        ("2606:2800:220:1:248:1893:25c8:1946", True),
        ("127.0.0.1", False),
        ("10.0.0.1", False),
        ("172.31.255.255", False),
        ("192.168.0.1", False),
        ("169.254.169.254", False),
        ("100.64.0.1", False),
        ("0.0.0.0", False),
        ("224.0.0.1", False),
        ("::1", False),
        ("fe80::1", False),
        ("fc00::1", False),
        ("::ffff:10.0.0.1", False),
        ("2002:7f00:0001::", False),  # 6to4 wrapping 127.0.0.1
    ],
)
def test_ac3_public_address_check(address, public):
    assert client_registry.is_public_address(address) is public
