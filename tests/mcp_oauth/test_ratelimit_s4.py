"""Design review S4 on the MCP side.

1. With more than one gunicorn worker and no shared rate-limit store, every per-grant limit is
   per worker. MCP must then refuse to be switched on (settings API 409, `workflow mcp enable`
   fails), and say why. Single-worker local dev keeps working on memory.
2. A `calculation` operation can walk the whole cost graph in one request, so on the bearer path it
   gets a lower per-grant limit (30 a minute by default) on top of the 120 for everything.
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from app.features.mcp_oauth.models import McpOrgSettings
from app.features.mcp_oauth.services import rate_limit
from tests.mcp_oauth.support import bearer, mint_grant

CALCULATION = "/api/core/inventory/expired-materials"  # x-bize.kind: calculation (inventory.yaml)
RECORD_OR_LIST = "/api/core/inventory"  # x-bize.kind: list


def _enabled(db, org_id) -> bool:
    db.expire_all()
    row = db.get(McpOrgSettings, org_id)
    return bool(row and row.enabled)


# --- 1. no shared store, more than one worker: MCP stays off -----------------------------------


@pytest.fixture
def two_workers_no_store(monkeypatch):
    """What the images run (WEB_CONCURRENCY=2) with no Valkey password, so no shared store."""
    from app.utils.config_loader import config

    monkeypatch.setenv("WEB_CONCURRENCY", "2")
    monkeypatch.delenv("VALKEY_PASSWORD", raising=False)
    assert not config.get("ratelimit", "storage_uri", fallback=None), "this test needs a config with no store"


def test_s4_the_settings_api_refuses_to_turn_mcp_on_without_a_shared_store(world, db, two_workers_no_store):
    world.enable(enabled=False, roles=[])
    resp = world.session("admin").put(
        "/api/core/mcp/settings", json={"enabled": True, "allowed_roles": ["builtin:admin"]}
    )
    assert resp.status_code == 409, resp.get_json()
    message = resp.get_json()["error"]
    assert "can't be switched on" in message
    # The organisation's admin can't run scripts: the operator detail stays out of their message.
    assert "VALKEY" not in message and "run_valkey" not in message and "worker" not in message
    assert _enabled(db, world.org.id) is False


def test_s4_turning_mcp_off_is_always_allowed(world, db, two_workers_no_store):
    world.enable(enabled=True, roles=["admin"])
    resp = world.session("admin").put("/api/core/mcp/settings", json={"enabled": False, "allowed_roles": []})
    assert resp.status_code == 200, resp.get_json()
    assert _enabled(db, world.org.id) is False


def test_s4_the_cli_refuses_to_turn_mcp_on_without_a_shared_store(world, db, two_workers_no_store):
    from app.cli import cli

    world.enable(enabled=False, roles=[])
    org_id = world.org.id  # the CLI closes the shared session
    result = CliRunner().invoke(cli, ["mcp", "enable", "--org-id", str(org_id), "--roles", "admin"])
    assert result.exit_code != 0
    assert "rate-limit store" in result.output and "run_valkey.sh" in result.output
    assert _enabled(db, org_id) is False


def test_s4_one_worker_on_memory_can_still_turn_mcp_on(world, db, monkeypatch):
    monkeypatch.setenv("WEB_CONCURRENCY", "1")
    world.enable(enabled=False, roles=[])
    resp = world.session("admin").put(
        "/api/core/mcp/settings", json={"enabled": True, "allowed_roles": ["builtin:admin"]}
    )
    assert resp.status_code == 200, resp.get_json()


# --- 2. calculations get a lower per-grant limit -----------------------------------------------


@pytest.fixture
def token(world):
    rate_limit._state.clear()
    _grant, access, _refresh = mint_grant(world.db, world.users["admin"], world.client_row)
    yield access
    rate_limit._state.clear()


def test_s4_the_31st_calculation_in_a_minute_on_one_grant_is_a_429(world, token):
    client = world.anon()
    codes = [client.get(CALCULATION, headers=bearer(token)).status_code for _ in range(31)]
    assert 429 not in codes[:30], codes
    assert codes[30] == 429
    refused = client.get(CALCULATION, headers=bearer(token))
    assert refused.status_code == 429 and int(refused.headers["Retry-After"]) >= 1


def test_s4_the_calculation_limit_leaves_other_reads_alone(world, token):
    client = world.anon()
    for _ in range(31):
        client.get(CALCULATION, headers=bearer(token))
    assert client.get(RECORD_OR_LIST, headers=bearer(token)).status_code == 200


def test_s4_the_calculation_limit_is_configurable(world, token, monkeypatch):
    from app.utils.config_loader import config

    monkeypatch.setitem(config.config["mcp"], "calculation_requests_per_minute", "2")
    client = world.anon()
    codes = [client.get(CALCULATION, headers=bearer(token)).status_code for _ in range(3)]
    assert 429 not in codes[:2] and codes[2] == 429


def test_s4_calculation_endpoints_come_from_the_openapi_overlay(world):
    endpoints = rate_limit.calculation_endpoints(world.app)
    assert "core.list_expired_materials" in endpoints
    assert "costing.get_stock_value" in endpoints
    assert "core.list_inventory" not in endpoints


# --- 3. a store outage on the bearer path fails closed ------------------------------------------


def test_s4_an_unreachable_store_refuses_bearer_requests_with_a_503(world, token, monkeypatch):
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    monkeypatch.setitem(world.app.config, "RATELIMIT_STORAGE_URI", f"redis://:x@127.0.0.1:{port}/0")
    rate_limit._state.clear()
    resp = world.anon().get(RECORD_OR_LIST, headers=bearer(token))
    rate_limit._state.clear()
    assert resp.status_code == 503, resp.get_data(as_text=True)[:200]
    assert resp.get_json()["error"] == "temporarily_unavailable"
    assert int(resp.headers["Retry-After"]) >= 1
