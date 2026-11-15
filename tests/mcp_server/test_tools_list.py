"""AC25: ``tools/list`` is filtered per caller from ``GET /api/core/mcp/me``.

An admin sees every tool; a person sees only the tools whose permission they hold. Spec: "bize_mcp
server (8.2c)" and "Tools (8.2c)".
"""

from __future__ import annotations

import pytest

from tests.mcp_server.conftest import token_for
from tests.mcp_server.support import (
    ALL_TOOLS,
    INJECTION_SUFFIX,
    ME_ADMIN,
    ME_PATH,
    Mcp,
    json_response,
    stub_app,
)

INVENTORY = {"search_inventory", "stock_position", "trace_lot", "list_open_holds"}
PRODUCTION = {"list_workflows", "get_workflow", "list_batches", "get_batch"}
COMPLIANCE = {"list_compliance_records", "excise_position", "excise_period"}
SALES = {"list_invoices", "monthly_sales"}
COSTS = {"get_cost", "stock_value"}  # margins also needs sales.view: the route checks both
MARGINS = {"margins"}


def test_ac25_admin_token_lists_every_tool(mcp, admin_token):
    assert mcp.tool_names(admin_token) == ALL_TOOLS
    assert len(ALL_TOOLS) == 16


def test_ac25_sales_token_lists_the_sales_tools_and_not_costs_or_batches(world, mcp):
    names = mcp.tool_names(token_for(world, "sales"))
    assert {"list_invoices", "monthly_sales"} <= names
    # The SALES role also holds inventory.view, so stock tools are listed: "anything else sales.view
    # covers" in the spec means the role's other read permissions.
    assert names == SALES | INVENTORY
    assert "get_cost" not in names
    assert "list_batches" not in names
    assert not names & (PRODUCTION | COMPLIANCE | COSTS | MARGINS)


@pytest.mark.parametrize(
    "role,expected",
    [
        ("production", INVENTORY | PRODUCTION | COMPLIANCE),
        ("compliance", INVENTORY | PRODUCTION | COMPLIANCE),
        ("auditor", INVENTORY | PRODUCTION | COMPLIANCE | SALES),  # no costs.view
        ("member", ALL_TOOLS),
    ],
)
def test_ac25_each_role_sees_exactly_the_tools_its_permissions_cover(world, mcp, role, expected):
    assert mcp.tool_names(token_for(world, role)) == expected


def test_margins_needs_both_costs_and_sales_view_like_the_route_does():
    only_costs = {**ME_ADMIN, "permissions": ["costs.view", "inventory.view"]}
    only_sales_costs = {**ME_ADMIN, "permissions": ["costs.view", "sales.view"]}
    with Mcp(stub_app({}, me=only_costs)) as mcp:
        assert "margins" not in mcp.tool_names("bza_x")
        assert {"get_cost", "stock_value"} <= mcp.tool_names("bza_x")
    with Mcp(stub_app({}, me=only_sales_costs)) as mcp:
        assert "margins" in mcp.tool_names("bza_x")


def test_a_person_with_no_read_permission_sees_no_tools():
    nothing = {**ME_ADMIN, "permissions": []}
    with Mcp(stub_app({}, me=nothing)) as mcp:
        assert mcp.tools("bza_x") == []


def test_every_tool_is_read_only_and_ends_with_the_prompt_injection_warning(mcp, admin_token):
    tools = mcp.tools(admin_token)
    assert len(tools) == len(ALL_TOOLS)
    for tool in tools:
        assert tool["annotations"]["readOnlyHint"] is True, tool["name"]
        assert tool["description"].rstrip().endswith(INJECTION_SUFFIX), tool["name"]
        assert tool["inputSchema"]["type"] == "object", tool["name"]
        assert tool["inputSchema"].get("additionalProperties") is False, tool["name"]


def test_tool_descriptions_are_written_for_a_model_not_copied_from_the_route(mcp, admin_token):
    for tool in mcp.tools(admin_token):
        body = tool["description"].removesuffix(INJECTION_SUFFIX).strip()
        assert len(body) >= 40, f"{tool['name']} needs a description a model can choose by"
        assert "/api/" not in body, f"{tool['name']} leaks an internal route into its description"


def test_the_identity_answer_is_cached_for_a_minute_per_token():
    transport = stub_app({})
    with Mcp(transport) as mcp:
        for _ in range(3):
            mcp.tools("bza_same")
        assert len(transport.calls_to(ME_PATH)) == 1
        mcp.tools("bza_different")
        assert len(transport.calls_to(ME_PATH)) == 2


def test_the_identity_cache_expires_after_sixty_seconds(monkeypatch):
    from bize_mcp import auth

    now = [1000.0]
    monkeypatch.setattr(auth, "_now", lambda: now[0])
    transport = stub_app({})
    with Mcp(transport) as mcp:
        mcp.tools("bza_x")
        now[0] += 59
        mcp.tools("bza_x")
        assert len(transport.calls_to(ME_PATH)) == 1
        now[0] += 2
        mcp.tools("bza_x")
        assert len(transport.calls_to(ME_PATH)) == 2


def test_a_failed_identity_lookup_is_not_cached():
    answers = [json_response(500, {"error": "boom"}), json_response(200, ME_ADMIN)]

    def handler(request):
        return answers.pop(0)

    from tests.mcp_server.support import StubTransport

    transport = StubTransport(handler)
    with Mcp(transport) as mcp:
        first = mcp.rpc("bza_x", "tools/list")
        assert first.status_code == 200 and "error" in first.json()
        assert mcp.tool_names("bza_x") == ALL_TOOLS


def test_an_org_that_turned_assistants_off_gets_a_plain_error_from_tools_list(world, mcp, admin_token):
    world.enable(False)
    response = mcp.rpc(admin_token, "tools/list")
    assert response.status_code == 200
    message = response.json()["error"]["message"]
    assert "AI assistant access" in message
    assert "mcp_not_allowed" not in message
