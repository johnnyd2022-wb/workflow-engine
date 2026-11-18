"""Design review S1 (part 2): an assistant's token is accepted only from the MCP container.

A token's audience is the MCP server, but the app used to accept it from any caller, so anyone
holding one could call the public app through Cloudflare and skip the MCP server's row caps, rate
limit and audit. The MCP container reaches the app over the private Docker network
(scripts/run_mcp.sh), never through the edge, and Cloudflare stamps ``CF-Connecting-IP`` and
``CF-Ray`` on every request it forwards. With ``[mcp] bearer_internal_only`` on, a bearer request
carrying either header is refused before the token is looked up.
"""

from __future__ import annotations

import configparser
from pathlib import Path

import pytest

from app.api.middleware import tenant_context
from app.features.mcp_oauth.services import bearer_auth
from app.utils.config_loader import config
from tests.mcp_oauth.support import bearer, mint_grant

CONFIG_DIR = Path(__file__).resolve().parents[2] / "app" / "config"
WWW_INVALID = 'Bearer error="invalid_token"'
EDGE_HEADERS = [
    {"CF-Connecting-IP": "203.0.113.7"},
    {"CF-Ray": "8a1b2c3d4e5f6a7b-AKL"},
    {"cf-connecting-ip": "2001:db8::1", "CF-Ray": "8a1b2c3d4e5f6a7b-SYD"},
]


def _internal_only(monkeypatch, on: bool) -> None:
    # raising=False: on code without the setting this still runs, and the test fails on behaviour.
    monkeypatch.setattr(type(config), "mcp_bearer_internal_only", property(lambda self: on), raising=False)


def _token(world, who="member"):
    _grant, access, _refresh = mint_grant(world.db, world.users[who], world.client_row)
    return access


class _LogSpy:
    """Records what tenant_context logs. structlog caches loggers on first use, so capture_logs()
    misses them once another test has logged; replacing the module's LOGGER does not."""

    def __init__(self, real):
        self.real = real
        self.events: list[dict] = []

    def __getattr__(self, level):
        def record(event, **kwargs):
            self.events.append({"event": event, "level": level, **kwargs})
            return getattr(self.real, level)(event, **kwargs)

        return record


def _spy_logs(monkeypatch) -> _LogSpy:
    spy = _LogSpy(tenant_context.LOGGER)
    monkeypatch.setattr(tenant_context, "LOGGER", spy)
    return spy


def _count_lookups(monkeypatch) -> list:
    calls = []
    real = bearer_auth.authenticate

    def spy(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(bearer_auth, "authenticate", spy)
    return calls


@pytest.mark.parametrize("edge", EDGE_HEADERS, ids=["cf-connecting-ip", "cf-ray", "both"])
def test_s1b_a_token_arriving_through_cloudflare_is_refused_before_lookup(world, monkeypatch, edge):
    _internal_only(monkeypatch, True)
    access = _token(world)
    lookups = _count_lookups(monkeypatch)
    logs = _spy_logs(monkeypatch)
    resp = world.anon().get("/api/core/inventory", headers={**bearer(access), **edge})
    assert resp.status_code == 401, resp.get_data(as_text=True)[:300]
    assert resp.get_json() == {"error": "invalid_token"}
    assert resp.headers.get("WWW-Authenticate") == WWW_INVALID
    assert lookups == [], "the token must not be looked up when it came through the edge"
    assert "Org A Juniper" not in resp.get_data(as_text=True)
    assert any(entry["event"] == "mcp.bearer_from_edge" for entry in logs.events), logs.events
    # The log line never carries the token.
    assert access not in repr(logs.events)


def test_s1b_a_garbage_token_through_cloudflare_gets_the_same_answer(world, monkeypatch):
    _internal_only(monkeypatch, True)
    lookups = _count_lookups(monkeypatch)
    resp = world.anon().get(
        "/api/core/inventory", headers={**bearer("bza_not-a-real-token"), "CF-Connecting-IP": "203.0.113.7"}
    )
    assert resp.status_code == 401
    assert resp.get_json() == {"error": "invalid_token"}
    assert lookups == []


def test_s1b_a_refresh_token_through_cloudflare_is_refused_before_lookup(world, monkeypatch):
    # parse_bearer hands bzr_/bzc_ values to the bearer path too; the edge rule covers every prefix.
    _internal_only(monkeypatch, True)
    _grant, _access, refresh = mint_grant(world.db, world.users["member"], world.client_row)
    lookups = _count_lookups(monkeypatch)
    resp = world.anon().get("/api/core/inventory", headers={**bearer(refresh), "CF-Ray": "8a1b2c3d4e5f6a7b-AKL"})
    assert resp.status_code == 401
    assert resp.get_json() == {"error": "invalid_token"}
    assert lookups == []


def test_s1b_a_token_from_the_private_network_works_as_today(world, monkeypatch):
    _internal_only(monkeypatch, True)
    access = _token(world)
    lookups = _count_lookups(monkeypatch)
    resp = world.anon().get("/api/core/inventory", headers=bearer(access))
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    assert "Org A Juniper" in resp.get_data(as_text=True)
    assert lookups == [1]


@pytest.mark.parametrize("edge", EDGE_HEADERS, ids=["cf-connecting-ip", "cf-ray", "both"])
def test_s1b_with_the_setting_off_an_edge_token_works_as_today(world, monkeypatch, edge):
    _internal_only(monkeypatch, False)
    access = _token(world)
    resp = world.anon().get("/api/core/inventory", headers={**bearer(access), **edge})
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    assert "Org A Juniper" in resp.get_data(as_text=True)


@pytest.mark.parametrize("edge", EDGE_HEADERS, ids=["cf-connecting-ip", "cf-ray", "both"])
def test_s1b_a_session_request_through_cloudflare_is_unaffected(world, monkeypatch, edge):
    _internal_only(monkeypatch, True)
    resp = world.session("member").get("/api/core/inventory", headers=edge)
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    assert "Org A Juniper" in resp.get_data(as_text=True)


def test_s1b_a_session_request_carrying_a_bearer_header_through_cloudflare_stays_a_session_request(world, monkeypatch):
    # A session user always wins (spec "Bearer path" step 6); the edge rule never applies to it.
    _internal_only(monkeypatch, True)
    access = _token(world)
    resp = world.session("member").get(
        "/api/core/inventory", headers={**bearer(access), "CF-Connecting-IP": "203.0.113.7"}
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]


def test_s1b_an_anonymous_request_through_cloudflare_is_unaffected(world, monkeypatch):
    _internal_only(monkeypatch, True)
    through_edge = world.anon().get("/api/core/inventory", headers={"CF-Connecting-IP": "203.0.113.7"})
    direct = world.anon().get("/api/core/inventory")
    assert through_edge.status_code == direct.status_code
    assert through_edge.get_json() == direct.get_json()
    assert through_edge.get_json() != {"error": "invalid_token"}


def _ini_flag(name: str):
    parser = configparser.ConfigParser()
    parser.read(CONFIG_DIR / name)
    if not parser.has_option("mcp", "bearer_internal_only"):
        return None
    return parser.getboolean("mcp", "bearer_internal_only")


@pytest.mark.parametrize("name", ["test.ini", "test.ini.template", "prod.ini", "prod.ini.template"])
def test_s1b_deployed_environments_accept_tokens_only_from_the_private_network(name):
    assert _ini_flag(name) is True, f"{name} [mcp] bearer_internal_only must be true"


@pytest.mark.parametrize("name", ["local.ini", "local.ini.template"])
def test_s1b_local_development_accepts_tokens_from_anywhere(name):
    # Local has no Cloudflare in front, and a developer may point an assistant at a local tunnel.
    assert _ini_flag(name) is False, f"{name} [mcp] bearer_internal_only must be false"


def test_s1b_the_setting_defaults_to_off_when_missing(monkeypatch):
    monkeypatch.setattr(type(config), "get", lambda self, section, key, fallback=None: fallback)
    monkeypatch.setattr(type(config), "getboolean", lambda self, section, key, fallback=False: fallback)
    assert type(config).mcp_bearer_internal_only.fget(config) is False
