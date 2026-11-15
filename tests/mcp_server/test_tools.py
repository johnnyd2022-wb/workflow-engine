"""AC26: each tool returns the app route's data for a seeded org, capped at 50 rows with a cursor.

Every test runs the whole chain: the SDK-facing ASGI app, a real bearer token, the real Flask app
and its access policy. Where a tool wraps a route, the expected answer is what the same person's
session gets from that route.
"""

from __future__ import annotations

from datetime import date, timedelta
from uuid import uuid4

import pytest

from app.core.db.models.inventory_item import InventoryItem
from app.core.services import lot_holds
from tests.factories import ExecutionFactory, InventoryItemFactory, ProcessFactory
from tests.mcp_server.conftest import token_for

PAGE = 50


def seed_lots(world, count: int, *, prefix: str = "Paging Lot", inventory_type: str = "final_product") -> list:
    items = [
        InventoryItemFactory(
            org_id=world.org.id, name=f"{prefix} {i:03d}", inventory_type=inventory_type, quantity="5", unit="bottle"
        )
        for i in range(count)
    ]
    world.db.commit()
    return items


def walk(mcp, token, tool: str, arguments: dict | None = None) -> list[dict]:
    """Every page of a list tool, following next_cursor until it is null."""
    pages, cursor = [], None
    for _ in range(40):
        args = dict(arguments or {})
        if cursor:
            args["cursor"] = cursor
        result = mcp.call(token, tool, args)
        assert not result.is_error, result.text
        pages.append(result.data)
        cursor = result.data["next_cursor"]
        if not cursor:
            return pages
    raise AssertionError("cursor never ended")


def session_json(world, who: str, path: str):
    response = world.session(who).get(path)
    assert response.status_code == 200, (path, response.status_code, response.get_data(as_text=True)[:300])
    return response.get_json()


# ---------------------------------------------------------------------------------------- inventory


def test_ac26_120_lots_page_as_50_then_50_then_20(world, mcp, admin_token):
    seed_lots(world, 120)
    pages = walk(mcp, admin_token, "search_inventory", {"type": "final_product"})
    assert [p["row_count"] for p in pages] == [50, 50, 20]
    assert [len(p["rows"]) for p in pages] == [50, 50, 20]
    assert [p["has_more"] for p in pages] == [True, True, False]
    assert pages[0]["next_cursor"] and pages[1]["next_cursor"] and pages[2]["next_cursor"] is None
    assert "next_cursor" in pages[0]["message"], "the result must say there is more"
    ids = [row["id"] for page in pages for row in page["rows"]]
    assert len(ids) == len(set(ids)) == 120
    in_db = {
        str(i.id)
        for i in world.db.query(InventoryItem).filter(
            InventoryItem.org_id == world.org.id, InventoryItem.inventory_type == "final_product"
        )
    }
    assert set(ids) == in_db


def test_ac26_search_inventory_rows_carry_the_stock_fields(world, mcp, admin_token):
    result = mcp.call(admin_token, "search_inventory", {"query": "Juniper"})
    assert not result.is_error, result.text
    assert [row["name"] for row in result.rows] == ["Org A Juniper"]
    row = result.rows[0]
    assert row["id"] == str(world.item.id)
    assert {"quantity", "unit", "inventory_type"} <= set(row)
    assert result.data["next_cursor"] is None and result.data["has_more"] is False


def test_ac26_search_inventory_matches_the_session_api(world, mcp, admin_token):
    seed_lots(world, 3, prefix="Orris Root", inventory_type="raw_material")
    expected = session_json(world, "admin", "/api/core/inventory?limit=50&type=raw_material")
    result = mcp.call(admin_token, "search_inventory", {"type": "raw_material"})
    assert {r["id"] for r in result.rows} == {i["id"] for i in expected["inventory_items"]}


def test_ac26_search_inventory_query_filters_by_name_and_never_reaches_another_org(world, mcp, admin_token):
    seed_lots(world, 2, prefix="Orris Root", inventory_type="raw_material")
    found = mcp.call(admin_token, "search_inventory", {"query": "orris"})
    assert {r["name"] for r in found.rows} == {"Orris Root 000", "Orris Root 001"}
    assert mcp.call(admin_token, "search_inventory", {"query": "Secret Botanical"}).rows == []
    everything = walk(mcp, admin_token, "search_inventory")
    assert "Org B Secret Botanical" not in str(everything)


def test_ac26_search_inventory_filters_by_site(world, mcp, admin_token):
    unknown_site = str(uuid4())
    result = mcp.call(admin_token, "search_inventory", {"site": unknown_site})
    assert not result.is_error and result.rows == []


def test_ac26_search_inventory_rejects_a_bad_site(mcp, admin_token):
    result = mcp.call(admin_token, "search_inventory", {"site": "not-a-uuid"})
    assert result.is_error
    assert "site" in result.text


def test_ac26_stock_position_returns_the_apps_position(world, mcp, admin_token):
    seed_lots(world, 3, prefix="Gin 700ml", inventory_type="final_product")
    expected = session_json(world, "admin", "/api/core/stock-position")
    result = mcp.call(admin_token, "stock_position")
    assert not result.is_error, result.text
    assert result.data["as_at"] == expected["as_at"]
    app_ids = {lot["id"] for place in expected["places"] for lot in place["lots"]}
    assert {row["id"] for row in result.rows} == app_ids
    assert all("place" in row and "stage" in row for row in result.rows)


def test_ac26_stock_position_is_as_at_today_only(world, mcp, admin_token):
    expected = session_json(world, "admin", "/api/core/stock-position")
    ok = mcp.call(admin_token, "stock_position", {"as_of": expected["as_at"]})
    assert not ok.is_error, ok.text
    past = (date.fromisoformat(expected["as_at"]) - timedelta(days=30)).isoformat()
    refused = mcp.call(admin_token, "stock_position", {"as_of": past})
    assert refused.is_error
    assert "today" in refused.text


def test_ac26_stock_position_pages_through_a_long_list(world, mcp, admin_token):
    seed_lots(world, 120, prefix="Bottle", inventory_type="final_product")
    pages = walk(mcp, admin_token, "stock_position")
    assert [p["row_count"] for p in pages] == [50, 50, 20]
    assert pages[0]["as_at"] == pages[2]["as_at"]


def test_ac26_trace_lot_back_and_to_sale(world, mcp, admin_token):
    path = f"/api/core/inventory/trace-backward/{world.item.id}"
    expected_back = session_json(world, "admin", path)
    back = mcp.call(admin_token, "trace_lot", {"item_id": str(world.item.id), "direction": "back"})
    assert not back.is_error, back.text
    assert back.data["direction"] == "back"
    assert {r["id"] for r in back.rows} >= {str(world.item.id)}
    assert {r["id"] for r in back.rows} == {i["id"] for i in expected_back["all_items"]}

    expected_graph = session_json(world, "admin", f"/api/core/inventory/trace-graph/{world.item.id}")
    graph = mcp.call(admin_token, "trace_lot", {"item_id": str(world.item.id), "direction": "to_sale"})
    assert not graph.is_error, graph.text
    assert graph.data["direction"] == "to_sale"
    assert {r["id"] for r in graph.rows} == {i["id"] for i in expected_graph["all_items"]}
    assert "connections" in graph.data


def test_ac26_trace_lot_cannot_see_another_orgs_lot(world, mcp, admin_token):
    result = mcp.call(admin_token, "trace_lot", {"item_id": str(world.other_item.id), "direction": "back"})
    assert result.is_error
    assert result.text.strip().startswith("Not found")
    assert "Secret" not in result.text


@pytest.mark.parametrize(
    "arguments", [{"item_id": "nope", "direction": "back"}, {"item_id": str(uuid4()), "direction": "sideways"}, {}]
)
def test_ac26_trace_lot_validates_its_arguments(mcp, admin_token, arguments):
    result = mcp.call(admin_token, "trace_lot", arguments)
    assert result.is_error
    assert not mcp.app_transport.calls_to("/api/core/inventory/trace"), "invalid input must not reach the app"


def test_ac26_list_open_holds_shows_held_lots_with_their_reason(world, mcp, admin_token):
    lot_holds.place_hold(world.db, world.org.id, world.item.id, "Cloudy on inspection", world.users["admin"].id)
    world.db.commit()
    result = mcp.call(admin_token, "list_open_holds")
    assert not result.is_error, result.text
    assert [r["inventory_item_id"] for r in result.rows] == [str(world.item.id)]
    assert result.rows[0]["reason"] == "Cloudy on inspection"
    assert result.rows[0]["lot"]["name"] == "Org A Juniper"


def test_ac26_list_open_holds_is_empty_when_nothing_is_held(mcp, admin_token):
    result = mcp.call(admin_token, "list_open_holds")
    assert result.rows == [] and result.data["has_more"] is False


# -------------------------------------------------------------------------------------- production


def test_ac26_workflows_list_and_get(world, mcp, admin_token):
    processes = [ProcessFactory(org_id=world.org.id, name=f"Workflow {i:03d}") for i in range(55)]
    world.db.commit()
    pages = walk(mcp, admin_token, "list_workflows")
    assert [p["row_count"] for p in pages] == [50, 5]
    ids = {row["id"] for page in pages for row in page["rows"]}
    assert ids == {str(p.id) for p in processes}

    detail = mcp.call(admin_token, "get_workflow", {"process_id": str(processes[0].id)})
    assert not detail.is_error, detail.text
    assert detail.data["id"] == str(processes[0].id)
    assert detail.data["name"] == "Workflow 000"
    assert detail.data["steps"] == []


def test_ac26_get_workflow_unknown_is_not_found(mcp, admin_token):
    result = mcp.call(admin_token, "get_workflow", {"process_id": str(uuid4())})
    assert result.is_error and result.text.strip().startswith("Not found")


def test_ac26_batches_list_and_get(world, mcp, admin_token):
    process = ProcessFactory(org_id=world.org.id, name="Gin")
    executions = [ExecutionFactory(org_id=world.org.id, process_id=process.id) for _ in range(3)]
    world.db.commit()
    expected = session_json(world, "admin", "/api/core/executions?limit=50")
    listed = mcp.call(admin_token, "list_batches")
    assert not listed.is_error, listed.text
    assert {r["id"] for r in listed.rows} == {e["id"] for e in expected["executions"]}
    assert {r["id"] for r in listed.rows} == {str(e.id) for e in executions}
    assert {"status", "process_id"} <= set(listed.rows[0])

    one = mcp.call(admin_token, "get_batch", {"execution_id": str(executions[0].id)})
    assert not one.is_error, one.text
    assert one.data["id"] == str(executions[0].id)
    assert "steps" in one.data


def test_ac26_list_batches_filters_by_status_and_pages(world, mcp, admin_token):
    process = ProcessFactory(org_id=world.org.id, name="Vodka")
    for _ in range(60):
        ExecutionFactory(org_id=world.org.id, process_id=process.id)
    world.db.commit()
    pages = walk(mcp, admin_token, "list_batches")
    assert [p["row_count"] for p in pages] == [50, 10]
    done = mcp.call(admin_token, "list_batches", {"status": "completed"})
    assert not done.is_error and done.rows == []
    bad = mcp.call(admin_token, "list_batches", {"status": "nonsense"})
    assert bad.is_error


def test_ac26_get_batch_of_another_org_is_not_found(world, mcp, admin_token):
    other_process = ProcessFactory(org_id=world.other_org.id, name="Other")
    other = ExecutionFactory(org_id=world.other_org.id, process_id=other_process.id)
    world.db.commit()
    result = mcp.call(admin_token, "get_batch", {"execution_id": str(other.id)})
    assert result.is_error and result.text.strip().startswith("Not found")


# ------------------------------------------------------------------------------------- compliance


def test_ac26_compliance_tools_mirror_the_session_api(world, mcp, admin_token):
    from tests.factories import FeatureSubscriptionFactory

    FeatureSubscriptionFactory(org_id=world.org.id, feature_key="compliant")
    world.db.commit()
    expected = session_json(world, "admin", "/api/compliant/records")
    records = mcp.call(admin_token, "list_compliance_records")
    assert not records.is_error, records.text
    assert [r["id"] for r in records.rows] == [r["id"] for r in expected["records"]]

    position_expected = session_json(world, "admin", "/api/compliant/nz-alcohol/excise/position")
    position = mcp.call(admin_token, "excise_position")
    assert not position.is_error, position.text
    assert set(position_expected) <= set(position.data)

    period_expected = session_json(world, "admin", "/api/compliant/nz-alcohol/excise")
    period = mcp.call(admin_token, "excise_period")
    assert not period.is_error, period.text
    assert set(period_expected) <= set(period.data)


def test_ac26_compliance_tools_say_not_available_when_the_module_is_off(world, mcp, admin_token):
    result = mcp.call(admin_token, "excise_position")
    # Whatever the app answers for an org with no compliance module (404 or 403), the tool says so plainly.
    assert result.is_error
    assert "Not available for your organisation" in result.text


# ------------------------------------------------------------------------------------------ sales


def seed_invoices(world, dates: list[date]):
    from app.features.crm.models.xero_contact import XeroContact
    from app.features.crm.models.xero_invoice import XeroInvoice

    contact = XeroContact(org_id=world.org.id, xero_contact_id=f"c-{uuid4()}", xero_tenant_id="t", name="Bottle Shop")
    world.db.add(contact)
    world.db.flush()
    rows = []
    for index, day in enumerate(dates):
        invoice = XeroInvoice(
            org_id=world.org.id,
            xero_invoice_id=f"inv-{uuid4()}",
            xero_tenant_id="t",
            contact_id=contact.id,
            invoice_type="ACCREC",
            status="AUTHORISED",
            invoice_number=f"INV-{index:04d}",
            date=day,
            total=100 + index,
        )
        world.db.add(invoice)
        rows.append(invoice)
    world.db.commit()
    return rows


def test_ac26_list_invoices_pages_as_50_50_20_newest_first(world, mcp, admin_token):
    today = date.today()
    seed_invoices(world, [today - timedelta(days=i) for i in range(120)])
    pages = walk(mcp, admin_token, "list_invoices")
    assert [p["row_count"] for p in pages] == [50, 50, 20]
    ids = [r["id"] for p in pages for r in p["rows"]]
    assert len(set(ids)) == 120
    dates = [r["date"] for p in pages for r in p["rows"]]
    assert dates == sorted(dates, reverse=True)
    assert pages[0]["rows"][0]["contact_name"] == "Bottle Shop"


def test_ac26_list_invoices_filters_by_date_range(world, mcp, admin_token):
    today = date.today()
    seed_invoices(world, [today - timedelta(days=d) for d in (1, 10, 40, 100)])
    window = mcp.call(
        admin_token,
        "list_invoices",
        {"from": (today - timedelta(days=45)).isoformat(), "to": (today - timedelta(days=5)).isoformat()},
    )
    assert not window.is_error, window.text
    assert sorted(r["date"] for r in window.rows) == sorted(
        [(today - timedelta(days=10)).isoformat(), (today - timedelta(days=40)).isoformat()]
    )
    assert mcp.call(admin_token, "list_invoices", {"from": "yesterday"}).is_error


def test_ac26_monthly_sales_mirrors_the_session_api(world, mcp, admin_token):
    seed_invoices(world, [date.today(), date.today() - timedelta(days=40)])
    expected = session_json(world, "admin", "/api/crm/analytics/monthly-sales?months=3")
    result = mcp.call(admin_token, "monthly_sales", {"months": 3})
    assert not result.is_error, result.text
    assert result.rows == expected["monthly_sales"]
    assert mcp.call(admin_token, "monthly_sales", {"months": 99}).is_error


# ------------------------------------------------------------------------------------------ costs


@pytest.fixture
def costing_world(world):
    from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository

    FeatureSubscriptionRepository(world.db).grant(world.org.id, "costing")
    world.db.commit()
    return world


def test_ac26_get_cost_for_a_lot_a_batch_and_a_product(costing_world, mcp, admin_token):
    world = costing_world
    lot = mcp.call(admin_token, "get_cost", {"lot_id": str(world.item.id)})
    assert not lot.is_error, lot.text
    assert lot.data["inventory_item_id"] == str(world.item.id)

    process = ProcessFactory(org_id=world.org.id, name="Costed")
    execution = ExecutionFactory(org_id=world.org.id, process_id=process.id)
    world.db.commit()
    batch = mcp.call(admin_token, "get_cost", {"batch_id": str(execution.id)})
    assert not batch.is_error, batch.text

    key_list = session_json(world, "admin", "/api/core/costing/readiness")["products"]
    if key_list:
        product = mcp.call(admin_token, "get_cost", {"product_key": key_list[0]["key"]})
        assert not product.is_error, product.text


def test_ac27_a_lot_with_no_cost_returns_null_with_a_status_never_zero(costing_world, mcp, admin_token):
    world = costing_world
    result = mcp.call(admin_token, "get_cost", {"lot_id": str(world.item.id)})
    assert not result.is_error, result.text
    assert result.data["unit_cost"] is None
    assert result.data["status"], "an unknown cost carries its status"
    assert '"unit_cost":null' in result.text.replace(" ", "")
    assert result.data["status"] != "actual"


def test_ac27_a_priced_lot_shows_its_price(costing_world, mcp, admin_token):
    world = costing_world
    put = world.session("admin").put(
        f"/api/core/costing/lots/{world.item.id}/cost", json={"kind": "manual", "amount": "80", "quantity": "2"}
    )
    assert put.status_code == 200, put.get_data(as_text=True)
    result = mcp.call(admin_token, "get_cost", {"lot_id": str(world.item.id)})
    assert result.data["unit_cost"] is not None
    assert result.data["status"] != "unknown"


@pytest.mark.parametrize(
    "arguments", [{}, {"lot_id": str(uuid4()), "batch_id": str(uuid4())}, {"lot_id": "not-a-uuid"}]
)
def test_ac26_get_cost_needs_exactly_one_valid_id(costing_world, mcp, admin_token, arguments):
    result = mcp.call(admin_token, "get_cost", arguments)
    assert result.is_error
    assert not mcp.app_transport.calls_to("/api/core/costing")


def test_ac26_costs_say_not_available_when_the_org_has_no_costing(world, mcp, admin_token):
    result = mcp.call(admin_token, "get_cost", {"lot_id": str(world.item.id)})
    assert result.is_error
    assert "not available" in result.text.lower() or result.text.strip().startswith("Not found")


def test_ac26_margins_and_stock_value_mirror_the_session_api(costing_world, mcp, admin_token):
    world = costing_world
    expected = session_json(world, "admin", "/api/core/costing/margins")
    margins = mcp.call(admin_token, "margins")
    assert not margins.is_error, margins.text
    assert set(expected) <= set(margins.data)
    assert not mcp.call(admin_token, "margins", {"from": "2026-01", "to": "2026-03"}).is_error
    assert mcp.call(admin_token, "margins", {"from": "January"}).is_error

    stock = session_json(world, "admin", "/api/core/costing/stock-value")
    value = mcp.call(admin_token, "stock_value")
    assert not value.is_error, value.text
    assert value.data["total_value"] == stock.get("total_value", value.data["total_value"])
    assert {line["name"] for line in value.rows} <= {line["name"] for line in stock["lines"]}


def test_ac26_stock_value_pages_its_lines_and_keeps_unknown_costs_unknown(costing_world, mcp, admin_token):
    world = costing_world
    seed_lots(world, 60, prefix="Unpriced", inventory_type="raw_material")
    pages = walk(mcp, admin_token, "stock_value")
    assert sum(p["row_count"] for p in pages) >= 60
    assert pages[0]["row_count"] == 50
    assert all(row.get("unit_cost") in (None,) or row.get("unit_cost") != 0 for p in pages for row in p["rows"])


def test_ac26_stock_value_as_of_a_month_end_needs_a_snapshot(costing_world, mcp, admin_token):
    result = mcp.call(admin_token, "stock_value", {"as_of": "2019-01-31"})
    assert result.is_error
    assert "snapshot" in result.text.lower()


def test_a_sales_token_cannot_read_costs_even_by_calling_the_hidden_tool(costing_world, mcp):
    world = costing_world
    token = token_for(world, "sales")
    result = mcp.call(token, "get_cost", {"lot_id": str(world.item.id)})
    assert result.is_error
    assert "permission" in result.text.lower() or "access" in result.text.lower()
