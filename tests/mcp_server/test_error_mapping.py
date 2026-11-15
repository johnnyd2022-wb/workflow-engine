"""AC28: the app's 401, 403, 404, 429 and 5xx become the MCP answers the spec lists.

| App response                          | Tool result                              |
| 401                                   | MCP 401, so the client re-auths          |
| 403 mcp_not_allowed/insufficient_scope| tool error with a plain message          |
| 404                                   | "Not found"                              |
| 429                                   | tool error with retry-after              |
| 5xx                                   | "Biz-E had a problem"                    |

Real app responses are used wherever the app can produce them; a stand-in app produces the rest.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import httpx2
import pytest

from app.features.mcp_oauth.models import OAuthToken
from tests.mcp_oauth.support import RESOURCE
from tests.mcp_server.conftest import token_for
from tests.mcp_server.support import Mcp, StubTransport, json_response, stub_app

HOLDS = "/api/core/holds"
RESOURCE_METADATA = f'resource_metadata="{RESOURCE.rsplit("/mcp", 1)[0]}/.well-known/oauth-protected-resource"'


def call_holds(transport, token="bza_x", tool="list_open_holds", arguments=None):
    with Mcp(transport) as mcp:
        return mcp.call(token, tool, arguments)


# ----------------------------------------------------------------------------------------- 401


def test_ac28_a_revoked_token_makes_the_mcp_response_a_401(world, mcp, admin_token):
    assert mcp.call(admin_token, "list_open_holds").rows == []  # warm: the identity answer is now cached
    world.db.query(OAuthToken).filter(OAuthToken.org_id == world.org.id).update({"revoked_at": datetime.now(UTC)})
    world.db.commit()
    response = mcp.rpc(admin_token, "tools/call", {"name": "list_open_holds", "arguments": {}})
    assert response.status_code == 401
    challenge = response.headers["www-authenticate"]
    assert challenge.startswith("Bearer ")
    assert 'error="invalid_token"' in challenge
    assert RESOURCE_METADATA in challenge


def test_ac28_an_unknown_token_is_a_401_on_tools_list(mcp):
    response = mcp.rpc("bza_" + "A" * 43, "tools/list")
    assert response.status_code == 401
    assert 'error="invalid_token"' in response.headers["www-authenticate"]
    assert RESOURCE_METADATA in response.headers["www-authenticate"]


def test_ac28_a_token_that_is_not_ours_is_a_401_too(mcp):
    assert mcp.rpc("not-a-biz-e-token", "tools/list").status_code == 401


def test_ac28_an_app_401_on_a_tool_call_is_an_http_401_not_a_tool_error():
    def handler(request):
        if request.url.path == "/api/core/mcp/me":
            return json_response(200, {"user": {}, "org": {}, "permissions": ["inventory.view"]})
        return json_response(401, {"error": "invalid_token"}, {"WWW-Authenticate": 'Bearer error="invalid_token"'})

    with Mcp(StubTransport(handler)) as mcp:
        mcp.tools("bza_x")
        response = mcp.rpc("bza_x", "tools/call", {"name": "list_open_holds", "arguments": {}})
    assert response.status_code == 401
    assert RESOURCE_METADATA in response.headers["www-authenticate"]


# ----------------------------------------------------------------------------------------- 403


def test_ac28_turning_the_org_off_gives_a_plain_tool_error(world, mcp, admin_token):
    world.enable(False)
    result = mcp.call(admin_token, "list_open_holds")
    assert result.is_error
    assert "AI assistant access" in result.text
    assert "mcp_not_allowed" not in result.text and "403" not in result.text
    world.enable(True)
    assert not mcp.call(admin_token, "list_open_holds").is_error, "the same token works again once it is back on"


def test_ac28_an_unticked_role_gives_the_same_plain_error(world, mcp):
    world.enable(True, roles=("admin",))
    result = mcp.call(token_for(world, "member"), "list_open_holds")
    assert result.is_error and "AI assistant access" in result.text


def test_ac28_insufficient_scope_is_a_plain_tool_error():
    transport = stub_app({HOLDS: json_response(403, {"error": "insufficient_scope"})})
    result = call_holds(transport)
    assert result.is_error
    assert "read only" in result.text.lower()
    assert "insufficient_scope" not in result.text


def test_ac28_a_permission_403_is_a_plain_tool_error():
    transport = stub_app({HOLDS: json_response(403, {"error": "Forbidden"})})
    result = call_holds(transport)
    assert result.is_error
    assert "permission" in result.text.lower()


def test_ac28_a_role_without_the_permission_gets_a_403_tool_error_from_the_real_app(world, mcp):
    token = token_for(world, "sales")
    result = mcp.call(token, "list_batches")  # sales cannot read production; the tool is hidden but callable
    assert result.is_error
    assert "permission" in result.text.lower()


# ----------------------------------------------------------------------------------------- 404


def test_ac28_a_missing_record_is_not_found(world, mcp, admin_token):
    result = mcp.call(admin_token, "get_batch", {"execution_id": str(uuid4())})
    assert result.is_error
    assert result.text.strip() == "Not found"
    assert result.data["error"]["kind"] == "not_found"


def test_ac28_a_404_on_a_route_with_no_id_means_not_available_for_the_org():
    transport = stub_app({HOLDS: json_response(404, {"error": "Not found"})})
    result = call_holds(transport)
    assert result.is_error and "Not available for your organisation" in result.text


# ----------------------------------------------------------------------------------------- 429


def test_ac28_a_429_is_a_tool_error_with_retry_after():
    transport = stub_app({HOLDS: json_response(429, {"error": "rate_limited"}, {"Retry-After": "7"})})
    result = call_holds(transport)
    assert result.is_error
    assert "7 seconds" in result.text
    assert result.data["error"]["kind"] == "rate_limited"
    assert result.data["error"]["retry_after_seconds"] == 7


def test_ac28_a_429_without_a_usable_retry_after_still_says_to_wait():
    transport = stub_app({HOLDS: json_response(429, {"error": "rate_limited"}, {"Retry-After": "soon"})})
    result = call_holds(transport)
    assert result.is_error and "try again" in result.text.lower()
    assert result.data["error"]["retry_after_seconds"] is None


def test_ac28_the_121st_request_in_a_minute_on_one_grant_is_a_429_tool_error(world, mcp, admin_token):
    from app.features.mcp_oauth.services import rate_limit

    grant_id = _grant_id(world)
    for _ in range(120):  # the grant's whole minute is used up; the tool call is the 121st
        rate_limit.hit_bearer(grant_id)
    result = mcp.call(admin_token, "list_open_holds")
    assert result.is_error
    assert "second" in result.text.lower()
    assert result.data["error"]["kind"] == "rate_limited"
    assert result.data["error"]["retry_after_seconds"] >= 1


def _grant_id(world):
    from app.features.mcp_oauth.models import OAuthGrant

    return world.db.query(OAuthGrant).filter(OAuthGrant.org_id == world.org.id).first().id


# ----------------------------------------------------------------------------------------- 5xx etc


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_ac28_a_5xx_is_biz_e_had_a_problem_and_leaks_nothing(status):
    transport = stub_app({HOLDS: json_response(status, {"error": "Traceback: secret detail at /srv/app.py"})})
    result = call_holds(transport)
    assert result.is_error
    assert "Biz-E had a problem" in result.text
    assert "Traceback" not in result.text and "secret" not in result.text
    assert result.data["error"]["kind"] == "upstream_error"


@pytest.mark.parametrize(
    "failure", [httpx2.ConnectError("refused"), httpx2.ReadTimeout("slow"), httpx2.RemoteProtocolError("bad")]
)
def test_ac28_a_dead_or_slow_app_is_biz_e_had_a_problem(failure):
    transport = StubTransport(
        lambda request: json_response(200, {"permissions": ["inventory.view"]})
        if request.url.path == "/api/core/mcp/me"
        else failure
    )
    result = call_holds(transport)
    assert result.is_error
    assert "Biz-E" in result.text
    assert result.data["error"]["kind"] in {"upstream_error", "timeout"}


def test_a_400_passes_the_apps_own_message_through():
    transport = stub_app({"/api/compliant/records": json_response(400, {"error": "Unknown framework"})})
    result = call_holds(transport, tool="list_compliance_records")
    assert result.is_error
    assert "Unknown framework" in result.text


def test_a_redirect_is_never_followed_and_the_token_never_leaves():
    hits: list[httpx2.Request] = []

    def handler(request):
        hits.append(request)
        if request.url.path == "/api/core/mcp/me":
            return json_response(200, {"user": {}, "org": {}, "permissions": ["inventory.view"]})
        return httpx2.Response(301, headers={"Location": "https://evil.example.test/steal"})

    result = call_holds(StubTransport(handler), token="bza_secrettoken")
    assert result.is_error and "Biz-E had a problem" in result.text
    assert all(r.url.host != "evil.example.test" for r in hits)
    assert len([r for r in hits if r.url.path == HOLDS]) == 1


def test_a_200_that_is_not_json_is_biz_e_had_a_problem():
    transport = stub_app({HOLDS: httpx2.Response(200, text="<html>maintenance</html>")})
    result = call_holds(transport)
    assert result.is_error and "Biz-E had a problem" in result.text


def test_an_unknown_tool_name_is_an_error_not_a_crash(mcp, admin_token):
    response = mcp.rpc(admin_token, "tools/call", {"name": "delete_everything", "arguments": {}})
    assert response.status_code == 200
    body = response.json()
    assert "error" in body or body["result"].get("isError")


def test_unknown_arguments_are_refused(mcp, admin_token):
    result = mcp.call(admin_token, "list_open_holds", {"surprise": "x"})
    assert result.is_error
    assert not mcp.app_transport.calls_to(HOLDS)
