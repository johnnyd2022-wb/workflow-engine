"""Regression tests for the build review of 8.2c (``.agents/reports/public-mcp/build-review-mcp-server.md``)."""

from __future__ import annotations

import asyncio
import json
import logging

import httpx2
import pytest

from bize_mcp.config import ConfigError
from bize_mcp.knowledge import Knowledge
from bize_mcp.logging_setup import redact_value
from bize_mcp.server import _bearer
from tests.mcp_server.support import ME_ADMIN, ME_PATH, Mcp, StubTransport, json_response, make_config, stub_app

TOKEN = "bza_" + "Zq3_-" * 8 + "abc"
HOLDS = "/api/core/holds"


def one(operation_id, params=None, call_id="a", select=None):
    body = {"id": call_id, "operation_id": operation_id, "params": params or {}}
    if select:
        body["select"] = select
    return body


# F1: redaction works on values, never on the JSON text
def test_f1_data_that_mentions_bearer_neither_crashes_nor_loses_keys():
    rows = [{"id": "1", "reason": "send a Bearer token", "note": "hello world"}, {"id": "2", "reason": "bearer x"}]
    with Mcp(stub_app({HOLDS: json_response(200, {"holds": rows})})) as mcp:
        result = mcp.execute(TOKEN, one("list_open_holds"))
    assert not result.is_error, result.text
    data = result.results[0]["data"]["holds"]
    assert [r["id"] for r in data] == ["1", "2"]
    assert data[0]["note"] == "hello world", "keys after a 'bearer' mention are kept"
    assert json.loads(result.text) == result.data


def test_f1_redact_value_handles_nested_structures_and_escaped_text():
    value = {"a": [f"line\n{TOKEN}", {"k": "Bearer abc, more"}], "b": 3, "bzr_" + "x" * 43: None}
    cleaned = redact_value(value)
    assert TOKEN not in json.dumps(cleaned) and "abc" not in json.dumps(cleaned)
    assert cleaned["b"] == 3 and "more" in cleaned["a"][1]["k"]


# F2: the HTTP library must not log request URLs (query values) at all
def test_f2_no_query_value_reaches_any_log_line(caplog):
    caplog.set_level(logging.DEBUG)
    transport = stub_app({"/api/core/inventory": json_response(200, {"inventory_items": []})})
    with Mcp(transport) as mcp:
        mcp.execute(TOKEN, one("list_inventory", {"cursor": "my-secret-recipe-sentinel"}))
    assert "my-secret-recipe-sentinel" not in caplog.text
    assert "my-secret-recipe-sentinel" in str(transport.requests[-1].url), "it was sent, just never logged"


# F3: a bearer value that can't be a token is a 401, never an internal error
@pytest.mark.parametrize("value", ["tok\x00en", "ték", "a" * 600, "to ken", "tok\ten", ""])
def test_f3_a_malformed_bearer_value_is_not_a_token(value):
    assert _bearer({"authorization": f"Bearer {value}"}) is None


def test_f3_a_well_formed_bearer_value_is_accepted():
    assert _bearer({"authorization": f"Bearer {TOKEN}"}) == TOKEN
    assert _bearer({"authorization": "bearer abc.def-ghi_jkl~mno+pqr/stu=="}) == "abc.def-ghi_jkl~mno+pqr/stu=="


# F4: formats in the OpenAPI document are enforced, not only patterns
def test_f4_a_uuid_format_path_parameter_rejects_a_sibling_route_name():
    doc = {
        "paths": {
            "/api/core/lots/{lot_id}": {
                "get": {
                    "operationId": "get_lot",
                    "parameters": [
                        {
                            "name": "lot_id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string", "format": "uuid"},
                        }
                    ],
                    "x-bize": {"mcp": True, "permission": "inventory.view", "domain": "inventory"},
                }
            }
        }
    }
    base = stub_app({})

    def handler(request):
        if request.url.path == "/api/openapi.json":
            return json_response(200, doc)
        if request.url.path == ME_PATH:
            return base.handler(request)
        return json_response(200, {"ok": True})

    transport = StubTransport(handler)
    with Mcp(transport) as mcp:
        bad = mcp.execute(TOKEN, one("get_lot", {"lot_id": "export"})).results[0]
        good = mcp.execute(TOKEN, one("get_lot", {"lot_id": "3f2b8c1e-5d4a-4b6c-8e9f-0a1b2c3d4e5f"})).results[0]
    assert bad["ok"] is False and bad["error"]["kind"] == "invalid_input"
    assert good["ok"] is True
    assert [r.url.path for r in transport.requests if r.url.path.startswith("/api/core/lots")] == [
        "/api/core/lots/3f2b8c1e-5d4a-4b6c-8e9f-0a1b2c3d4e5f"
    ]


# F5: discover and docs are limited per caller too, and a long query is bounded
def test_f5_discover_is_limited_per_caller():
    with Mcp(stub_app({}, grant_per_token=True)) as mcp:
        results = [mcp.discover(TOKEN, "inventory") for _ in range(121)]
        other = mcp.discover("bza_someone_else", "inventory")
    assert not any(r.is_error for r in results[:120])
    assert results[120].is_error and results[120].data["error"]["kind"] == "rate_limited"
    assert not other.is_error


def test_f5_a_very_long_query_uses_only_its_first_words():
    from bize_mcp.knowledge import MAX_QUERY_TOKENS, query_tokens

    assert len(query_tokens("stock " * 200)) == MAX_QUERY_TOKENS


# F6: a refused execute is still audited; the budget follows the grant, not the token
def test_f6_a_rate_limited_execute_is_still_audited(caplog):
    caplog.set_level(logging.INFO, logger="bize_mcp.audit")
    with Mcp(stub_app({HOLDS: json_response(200, {"holds": []})})) as mcp:
        for _ in range(31):
            mcp.execute("bza_busy", one("list_open_holds"))
    events = [r.getMessage() for r in caplog.records if r.name == "bize_mcp.audit"]
    assert len(events) == 31
    assert "statuses=rate_limited" in events[-1] and "operations=list_open_holds" in events[-1]


def test_f6_a_new_access_token_for_the_same_grant_does_not_reset_the_execute_budget():
    with Mcp(stub_app({HOLDS: json_response(200, {"holds": []})})) as mcp:  # the stub's grant is always "grant-1"
        for i in range(30):
            assert not mcp.execute(f"bza_token_{i}", one("list_open_holds")).is_error
        assert mcp.execute("bza_token_fresh", one("list_open_holds")).is_error


# F7: a malformed schema fails its own call, not the whole batch
def test_f7_an_unusable_parameter_schema_fails_one_call_only():
    doc = {
        "paths": {
            "/api/a": {
                "get": {
                    "operationId": "broken",
                    "parameters": [{"name": "x", "in": "query", "schema": {"$ref": "#/components/schemas/Missing"}}],
                    "x-bize": {"mcp": True, "permission": "inventory.view", "domain": "inventory"},
                }
            },
            "/api/core/holds": {
                "get": {
                    "operationId": "list_open_holds",
                    "x-bize": {"mcp": True, "permission": "inventory.view", "domain": "inventory"},
                }
            },
        }
    }
    base = stub_app({HOLDS: json_response(200, {"holds": []})})

    def handler(request):
        return json_response(200, doc) if request.url.path == "/api/openapi.json" else base.handler(request)

    with Mcp(StubTransport(handler)) as mcp:
        result = mcp.execute(TOKEN, one("list_open_holds", call_id="ok"), one("broken", {"x": "1"}, call_id="bad"))
    ok, bad = result.results
    assert ok["ok"] is True and bad["ok"] is False
    assert result.data["ok"] is False


# F8: paging stays honest when rows are cut
def test_f8_rows_cut_locally_never_come_with_a_cursor_that_would_skip_them():
    rows = [{"id": str(i)} for i in range(80)]
    body = {"inventory_items": rows, "has_more": True, "next_cursor": "app-cursor"}
    with Mcp(stub_app({"/api/core/inventory": json_response(200, body)})) as mcp:
        entry = mcp.execute(TOKEN, one("list_inventory")).results[0]
    assert len(entry["data"]["inventory_items"]) == 50
    assert "next_cursor" not in entry
    assert any("No next_cursor" in n for n in entry["notes"])


def test_f8_page_size_is_clamped_like_limit():
    seen = []
    base = stub_app({})

    def handler(request):
        if request.url.path == "/api/crm/invoices":
            seen.append(dict(request.url.params.multi_items()))
            return json_response(200, {"invoices": []})
        return base.handler(request)

    with Mcp(StubTransport(handler)) as mcp:
        mcp.execute(TOKEN, one("crm_list_invoices", {"page_size": 100}))
        mcp.execute(TOKEN, one("crm_list_invoices"))
    assert [p["page_size"] for p in seen] == ["50", "50"]


# F9: nulls keep their place, so a cost can't be paired with the wrong lot
def test_f9_a_projection_keeps_null_costs_in_position():
    items = [
        {"name": "A", "unit_cost": None},
        {"name": "B", "unit_cost": "2.50"},
        {"name": "C", "unit_cost": None},
    ]
    with Mcp(stub_app({"/api/core/inventory": json_response(200, {"inventory_items": items})})) as mcp:
        result = mcp.execute(
            TOKEN,
            one("list_inventory", call_id="n", select="inventory_items[*].name"),
            one("list_inventory", call_id="c", select="inventory_items[*].unit_cost"),
        )
    assert result.results[0]["data"] == ["A", "B", "C"]
    assert result.results[1]["data"] == [None, "2.50", None]


# F10: smaller hardening
def test_f10_read_permissions_match_the_apps():
    from app.core.security.access_policy import READ_PERMISSIONS as APP
    from bize_mcp.catalogue import READ_PERMISSIONS as MCP

    assert MCP == APP, "bize_mcp keeps its own copy (it can't import app); this test is the drift alarm"


def test_f10_a_tokens_value_is_not_in_the_repr_of_what_holds_it():
    from bize_mcp.server import _RequestState
    from bize_mcp.tools.base import ToolContext

    assert TOKEN not in repr(_RequestState(TOKEN))
    assert TOKEN not in repr(ToolContext(None, TOKEN, None, None, None, None))


def test_f10_a_server_with_no_knowledge_refuses_to_start(tmp_path):
    from bize_mcp.server import create_app

    with pytest.raises(ConfigError):
        create_app(make_config(knowledge_dir=str(tmp_path)), knowledge=Knowledge.load(tmp_path))


def test_f10_two_callers_at_once_never_see_each_others_token():
    seen: dict[str, set[str]] = {}
    base = stub_app({})

    async def handle(request):
        await asyncio.sleep(0.01)
        return base.handler(request)

    class Slow(httpx2.AsyncBaseTransport):
        async def handle_async_request(self, request):
            seen.setdefault(request.headers["authorization"], set()).add(request.url.path)
            await asyncio.sleep(0.01)
            if request.url.path == HOLDS:
                return json_response(200, {"holds": [{"id": request.headers["authorization"][-4:]}]})
            return await handle(request)

    with Mcp(Slow()) as mcp:

        async def both():
            calls = [
                mcp.http.post(
                    "/mcp",
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {"name": "execute", "arguments": {"calls": [one("list_open_holds")]}},
                    },
                    headers={
                        "Authorization": f"Bearer bza_caller_{name}",
                        "Accept": "application/json, text/event-stream",
                        "Content-Type": "application/json",
                    },
                )
                for name in ("aaaa", "bbbb") * 3
            ]
            return await asyncio.gather(*calls)

        replies = mcp.run(both())
    for reply, name in zip(replies, ("aaaa", "bbbb") * 3, strict=True):
        assert reply.json()["result"]["structuredContent"]["results"][0]["data"]["holds"][0]["id"] == name
    assert set(seen) == {"Bearer bza_caller_aaaa", "Bearer bza_caller_bbbb"}
    assert ME_ADMIN
