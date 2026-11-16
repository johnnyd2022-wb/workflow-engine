"""AC28: the app's 401, 403, 404, 429 and 5xx become the MCP answers the spec lists.

| App response                          | Result                                         |
| 401                                   | MCP 401, so the client re-auths                |
| 403 mcp_not_allowed/insufficient_scope| tool error with a plain message                |
| 404                                   | "Not found"                                    |
| 429                                   | tool error with retry-after                    |
| 5xx                                   | "Biz-E had a problem"                          |

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
from tests.mcp_server.support import ME_ADMIN, ME_PATH, Mcp, StubTransport, json_response, stub_app

HOLDS = "/api/core/holds"
RESOURCE_METADATA = f'resource_metadata="{RESOURCE.rsplit("/mcp", 1)[0]}/.well-known/oauth-protected-resource"'


def run_holds(transport, token="bza_x", operation="list_open_holds", params=None):
    with Mcp(transport) as mcp:
        result = mcp.execute(token, {"id": "a", "operation_id": operation, "params": params or {}})
    return result, result.results[0]


# ----------------------------------------------------------------------------------------- 401


def test_ac28_a_revoked_token_makes_the_mcp_response_a_401(world, mcp, admin_token):
    assert mcp.execute(admin_token, {"id": "a", "operation_id": "list_open_holds"}).results[0]["ok"]
    world.db.query(OAuthToken).filter(OAuthToken.org_id == world.org.id).update({"revoked_at": datetime.now(UTC)})
    world.db.commit()
    response = mcp.rpc(
        admin_token,
        "tools/call",
        {"name": "execute", "arguments": {"calls": [{"id": "a", "operation_id": "list_open_holds"}]}},
    )
    assert response.status_code == 401
    challenge = response.headers["www-authenticate"]
    assert 'error="invalid_token"' in challenge and RESOURCE_METADATA in challenge


@pytest.mark.parametrize("token", ["bza_" + "A" * 43, "not-a-biz-e-token"])
def test_ac28_an_unknown_token_is_a_401_on_tools_list_and_on_a_call(mcp, token):
    for response in (
        mcp.rpc(token, "tools/list"),
        mcp.rpc(token, "tools/call", {"name": "discover", "arguments": {"query": "x"}}),
    ):
        assert response.status_code == 401
        assert 'error="invalid_token"' in response.headers["www-authenticate"]
        assert RESOURCE_METADATA in response.headers["www-authenticate"]


def test_ac28_an_app_401_on_a_call_is_an_http_401_not_a_tool_error():
    def handler(request):
        if request.url.path in {ME_PATH, "/api/openapi.json"}:
            return stub_app({}).handler(request)
        return json_response(401, {"error": "invalid_token"})

    with Mcp(StubTransport(handler)) as mcp:
        assert mcp.tools("bza_x")
        response = mcp.rpc(
            "bza_x",
            "tools/call",
            {"name": "execute", "arguments": {"calls": [{"id": "a", "operation_id": "list_open_holds"}]}},
        )
    assert response.status_code == 401
    assert RESOURCE_METADATA in response.headers["www-authenticate"]


# ----------------------------------------------------------------------------------------- 403


def test_ac28_turning_the_org_off_gives_a_plain_error(world, mcp, admin_token):
    world.enable(False)
    for result in (
        mcp.execute(admin_token, {"id": "a", "operation_id": "list_open_holds"}),
        mcp.discover(admin_token, "x"),
    ):
        assert result.is_error
        assert "AI assistant access" in result.text
        assert "mcp_not_allowed" not in result.text and "403" not in result.text
    world.enable(True)
    assert mcp.execute(admin_token, {"id": "a", "operation_id": "list_open_holds"}).results[0]["ok"], (
        "same token works again"
    )


def test_ac28_an_unticked_role_gives_the_same_plain_error(world, mcp):
    world.enable(True, roles=("admin",))
    assert "AI assistant access" in mcp.discover(token_for(world, "member"), "x").text


def test_ac28_insufficient_scope_is_a_plain_error():
    _, entry = run_holds(stub_app({HOLDS: json_response(403, {"error": "insufficient_scope"})}))
    assert entry["error"]["kind"] == "read_only" and "read only" in entry["error"]["message"]
    assert "insufficient_scope" not in entry["error"]["message"]


def test_ac28_a_permission_403_is_a_plain_error():
    _, entry = run_holds(stub_app({HOLDS: json_response(403, {"error": "Forbidden"})}))
    assert entry["error"]["kind"] == "forbidden" and "permission" in entry["error"]["message"]


def test_ac28_the_real_app_refuses_a_role_the_catalogue_did_not_hide(world, mcp):
    """If the catalogue ever offered more than the role holds, the app's own 403 still stops it."""
    token = token_for(world, "sales")
    me = {**ME_ADMIN, "permissions": ["production.view", "inventory.view"]}  # the server is told too much
    from tests.mcp_server.support import CatalogueTransport, FlaskTransport

    class Lying(CatalogueTransport):
        async def handle_async_request(self, request):
            if request.url.path == ME_PATH:
                return httpx2.Response(200, json=me, request=request)
            return await super().handle_async_request(request)

    with Mcp(Lying(FlaskTransport(world.app))) as lying:
        entry = lying.execute(token, {"id": "a", "operation_id": "list_executions"}).results[0]
    assert entry["ok"] is False and entry["error"]["kind"] == "forbidden"


# ----------------------------------------------------------------------------------------- 404


def test_ac28_a_missing_record_is_not_found(world, mcp, admin_token):
    entry = mcp.execute(
        admin_token, {"id": "a", "operation_id": "get_execution", "params": {"execution_id": str(uuid4())}}
    ).results[0]
    assert entry["error"] == {"kind": "not_found", "message": "Not found"}


def test_ac28_a_404_on_an_operation_with_no_id_means_not_available_for_the_org():
    _, entry = run_holds(stub_app({HOLDS: json_response(404, {"error": "Not found"})}))
    assert (
        entry["error"]["kind"] == "not_available" and "Not available for your organisation" in entry["error"]["message"]
    )


# ----------------------------------------------------------------------------------------- 429


def test_ac28_a_429_is_a_tool_error_with_retry_after():
    result, entry = run_holds(stub_app({HOLDS: json_response(429, {"error": "rate_limited"}, {"Retry-After": "7"})}))
    assert result.is_error
    assert entry["error"]["kind"] == "rate_limited" and entry["error"]["retry_after_seconds"] == 7
    assert "7 seconds" in entry["error"]["message"]


def test_ac28_a_429_without_a_usable_retry_after_still_says_to_wait():
    _, entry = run_holds(stub_app({HOLDS: json_response(429, {"error": "rate_limited"}, {"Retry-After": "soon"})}))
    assert entry["error"]["retry_after_seconds"] is None and "try again" in entry["error"]["message"].lower()


def test_ac28_the_121st_request_in_a_minute_on_one_grant_is_a_429_tool_error(world, mcp, admin_token):
    from app.features.mcp_oauth.models import OAuthGrant
    from app.features.mcp_oauth.services import rate_limit

    grant_id = world.db.query(OAuthGrant).filter(OAuthGrant.org_id == world.org.id).first().id
    for _ in range(119):  # the identity lookup makes the 120th request; the holds call is the 121st
        rate_limit.hit_bearer(grant_id)
    entry = mcp.execute(admin_token, {"id": "a", "operation_id": "list_open_holds"}).results[0]
    assert entry["ok"] is False and entry["error"]["kind"] == "rate_limited"
    assert entry["error"]["retry_after_seconds"] >= 1


def test_more_than_30_execute_calls_a_minute_for_one_caller_are_limited():
    from bize_mcp.tools import execute

    execute._windows = execute._Window(30, 60.0)
    transport = stub_app({HOLDS: json_response(200, {"holds": []})})
    with Mcp(transport) as mcp:
        results = [mcp.execute("bza_busy", {"id": "a", "operation_id": "list_open_holds"}) for _ in range(31)]
        other = mcp.execute("bza_calm", {"id": "a", "operation_id": "list_open_holds"})
    assert not any(r.is_error for r in results[:30])
    assert results[30].is_error and results[30].data["error"]["kind"] == "rate_limited"
    assert results[30].data["error"]["retry_after_seconds"] >= 1
    assert not other.is_error, "one caller's limit is not another's"


# ----------------------------------------------------------------------------------------- 5xx etc


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_ac28_a_5xx_is_biz_e_had_a_problem_and_leaks_nothing(status):
    _, entry = run_holds(stub_app({HOLDS: json_response(status, {"error": "Traceback: secret detail at /srv/app.py"})}))
    assert "Biz-E had a problem" in entry["error"]["message"] and entry["error"]["kind"] == "upstream_error"
    assert "Traceback" not in str(entry) and "secret" not in str(entry)


@pytest.mark.parametrize(
    "failure", [httpx2.ConnectError("refused"), httpx2.ReadTimeout("slow"), httpx2.RemoteProtocolError("bad")]
)
def test_ac28_a_dead_or_slow_app_is_biz_e_had_a_problem(failure):
    base = stub_app({})

    def handler(request):
        return base.handler(request) if request.url.path in {ME_PATH, "/api/openapi.json"} else failure

    _, entry = run_holds(StubTransport(handler))
    assert "Biz-E" in entry["error"]["message"]
    assert entry["error"]["kind"] in {"upstream_error", "timeout"}


def test_a_400_passes_the_apps_own_message_through():
    _, entry = run_holds(stub_app({HOLDS: json_response(400, {"error": "Unknown framework"})}))
    assert entry["error"]["kind"] == "bad_request" and "Unknown framework" in entry["error"]["message"]


def test_a_redirect_is_never_followed_and_the_token_never_leaves():
    hits: list[httpx2.Request] = []
    base = stub_app({})

    def handler(request):
        hits.append(request)
        if request.url.path in {ME_PATH, "/api/openapi.json"}:
            return base.handler(request)
        return httpx2.Response(301, headers={"Location": "https://evil.example.test/steal"})

    _, entry = run_holds(StubTransport(handler), token="bza_secrettoken")
    assert "Biz-E had a problem" in entry["error"]["message"]
    assert all(r.url.host != "evil.example.test" for r in hits)
    assert len([r for r in hits if r.url.path == HOLDS]) == 1


def test_a_200_that_is_not_json_is_biz_e_had_a_problem():
    _, entry = run_holds(stub_app({HOLDS: httpx2.Response(200, text="<html>maintenance</html>")}))
    assert "Biz-E had a problem" in entry["error"]["message"]


def test_a_call_that_takes_too_long_times_out_without_stopping_the_others(monkeypatch):
    import asyncio

    from bize_mcp.tools import execute

    monkeypatch.setattr(execute, "CALL_SECONDS", 0.2)

    async def slow(request):
        await asyncio.sleep(2)

    class Slow(httpx2.AsyncBaseTransport):
        async def handle_async_request(self, request):
            if request.url.path == HOLDS:
                await asyncio.sleep(2)
            return stub_app({"/api/core/processes": json_response(200, {"processes": []})}).handler(request)

    with Mcp(Slow()) as mcp:
        result = mcp.execute(
            "bza_x", {"id": "a", "operation_id": "list_open_holds"}, {"id": "b", "operation_id": "list_processes"}
        )
    a, b = result.results
    assert a["error"]["kind"] == "timeout" and b["ok"]


def test_an_unknown_tool_name_is_an_error_not_a_crash(mcp, admin_token):
    response = mcp.rpc(admin_token, "tools/call", {"name": "delete_everything", "arguments": {}})
    assert response.status_code == 200 and "error" in response.json()


def test_unknown_arguments_to_a_tool_are_refused(mcp, admin_token):
    result = mcp.call(admin_token, "discover", {"surprise": "x"})
    assert result.is_error and "surprise" in result.text
