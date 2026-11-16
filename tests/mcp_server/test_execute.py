"""AC26 and AC27: ``execute`` composes allowlisted read operations against the real app.

Every test runs the whole chain: the ASGI app, a real bearer token, the real Flask app and its access
policy. The operations come from the fixture OpenAPI document (``fixtures/openapi.json``).
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from tests.factories import ExecutionFactory, InventoryItemFactory, ProcessFactory
from tests.mcp_server.conftest import token_for
from tests.mcp_server.support import ME_ADMIN, ME_PATH, Mcp, json_response, stub_app


def call(call_id: str, operation_id: str, params: dict | None = None, select: str | None = None) -> dict:
    body = {"id": call_id, "operation_id": operation_id, "params": params or {}}
    if select:
        body["select"] = select
    return body


def seed_lots(world, count: int, *, prefix: str = "Paging Lot", inventory_type: str = "final_product") -> list:
    items = [
        InventoryItemFactory(
            org_id=world.org.id, name=f"{prefix} {i:03d}", inventory_type=inventory_type, quantity="5", unit="bottle"
        )
        for i in range(count)
    ]
    world.db.commit()
    return items


def session_json(world, who: str, path: str):
    response = world.session(who).get(path)
    assert response.status_code == 200, (path, response.status_code)
    return response.get_json()


def test_ac26_two_calls_where_the_second_takes_an_id_from_the_first(world, mcp, admin_token):
    result = mcp.execute(
        admin_token,
        call("find", "list_inventory", {"q": "Juniper"}),
        call("trace", "trace_inventory_backward", {"inventory_item_id": {"$from": "find", "path": "inventory_items[0].id"}}),
    )
    assert not result.is_error, result.text
    assert [r["id"] for r in result.results] == ["find", "trace"]
    assert all(r["ok"] for r in result.results)
    assert result.results[0]["data"]["inventory_items"][0]["name"] == "Org A Juniper"
    assert result.results[1]["data"]["traced_item"]["id"] == str(world.item.id)
    assert result.data["ok"] is True


def test_ac26_the_referenced_call_may_be_projected_down_and_the_reference_still_works(world, mcp, admin_token):
    result = mcp.execute(
        admin_token,
        call("find", "list_inventory", {"q": "Juniper"}, select="inventory_items[*].name"),
        call("trace", "trace_inventory_backward", {"inventory_item_id": {"$from": "find", "path": "inventory_items[0].id"}}),
    )
    assert result.results[0]["data"] == ["Org A Juniper"]
    assert result.results[1]["ok"], "references read the full result, not the trimmed one"


def test_ac26_a_sixth_call_is_refused(mcp, admin_token):
    calls = [call(f"c{i}", "list_open_holds") for i in range(6)]
    result = mcp.execute(admin_token, *calls)
    assert result.is_error
    assert not mcp.app_transport.calls_to("/api/core/holds")
    five = mcp.execute(admin_token, *calls[:5])
    assert not five.is_error and len(five.results) == 5


def test_ac26_an_empty_calls_list_and_duplicate_ids_are_refused(mcp, admin_token):
    assert mcp.call(admin_token, "execute", {"calls": []}).is_error
    assert mcp.execute(admin_token, call("a", "list_open_holds"), call("a", "list_open_holds")).is_error


@pytest.mark.parametrize(
    "operation_id",
    [
        "create_inventory_item",  # a POST, even though marked mcp
        "list_org_users",  # users.manage is not a read permission
        "list_core_suppliers",  # not marked mcp
        "no_such_operation",
    ],
)
def test_ac26_an_operation_that_is_not_allowlisted_is_not_found_and_no_request_is_made(mcp, admin_token, operation_id):
    result = mcp.execute(admin_token, call("a", operation_id))
    entry = result.results[0]
    assert entry["ok"] is False and entry["error"]["message"] == "Not found" and entry["error"]["kind"] == "not_found"
    assert [r for r in mcp.app_transport.requests if r.url.path not in {ME_PATH, "/api/openapi.json"}] == []


def test_ac26_an_operation_the_caller_does_not_hold_is_not_found_with_no_request(world, mcp):
    token = token_for(world, "sales")  # no production.view or costs.view
    for operation in ("list_executions", "list_processes", "get_lot_cost"):
        entry = mcp.execute(token, call("a", operation, {"item_id": str(uuid4())})).results[0]
        assert entry["error"]["message"] == "Not found", operation
    assert [r for r in mcp.app_transport.requests if r.url.path not in {ME_PATH, "/api/openapi.json"}] == []


def test_ac26_an_undeclared_parameter_is_refused_and_never_passed_through(mcp, admin_token):
    result = mcp.execute(admin_token, call("a", "list_inventory", {"q": "x", "org_id": str(uuid4())}))
    entry = result.results[0]
    assert entry["ok"] is False and entry["error"]["kind"] == "invalid_input"
    assert "org_id" in entry["error"]["message"]
    assert not mcp.app_transport.calls_to("/api/core/inventory")


@pytest.mark.parametrize(
    "operation,params",
    [
        ("list_inventory", {"type": "not_a_type"}),
        ("list_inventory", {"limit": "many"}),
        ("list_inventory", {"limit": 0}),
        ("list_inventory", {"site_id": "not-a-uuid"}),
        ("get_execution", {}),  # a required path parameter missing
        ("get_execution", {"execution_id": "../../settings"}),
        ("get_execution", {"execution_id": f"{uuid4()}/steps"}),
        ("get_execution", {"execution_id": {"nested": "object"}}),
        ("list_executions", {"status": ["completed"]}),
    ],
)
def test_ac26_params_are_validated_against_the_operations_schema_before_any_request(mcp, admin_token, operation, params):
    entry = mcp.execute(admin_token, call("a", operation, params)).results[0]
    assert entry["ok"] is False and entry["error"]["kind"] == "invalid_input", entry
    assert [r for r in mcp.app_transport.requests if r.url.path not in {ME_PATH, "/api/openapi.json"}] == []


def test_ac26_120_lots_return_50_rows_and_a_cursor_then_50_then_20(world, mcp, admin_token):
    seed_lots(world, 120)
    seen, cursor, sizes = [], None, []
    for _ in range(5):
        params = {"type": "final_product", **({"cursor": cursor} if cursor else {})}
        entry = mcp.execute(admin_token, call("a", "list_inventory", params)).results[0]
        assert entry["ok"], entry
        rows = entry["data"]["inventory_items"]
        sizes.append(len(rows))
        seen += [r["id"] for r in rows]
        cursor = entry.get("next_cursor")
        if not cursor:
            break
        assert any("next_cursor" in n for n in entry["notes"]), "the result says there is more"
    assert sizes == [50, 50, 20]
    assert len(set(seen)) == 120


def test_ac26_a_limit_above_50_is_clamped_to_50(world, mcp, admin_token):
    seed_lots(world, 60)
    entry = mcp.execute(admin_token, call("a", "list_inventory", {"type": "final_product", "limit": 50})).results[0]
    assert len(entry["data"]["inventory_items"]) == 50
    over = mcp.execute(admin_token, call("a", "list_inventory", {"type": "final_product", "limit": 50}))
    sent = [r for r in mcp.app_transport.calls_to("/api/core/inventory") if r.url.params.get("limit")]
    assert all(int(r.url.params["limit"]) <= 50 for r in sent) and over.results


def test_ac26_a_list_the_app_returns_whole_is_cut_to_50_rows_with_a_note():
    holds = [{"id": str(i), "reason": f"r{i}"} for i in range(130)]
    transport = stub_app({"/api/core/holds": json_response(200, {"holds": holds})})
    with Mcp(transport) as mcp:
        entry = mcp.execute("bza_x", call("a", "list_open_holds")).results[0]
    assert len(entry["data"]["holds"]) == 50
    assert any("50 of 130" in n for n in entry["notes"])


def test_ac26_output_over_256_kb_is_truncated_with_a_note():
    big = [{"id": str(i), "text": "x" * 1500} for i in range(50)]
    routes = {f"/api/core/holds": json_response(200, {"holds": big}), "/api/core/processes": json_response(200, {"processes": big})}
    transport = stub_app(routes)
    with Mcp(transport) as mcp:
        calls = [call(f"c{i}", "list_open_holds") for i in range(3)] + [call(f"p{i}", "list_processes") for i in range(2)]
        result = mcp.execute("bza_x", *calls)
        assert not result.is_error, result.text
    assert len(result.text.encode()) <= 256 * 1024 + 2048
    assert any("256 KB" in n for n in result.data["notes"])
    assert all(r["ok"] for r in result.results), "rows are left out; the calls still succeeded"


def test_select_trims_the_result(world, mcp, admin_token):
    seed_lots(world, 3, prefix="Orris Root", inventory_type="raw_material")
    entry = mcp.execute(
        admin_token,
        call("a", "list_inventory", {"q": "orris"}, select="inventory_items[*].{name: name, qty: quantity}"),
    ).results[0]
    assert sorted(r["name"] for r in entry["data"]) == ["Orris Root 000", "Orris Root 001", "Orris Root 002"]
    assert set(entry["data"][0]) == {"name", "qty"}
    bad = mcp.execute(admin_token, call("a", "list_inventory", select="max(inventory_items)")).results[0]
    assert bad["ok"] is False and bad["error"]["kind"] == "invalid_input"


def test_a_failed_call_stops_what_depends_on_it_but_not_the_rest(world, mcp, admin_token):
    result = mcp.execute(
        admin_token,
        call("a", "no_such_operation"),
        call("b", "list_open_holds"),
        call("c", "get_execution", {"execution_id": {"$from": "a", "path": "id"}}),
    )
    a, b, c = result.results
    assert not a["ok"] and b["ok"] and not c["ok"]
    assert c["error"]["kind"] == "dependency_failed"
    assert result.data["ok"] is False and result.is_error


@pytest.mark.parametrize(
    "reference",
    [
        {"$from": "later", "path": "id"},  # not an earlier call
        {"$from": "first", "path": "inventory_items"},  # leads to a list, not a value
        {"$from": "first", "path": "nothing.here"},  # finds nothing
        {"$from": "first", "path": "max(x)"},  # a function
        {"$from": "first", "path": "id", "extra": 1},  # unknown key
    ],
)
def test_bad_references_are_errors_not_guesses(world, mcp, admin_token, reference):
    result = mcp.execute(
        admin_token,
        call("first", "list_inventory", {"q": "Juniper"}),
        call("second", "get_execution", {"execution_id": reference}),
        call("later", "list_open_holds"),
    )
    assert result.results[0]["ok"] and result.results[1]["ok"] is False
    assert not mcp.app_transport.calls_to("/api/core/executions")


def test_the_app_is_asked_for_real_data_and_org_b_never_appears(world, mcp, admin_token):
    result = mcp.execute(admin_token, call("a", "list_inventory"), call("b", "list_inventory", {"q": "Secret"}))
    assert "Org B Secret Botanical" not in result.text
    assert result.results[1]["data"]["inventory_items"] == []
    other = mcp.execute(admin_token, call("t", "trace_inventory_backward", {"inventory_item_id": str(world.other_item.id)}))
    assert other.results[0]["error"]["message"] == "Not found"


def test_batches_workflows_and_holds_match_the_session_api(world, mcp, admin_token):
    from app.core.services import lot_holds

    process = ProcessFactory(org_id=world.org.id, name="Gin")
    execution = ExecutionFactory(org_id=world.org.id, process_id=process.id)
    lot_holds.place_hold(world.db, world.org.id, world.item.id, "Cloudy on inspection", world.users["admin"].id)
    world.db.commit()
    result = mcp.execute(
        admin_token,
        call("exec", "list_executions"),
        call("one", "get_execution", {"execution_id": str(execution.id)}),
        call("procs", "list_processes"),
        call("proc", "get_process", {"process_id": str(process.id)}),
        call("holds", "list_open_holds"),
    )
    assert all(r["ok"] for r in result.results), result.text
    exec_ids = {e["id"] for e in result.results[0]["data"]["executions"]}
    assert exec_ids == {e["id"] for e in session_json(world, "admin", "/api/core/executions")["executions"]}
    assert result.results[1]["data"]["id"] == str(execution.id)
    assert str(process.id) in {p["id"] for p in result.results[2]["data"]["processes"]}
    assert result.results[3]["data"]["name"] == "Gin"
    assert result.results[4]["data"]["holds"][0]["reason"] == "Cloudy on inspection"


# ---------------------------------------------------------------------------------------- AC27


@pytest.fixture
def costing_world(world):
    from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository

    FeatureSubscriptionRepository(world.db).grant(world.org.id, "costing")
    world.db.commit()
    return world


def test_ac27_a_lot_with_no_cost_returns_null_with_a_status_never_zero(costing_world, mcp, admin_token):
    world = costing_world
    entry = mcp.execute(admin_token, call("c", "get_lot_cost", {"item_id": str(world.item.id)})).results[0]
    assert entry["ok"], entry
    data = entry["data"]
    assert data["unit_cost"] is None
    assert data["status"] and data["status"] != "actual"
    assert '"unit_cost":null' in mcp.execute(admin_token, call("c", "get_lot_cost", {"item_id": str(world.item.id)})).text


def test_ac27_a_priced_lot_shows_its_price(costing_world, mcp, admin_token):
    world = costing_world
    put = world.session("admin").put(
        f"/api/core/costing/lots/{world.item.id}/cost", json={"kind": "manual", "amount": "80", "quantity": "2"}
    )
    assert put.status_code == 200, put.get_data(as_text=True)
    data = mcp.execute(admin_token, call("c", "get_lot_cost", {"item_id": str(world.item.id)})).results[0]["data"]
    assert data["unit_cost"] is not None and data["status"] != "unknown"


def test_a_select_that_misses_a_field_gives_null_never_zero(costing_world, mcp, admin_token):
    world = costing_world
    entry = mcp.execute(
        admin_token, call("c", "get_lot_cost", {"item_id": str(world.item.id)}, select="{cost: unit_cost, nope: nope}")
    ).results[0]
    assert entry["data"] == {"cost": None, "nope": None}


def test_a_feature_the_org_lacks_hides_the_operation(world, mcp, admin_token):
    entry = mcp.execute(admin_token, call("c", "get_lot_cost", {"item_id": str(world.item.id)})).results[0]
    assert entry["error"]["message"] == "Not found"


def test_the_crm_invoice_operation_pages_like_the_app(world, mcp, admin_token):
    entry = mcp.execute(admin_token, call("i", "crm_list_invoices", {"kind": "all", "page_size": 25})).results[0]
    assert entry["ok"], entry
    assert entry["data"]["page_size"] == 25 and entry["data"]["invoices"] == []
