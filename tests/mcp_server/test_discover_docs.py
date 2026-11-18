"""AC25 (discover, filtered per caller) and the ``docs`` half of AC27.

The catalogue here is the fixture OpenAPI document in ``fixtures/`` and the fixture knowledge files,
in the exact formats the spec gives. The integration test against the real document is in
``test_integration.py``.
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


def ops(result) -> set[str]:
    return {row["operation_id"] for row in result.data["operations"]}


def topics(result) -> set[str]:
    return {row["topic"] for row in result.data["concepts"]}


def test_exactly_three_tools_are_listed_and_all_are_read_only(mcp, admin_token):
    tools = mcp.tools(admin_token)
    assert {t["name"] for t in tools} == ALL_TOOLS
    for tool in tools:
        assert tool["annotations"]["readOnlyHint"] is True, tool["name"]
        assert tool["description"].rstrip().endswith(INJECTION_SUFFIX), tool["name"]
        assert tool["inputSchema"]["type"] == "object"
        assert tool["inputSchema"].get("additionalProperties") is False


def test_ac25_discover_finds_the_availability_topic_and_the_inventory_list_operation(mcp, admin_token):
    result = mcp.discover(admin_token, "orris root stock available")
    assert not result.is_error, result.text
    assert "inventory.availability" in topics(result)
    assert "list_inventory" in ops(result)
    row = next(r for r in result.data["operations"] if r["operation_id"] == "list_inventory")
    assert row["permission"] == "inventory.view" and row["domain"] == "inventory"
    assert row["kind"] == "list" and row["required_params"] == []


def test_ac25_a_sales_token_is_offered_no_costs_or_production_operations(world, mcp):
    token = token_for(world, "sales")
    everything = mcp.discover(token, "cost batch lot stock invoice workflow", limit=20)
    found = ops(everything)
    assert "crm_list_invoices" in found and "list_inventory" in found
    assert not found & {"get_lot_cost", "list_executions", "get_execution", "list_processes", "get_process"}
    assert "costing.status" not in topics(everything)  # this org has no costing feature
    # The docs for a hidden operation are "not found", not "forbidden".
    hidden = mcp.docs(token, operation_id="get_lot_cost")
    assert hidden.is_error and hidden.text.strip() == "Not found"


def test_ac25_with_crm_off_no_crm_operations_or_topics_appear():
    no_crm = {**ME_ADMIN, "features": ["costing"]}
    with Mcp(stub_app({}, me=no_crm)) as mcp:
        result = mcp.discover("bza_x", "invoices sales customers", limit=20)
        assert not any(o.startswith("crm_") for o in ops(result))
        assert "sales.invoices" not in topics(result)
        assert mcp.docs("bza_x", operation_id="crm_list_invoices").is_error
        assert mcp.docs("bza_x", topic="sales.invoices").is_error
    with Mcp(stub_app({}, me=ME_ADMIN)) as mcp:
        assert "crm_list_invoices" in ops(mcp.discover("bza_x", "invoices", limit=20))


def test_operations_that_are_not_get_not_marked_mcp_or_not_a_read_permission_are_never_listed(mcp, admin_token):
    result = mcp.discover(admin_token, "add create inventory lot users people suppliers", limit=20)
    found = ops(result)
    assert "create_inventory_item" not in found  # a POST, although marked mcp
    assert "list_org_users" not in found  # users.manage is not a read permission, although marked mcp
    assert "list_core_suppliers" not in found  # not marked mcp
    for hidden in ("create_inventory_item", "list_org_users", "list_core_suppliers"):
        assert mcp.docs(admin_token, operation_id=hidden).is_error


def test_discover_with_no_query_returns_the_overview_and_the_topic_list(mcp, admin_token):
    result = mcp.discover(admin_token, "")
    assert not result.is_error
    assert "Physical quantity is not the same as usable stock" in result.data["overview"]
    assert "inventory.availability" in {t["topic"] for t in result.data["topics"]}
    assert result.data["operation_domains"]["inventory"] >= 2
    assert len(result.data["overview"].split()) < 400


def test_discover_filters_by_kind_domain_and_limit(mcp, admin_token):
    only_ops = mcp.discover(admin_token, "inventory stock", kind="operations")
    assert only_ops.data["concepts"] == [] and only_ops.data["operations"]
    only_topics = mcp.discover(admin_token, "inventory stock", kind="concepts")
    assert only_topics.data["operations"] == [] and only_topics.data["concepts"]
    production = mcp.discover(admin_token, "list", domain="production", limit=20)
    assert production.data["operations"] and {r["domain"] for r in production.data["operations"]} == {"production"}
    assert len(mcp.discover(admin_token, "list", limit=2).data["operations"]) <= 2
    assert mcp.discover(admin_token, "list", limit=21).is_error
    assert mcp.discover(admin_token, "list", kind="everything").is_error


def test_discover_says_when_nothing_matched(mcp, admin_token):
    result = mcp.discover(admin_token, "zzzxqj")
    assert not result.is_error
    assert result.data["concepts"] == [] and result.data["operations"] == []
    assert "Nothing matched" in result.data["message"]


# ---------------------------------------------------------------------------------------------- docs


def test_ac27_docs_topic_returns_the_markdown_and_its_frontmatter_fields(mcp, admin_token):
    result = mcp.docs(admin_token, topic="inventory.availability")
    assert not result.is_error, result.text
    data = result.data
    assert data["topic"] == "inventory.availability"
    assert data["title"] == "Inventory availability"
    assert data["domain"] == "inventory"
    assert "Never assume that all physically present stock is usable." in data["markdown"]
    assert data["markdown"].startswith("---\ntopic: inventory.availability")
    assert data["related_topics"] == ["production.batches", "traceability.back"]
    assert data["related_operations"] == ["list_inventory", "get_stock_position"]


def test_ac27_docs_operation_returns_its_schema_and_related_operations(mcp, admin_token):
    result = mcp.docs(admin_token, operation_id="list_inventory")
    assert not result.is_error, result.text
    data = result.data
    assert data["operation_id"] == "list_inventory" and data["method"] == "GET"
    names = {p["name"]: p for p in data["parameters"]}
    assert {"type", "site_id", "limit", "cursor"} == set(names)
    assert names["type"]["schema"]["enum"] == ["raw_material", "work_in_progress", "final_product"]
    assert names["limit"]["schema"]["maximum"] == 50
    assert data["response_schema"]["type"] == "object"
    assert data["concepts"] == ["inventory.availability"]
    assert data["concept_topics"] == ["inventory.availability"]
    assert data["related_operations"] == ["get_stock_position", "trace_inventory_backward"]
    assert data["example"] == {"params": {"type": "raw_material", "limit": 10}}
    assert "path" not in data, "the model works with operation ids, never routes"


def test_docs_related_operations_leave_out_ones_the_caller_cannot_run(world, mcp):
    token = token_for(world, "sales")  # inventory.view and sales.view only: no production
    related = mcp.docs(token, topic="production.batches")
    assert related.data["related_operations"] == []
    assert "related_operations: []" in related.data["markdown"]
    assert "list_executions" not in related.data["markdown"] and "get_execution" not in related.data["markdown"]


def test_topic_markdown_omits_operation_ids_missing_from_the_live_catalogue(mcp, admin_token):
    data = mcp.docs(admin_token, topic="production.batches").data
    assert data["related_operations"] == ["list_executions", "get_execution"]
    assert "related_operations: [list_executions, get_execution]" in data["markdown"]
    assert "`list_executions`" in data["markdown"] and "`get_execution`" in data["markdown"]
    assert "get_batch_notes" not in data["markdown"]


def test_docs_needs_exactly_one_of_topic_or_operation_id(mcp, admin_token):
    assert mcp.docs(admin_token).is_error
    assert mcp.docs(admin_token, topic="inventory.availability", operation_id="list_inventory").is_error
    assert mcp.docs(admin_token, topic="no.such.topic").text.strip() == "Not found"
    assert mcp.docs(admin_token, operation_id="no_such_operation").text.strip() == "Not found"


def test_the_catalogue_is_fetched_with_the_callers_own_token_and_cached_for_five_minutes(monkeypatch):
    from bize_mcp import auth

    now = [5000.0]
    monkeypatch.setattr(auth, "_now", lambda: now[0])
    transport = stub_app({})
    with Mcp(transport) as mcp:
        mcp.discover("bza_one", "inventory")
        mcp.docs("bza_one", operation_id="list_inventory")
        catalogue_calls = transport.calls_to("/api/openapi.json")
        assert len(catalogue_calls) == 1
        assert catalogue_calls[0].headers["authorization"] == "Bearer bza_one"
        assert dict(catalogue_calls[0].url.params.multi_items()) == {"audience": "mcp"}
        now[0] += 299
        mcp.discover("bza_one", "inventory")
        assert len(transport.calls_to("/api/openapi.json")) == 1
        now[0] += 5
        mcp.discover("bza_one", "inventory")
        assert len(transport.calls_to("/api/openapi.json")) == 2


def test_the_identity_answer_is_cached_for_a_minute_per_token(monkeypatch):
    from bize_mcp import auth

    now = [1000.0]
    monkeypatch.setattr(auth, "_now", lambda: now[0])
    transport = stub_app({})
    with Mcp(transport) as mcp:
        for _ in range(3):
            mcp.discover("bza_same", "inventory")
        assert len(transport.calls_to(ME_PATH)) == 1
        mcp.discover("bza_other", "inventory")
        assert len(transport.calls_to(ME_PATH)) == 2
        now[0] += 61
        mcp.discover("bza_same", "inventory")
        assert len(transport.calls_to(ME_PATH)) == 3


def test_a_failed_identity_lookup_is_not_cached():
    from tests.mcp_server.support import StubTransport

    answers = [json_response(500, {"error": "boom"}), json_response(200, ME_ADMIN)]
    transport = StubTransport(lambda request: answers.pop(0))
    with Mcp(transport) as mcp:
        first = mcp.rpc("bza_x", "tools/list")
        assert first.status_code == 200 and "error" in first.json()
        assert {t["name"] for t in mcp.tools("bza_x")} == ALL_TOOLS


def test_an_org_that_turned_assistants_off_gets_a_plain_error_from_tools_list(world, mcp, admin_token):
    world.enable(False)
    message = mcp.rpc(admin_token, "tools/list").json()["error"]["message"]
    assert "AI assistant access" in message and "mcp_not_allowed" not in message


@pytest.mark.parametrize("who", ["admin", "member", "production", "compliance", "sales", "auditor"])
def test_every_role_can_discover_something_and_never_sees_what_it_cannot_run(world, mcp, who):
    token = token_for(world, who)
    result = mcp.discover(token, "list", limit=20)
    assert not result.is_error
    permissions = mcp.discover(token, "")  # overview works for everyone
    assert permissions.data["overview"]
