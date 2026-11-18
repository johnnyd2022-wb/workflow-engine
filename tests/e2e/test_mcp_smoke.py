"""Public MCP 8.2d (AC32): the deployed MCP server answers, and reaches the deployed app.

cd_e2e runs this against the container scripts/run_mcp.sh just started (``E2E_MCP_URL``, by its
name on the app's Docker network), with a token minted straight into the shared test database for a
throwaway person, the same way tests/mcp_oauth does. Nothing here needs the MCP SDK or a browser: it
speaks the protocol's plain HTTP + JSON-RPC, as an assistant's connector does.

Without ``E2E_MCP_URL`` there is no server to ask, so these skip with that reason (the suite's rule:
an absent dependency is a skip, never a failure).
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit
from uuid import UUID

import pytest
import requests

pytestmark = pytest.mark.e2e

METADATA_PATH = "/.well-known/oauth-protected-resource"
MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def mcp_url() -> str:
    url = os.environ.get("E2E_MCP_URL", "").strip()
    if not url:
        pytest.skip("E2E_MCP_URL is not set: point it at a deployed bize_mcp server (cd_e2e does)")
    return url.rstrip("/")


def _rpc(mcp_url: str, method: str, params: dict | None = None, token: str | None = None) -> requests.Response:
    headers = dict(MCP_HEADERS)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    return requests.post(f"{mcp_url}/mcp", json=body, headers=headers, timeout=30)


def _expected_resource() -> str:
    """The address the app binds tokens to: its own [mcp] resource for the environment under test.

    cd_e2e runs with ENVIRONMENT=test, so this is test.ini's. A local run against a container started
    with another environment's addresses sets E2E_MCP_RESOURCE and E2E_MCP_ISSUER to match them."""
    from app.utils.config_loader import config

    return os.environ.get("E2E_MCP_RESOURCE") or config.mcp_resource


def _expected_issuer() -> str:
    from app.utils.config_loader import config

    return os.environ.get("E2E_MCP_ISSUER") or config.mcp_issuer


@pytest.fixture()
def connected(mcp_url, fresh_user, db):
    """A raw read token for a person whose organisation has the MCP switch on, as an assistant would hold it."""
    from app.core.db.models.user import User, UserRole
    from app.features.mcp_oauth.models import McpAllowedRole, McpOrgSettings, OAuthClient, OAuthGrant, OAuthToken
    from tests.mcp_oauth.support import make_client, mint_grant

    person = fresh_user(UserRole.MEMBER)
    org_id, user_id = UUID(person["org_id"]), UUID(person["user_id"])
    # The token's audience is the resource the *deployed* server advertises, so a mismatch between the
    # server's configuration and the app's shows up as the 401 the test below asserts against.
    resource = requests.get(f"{mcp_url}{METADATA_PATH}", timeout=10).json()["resource"]
    db.add(McpOrgSettings(org_id=org_id, enabled=True))
    db.add(McpAllowedRole(org_id=org_id, role_key=f"builtin:{UserRole.MEMBER.value}"))
    db.commit()
    client = make_client(db, name="MCPTEST e2e smoke")
    grant, access, _refresh = mint_grant(db, db.get(User, user_id), client, resource=resource)
    yield access
    db.rollback()
    # The client row is global; its grant and tokens go first. The org's own rows go with fresh_user.
    db.query(OAuthToken).filter(OAuthToken.grant_id == grant.id).delete(synchronize_session=False)
    db.query(OAuthGrant).filter(OAuthGrant.id == grant.id).delete(synchronize_session=False)
    db.query(OAuthClient).filter(OAuthClient.id == client.id).delete(synchronize_session=False)
    db.commit()


def test_protected_resource_metadata_names_the_apps_resource_and_issuer(mcp_url):
    response = requests.get(f"{mcp_url}{METADATA_PATH}", timeout=10)
    assert response.status_code == 200
    body = response.json()
    assert body["resource"] == _expected_resource()
    assert body["authorization_servers"] == [_expected_issuer()]
    assert body["scopes_supported"] == ["bize.read"]
    assert body["bearer_methods_supported"] == ["header"]


def test_an_unauthenticated_mcp_request_is_401_and_points_at_the_metadata(mcp_url):
    response = _rpc(mcp_url, "tools/list")
    assert response.status_code == 401
    resource = urlsplit(_expected_resource())
    origin = f"{resource.scheme}://{resource.netloc}"
    assert response.headers["WWW-Authenticate"] == f'Bearer resource_metadata="{origin}{METADATA_PATH}"'


def test_a_minted_token_lists_the_three_tools(mcp_url, connected):
    response = _rpc(mcp_url, "tools/list", token=connected)
    assert response.status_code == 200, response.text
    body = response.json()
    assert "result" in body, body
    names = {tool["name"] for tool in body["result"]["tools"]}
    assert {"discover", "docs", "execute"} <= names


def test_a_tool_call_reaches_the_app_with_the_callers_token(mcp_url, connected):
    """The step a deploy mistake breaks quietly: the server up, but its call to the app refused."""
    response = _rpc(mcp_url, "tools/call", {"name": "discover", "arguments": {"query": ""}}, token=connected)
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert not result.get("isError"), result
    assert result["content"], "an empty query returns the domain overview"


def test_the_server_is_healthy_and_can_reach_the_app(mcp_url):
    response = requests.get(f"{mcp_url}/healthz", params={"deep": "1"}, timeout=10)
    assert response.status_code == 200, response.text
    assert response.json() == {"ok": True, "app": "ok"}
