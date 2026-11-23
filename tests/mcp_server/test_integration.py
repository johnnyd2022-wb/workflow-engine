"""bize_mcp against the real OpenAPI document (8.2f) and the real knowledge docs (8.2g).

The unit tests use small fixtures; these prove the server works on what actually ships. They skip with
a reason when the app doesn't yet serve ``/api/openapi.json``.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from bize_mcp.catalogue import READ_PERMISSIONS, parse
from bize_mcp.knowledge import Knowledge
from tests.factories import InventoryItemFactory
from tests.mcp_server.conftest import token_for
from tests.mcp_server.support import FlaskTransport, Mcp, make_config

REPO = Path(__file__).resolve().parents[2]
KNOWLEDGE = REPO / "docs" / "knowledge"


@pytest.fixture
def real(world):
    if not any(rule.rule == "/api/openapi.json" for rule in world.app.url_map.iter_rules()):
        pytest.skip("the app does not serve /api/openapi.json yet (public MCP 8.2f)")
    with Mcp(FlaskTransport(world.app), make_config(knowledge_dir=str(KNOWLEDGE))) as harness:
        yield harness


def call(call_id, operation_id, params=None, select=None):
    body = {"id": call_id, "operation_id": operation_id, "params": params or {}}
    if select:
        body["select"] = select
    return body


def real_document(world, token) -> dict:
    response = world.anon().get("/api/openapi.json?audience=mcp", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200, response.get_data(as_text=True)[:300]
    return response.get_json()


def test_every_mcp_operation_in_the_real_document_parses_into_a_usable_contract(world, real, admin_token):
    operations = parse(real_document(world, admin_token))
    assert len(operations) >= 25
    for op in operations.values():
        assert op.method == "GET", op.operation_id
        assert op.summary, f"{op.operation_id} needs a summary"
        assert op.permissions and set(op.permissions) <= READ_PERMISSIONS, op.operation_id
        jsonschema.Draft202012Validator.check_schema(op.param_schema())
        for param in op.params:
            assert "$ref" not in json.dumps(param.schema), f"{op.operation_id}.{param.name} has an unresolved $ref"
        if op.response_schema is not None:
            assert "$ref" not in json.dumps(op.response_schema), f"{op.operation_id} response has an unresolved $ref"


def test_the_real_knowledge_docs_load_and_point_at_real_operations(world, real, admin_token):
    knowledge = Knowledge.load(KNOWLEDGE)
    assert len(knowledge.topics) >= 25 and knowledge.overview
    known = set(parse(real_document(world, admin_token)))
    missing = {
        (topic.topic, operation)
        for topic in knowledge.topics.values()
        for operation in topic.related_operations
        if operation not in known
    }
    # Compliance and costing operations are only in the document for an org that has those features.
    assert {m for m in missing if not m[1].startswith(("compliant_", "costing_", "planning_"))} == set()


def test_discover_finds_the_availability_topic_and_the_inventory_list_operation(real, admin_token):
    result = real.discover(admin_token, "orris root stock available")
    assert not result.is_error, result.text
    assert "inventory.availability" in {c["topic"] for c in result.data["concepts"]}
    assert "core_list_inventory" in {o["operation_id"] for o in result.data["operations"]}


def test_a_sales_token_is_offered_no_cost_or_production_operations(world, real):
    token = token_for(world, "sales")
    found = {
        o["operation_id"]
        for o in real.discover(token, "cost batch workflow stock invoice lot", limit=20).data["operations"]
    }
    assert "crm_crm_api_get_org_invoices" in found and "core_list_inventory" in found
    assert not found & {"costing_get_lot_cost", "core_list_executions", "core_list_processes"}
    assert real.docs(token, operation_id="costing_get_lot_cost").is_error


def test_docs_for_an_operation_has_a_fully_resolved_schema_and_an_example(real, admin_token):
    data = real.docs(admin_token, operation_id="core_list_inventory", include_response_schema=True).data
    assert {p["name"] for p in data["parameters"]} >= {"type", "site_id", "limit", "cursor"}
    assert "$ref" not in json.dumps(data["response_schema"])
    assert data["example"] and "inventory_items" in data["example"]
    assert data["related_operations"]


def test_execute_chains_list_then_trace_with_a_reference(world, real, admin_token):
    result = real.execute(
        admin_token,
        call("find", "core_list_inventory", {"type": "raw_material"}),
        call(
            "trace",
            "core_trace_inventory_backward",
            {"inventory_item_id": {"$from": "find", "path": "inventory_items[0].id"}},
        ),
    )
    assert not result.is_error, result.text
    assert result.results[1]["data"]["traced_item"]["id"] == str(world.item.id)


def test_120_lots_come_back_as_50_50_20(world, real, admin_token):
    for i in range(120):
        InventoryItemFactory(org_id=world.org.id, name=f"Paging Lot {i:03d}", inventory_type="final_product")
    world.db.commit()
    sizes, cursor = [], None
    for _ in range(4):
        params = {"type": "final_product", **({"cursor": cursor} if cursor else {})}
        entry = real.execute(admin_token, call("a", "core_list_inventory", params)).results[0]
        assert entry["ok"], entry
        sizes.append(len(entry["data"]["inventory_items"]))
        cursor = entry.get("next_cursor")
        if not cursor:
            break
    assert sizes == [50, 50, 20]


def test_a_lot_with_no_cost_is_null_with_a_status_never_zero(world, real, admin_token):
    from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository

    FeatureSubscriptionRepository(world.db).grant(world.org.id, "costing")
    world.db.commit()
    entry = real.execute(admin_token, call("c", "costing_get_lot_cost", {"item_id": str(world.item.id)})).results[0]
    assert entry["ok"], entry
    assert entry["data"]["unit_cost"] is None and entry["data"]["status"] != "actual"


def test_the_crm_operations_follow_the_orgs_feature(world, real, admin_token):
    entry = real.execute(admin_token, call("i", "crm_crm_api_get_org_invoices", {"kind": "all"})).results[0]
    assert entry["ok"], entry


def test_ac27_docs_topic_returns_the_real_markdown_with_its_frontmatter_fields(real, admin_token):
    data = real.docs(admin_token, topic="inventory.availability").data
    assert data["topic"] == "inventory.availability" and data["domain"] == "inventory"
    assert data["markdown"].startswith("---\ntopic:")
    assert "core_list_inventory" in data["related_operations"]
    assert "inventory.holds" in data["related_topics"]


def test_every_real_topic_can_be_read_through_docs(real, admin_token):
    knowledge = Knowledge.load(KNOWLEDGE)
    for name, topic in knowledge.topics.items():
        if topic.features:  # feature-gated topics are tested through their feature
            continue
        assert not real.docs(admin_token, topic=name).is_error, name
