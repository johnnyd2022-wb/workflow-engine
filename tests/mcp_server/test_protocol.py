"""AC24 (protected-resource metadata, 401 with resource_metadata) and the server's plumbing.

Spec: ``.agents/specs/public-mcp.md``, "bize_mcp server (8.2c)".
"""

from __future__ import annotations

import httpx2
import pytest

from tests.mcp_oauth.support import ISSUER, RESOURCE
from tests.mcp_server.conftest import token_for
from tests.mcp_server.support import Mcp, StubTransport, json_response, make_config, run_coroutine, stub_app

METADATA_PATH = "/.well-known/oauth-protected-resource"


def _origin(url: str) -> str:
    parts = httpx2.URL(url)
    return f"{parts.scheme}://{parts.netloc.decode() if isinstance(parts.netloc, bytes) else parts.netloc}"


def test_ac24_protected_resource_metadata_matches_the_spec():
    with Mcp(stub_app({})) as mcp:
        response = mcp.request("GET", METADATA_PATH)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {
        "resource": RESOURCE,
        "authorization_servers": [ISSUER],
        "scopes_supported": ["bize.read"],
        "bearer_methods_supported": ["header"],
    }


def test_ac24_metadata_is_also_served_at_the_path_suffixed_url():
    """RFC 9728 clients that build the URL themselves ask for ``.../oauth-protected-resource/mcp``."""
    with Mcp(stub_app({})) as mcp:
        plain = mcp.request("GET", METADATA_PATH).json()
        suffixed = mcp.request("GET", f"{METADATA_PATH}/mcp")
    assert suffixed.status_code == 200
    assert suffixed.json() == plain


def test_ac24_metadata_needs_no_token_and_never_calls_the_app():
    transport = stub_app({})
    with Mcp(transport) as mcp:
        mcp.request("GET", METADATA_PATH)
    assert transport.requests == []


@pytest.mark.parametrize("method,path", [("POST", "/mcp"), ("POST", "/mcp/"), ("GET", "/mcp"), ("DELETE", "/mcp")])
def test_ac24_mcp_without_a_token_gets_401_with_resource_metadata(method, path):
    transport = stub_app({})
    with Mcp(transport) as mcp:
        response = mcp.request(method, path, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert response.status_code == 401
    expected = f'Bearer resource_metadata="{_origin(RESOURCE)}{METADATA_PATH}"'
    assert response.headers["www-authenticate"] == expected
    assert transport.requests == [], "an unauthenticated request must never reach the app"


@pytest.mark.parametrize("header", ["Basic dXNlcjpwYXNz", "Bearer", "Bearer ", "bearer-token-without-scheme"])
def test_ac24_a_malformed_authorization_header_is_a_401_with_resource_metadata(header):
    with Mcp(stub_app({})) as mcp:
        response = mcp.request(
            "POST",
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={"Authorization": header, "Accept": "application/json, text/event-stream"},
        )
    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Bearer resource_metadata=")


def test_healthz_answers_without_calling_the_app():
    transport = stub_app({})
    with Mcp(transport) as mcp:
        response = mcp.request("GET", "/healthz")
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert transport.requests == []


def test_healthz_deep_calls_the_apps_healthcheck():
    transport = stub_app({"/healthcheck": json_response(200, {"status": "ok"})})
    with Mcp(transport) as mcp:
        response = mcp.request("GET", "/healthz?deep=1")
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert [r.url.path for r in transport.requests] == ["/healthcheck"]


def test_healthz_deep_is_503_when_the_app_is_down():
    transport = StubTransport(lambda request: httpx2.ConnectError("refused"))
    with Mcp(transport) as mcp:
        response = mcp.request("GET", "/healthz?deep=1")
    assert response.status_code == 503
    assert response.json()["ok"] is False


def test_the_server_holds_no_session_state(world, mcp, admin_token):
    """Stateless: no session id is issued, and a request needs nothing from an earlier one."""
    response = mcp.rpc(admin_token, "tools/list")
    assert response.status_code == 200
    assert "mcp-session-id" not in {k.lower() for k in response.headers}
    # A second, unrelated token works on its own with no handshake before it.
    other = token_for(world, "member")
    assert mcp.rpc(other, "tools/list").status_code == 200


def test_config_comes_from_the_environment_and_names_what_is_missing():
    from bize_mcp.config import Config, ConfigError

    env = {
        "BIZE_API_BASE_URL": "http://app.internal:8000/",
        "MCP_PUBLIC_URL": "https://mcp.example.test/mcp",
        "BIZE_ISSUER_URL": "https://app.example.test",
    }
    config = Config.from_env(env)
    assert config.api_base_url == "http://app.internal:8000"
    assert config.public_url == "https://mcp.example.test/mcp"
    assert config.issuer_url == "https://app.example.test"
    assert config.metadata_url == "https://mcp.example.test/.well-known/oauth-protected-resource"

    with pytest.raises(ConfigError) as err:
        Config.from_env({"BIZE_API_BASE_URL": env["BIZE_API_BASE_URL"]})
    assert "MCP_PUBLIC_URL" in str(err.value) and "BIZE_ISSUER_URL" in str(err.value)
    assert "BIZE_API_BASE_URL" not in str(err.value)


def test_config_holds_exactly_one_secret_the_rate_limit_store_password():
    """No database credentials and no app secrets. Founder decision (design review S4, 2026-11-17): its
    one secret is the shared Valkey's password, and it never shows in the config's repr."""
    from bize_mcp.config import Config

    fields = Config.__dataclass_fields__
    secretish = {name for name in fields for word in ("password", "secret", "database", "db_", "token") if word in name}
    assert secretish == {"ratelimit_password"}
    assert fields["ratelimit_password"].repr is False


@pytest.mark.parametrize("field", ["api_base_url", "public_url", "issuer_url"])
def test_config_rejects_non_http_urls(field):
    from bize_mcp.config import ConfigError

    with pytest.raises(ConfigError):
        make_config(**{field: "file:///etc/passwd"})


def test_an_sdk_client_can_list_and_call_tools(world, app_transport, admin_token):
    """The official client, over the ASGI app, with only a bearer header: initialize, list, call."""

    from mcp.client import Client
    from mcp.client.streamable_http import streamable_http_client

    from tests.mcp_server.support import ALL_TOOLS, Mcp

    async def drive(mcp: Mcp):
        http = httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=mcp.app),
            base_url="https://mcp.test",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        async with http:
            async with Client(streamable_http_client("https://mcp.test/mcp", http_client=http)) as client:
                listed = await client.list_tools()
                called = await client.call_tool(
                    "execute",
                    {"calls": [{"id": "a", "operation_id": "list_inventory", "params": {"type": "raw_material"}}]},
                )
                return listed, called

    with Mcp(app_transport) as mcp:
        # The harness already opened the app's lifespan; reuse its loop for the client.
        listed, called = mcp.run(drive(mcp))
    assert {tool.name for tool in listed.tools} == ALL_TOOLS
    assert not called.is_error
    assert "Org A Juniper" in str(called.structured_content["results"][0]["data"])


def test_the_harness_works_while_another_event_loop_is_running_on_this_thread(world, app_transport, admin_token):
    """CI runs browser tests in the same process, which leave a loop running; this once broke every test here."""

    async def inside_a_running_loop():
        with Mcp(app_transport) as mcp:
            return mcp.discover(admin_token, "inventory").is_error

    assert run_coroutine(inside_a_running_loop()) is False
