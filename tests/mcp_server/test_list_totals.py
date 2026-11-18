"""Design review 2026-11-17 M1 and M2: totals on lists, and answers that must be whole.

M1: a list came back as 50 rows and nothing else, so an assistant added up the first page. Now every
``list`` operation's app response carries ``total_count`` (all matching rows, not the page) and, where
the list has one obvious quantity, a total of it computed by the server, and ``execute`` hands both on.

M2: a nested list inside a calculation (a trace, an excise return, a stocktake reconciliation) was cut
to 50 with a note and no cursor, so a partial recall trace read as the answer. Operations marked
``x-bize.complete`` are now whole or an ``incomplete`` error with the counts and the app page to open.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

from app.features.crm.models.xero_invoice import XeroInvoice
from tests.factories import ExecutionFactory, InventoryItemFactory, ProcessFactory
from tests.mcp_server.support import Mcp, json_response, stub_app


def call(call_id: str, operation_id: str, params: dict | None = None, select: str | None = None) -> dict:
    body = {"id": call_id, "operation_id": operation_id, "params": params or {}}
    if select:
        body["select"] = select
    return body


def seed_lots(world, count: int) -> Decimal:
    """``count`` finished lots of 1..count bottles; returns the quantity of all of them."""
    for i in range(count):
        InventoryItemFactory(
            org_id=world.org.id,
            name=f"Totals Lot {i:03d}",
            inventory_type="final_product",
            quantity=str(i + 1),
            unit="bottle",
        )
    world.db.commit()
    return Decimal(count * (count + 1) // 2)


# ---- M1: list totals -------------------------------------------------------------------------


def test_m1_120_lots_return_total_count_120_and_the_quantity_of_all_120_while_rows_stay_50(world, mcp, admin_token):
    everything = seed_lots(world, 120)
    entry = mcp.execute(admin_token, call("a", "list_inventory", {"type": "final_product"})).results[0]
    assert entry["ok"], entry
    assert len(entry["data"]["inventory_items"]) == 50, "the page is still 50 rows"
    assert entry["total_count"] == 120, "the count is of every matching lot, not the page"
    by_unit = {t["unit"]: t for t in entry["totals"]["quantity_by_unit"]}
    assert Decimal(by_unit["bottle"]["quantity"]) == everything == Decimal(7260)
    assert by_unit["bottle"]["lot_count"] == 120
    assert any("do not add" in n.lower() for n in entry["notes"]), entry["notes"]


def test_m1_totals_survive_a_select_that_projects_the_rows(world, mcp, admin_token):
    seed_lots(world, 60)
    entry = mcp.execute(
        admin_token, call("a", "list_inventory", {"type": "final_product"}, select="inventory_items[*].name")
    ).results[0]
    assert len(entry["data"]) == 50
    assert entry["total_count"] == 60
    assert Decimal(entry["totals"]["quantity_by_unit"][0]["quantity"]) == Decimal(1830)


def test_m1_the_inventory_page_and_its_totals_use_the_same_filter(world, admin_token):
    seed_lots(world, 3)
    InventoryItemFactory(org_id=world.org.id, name="Empty", inventory_type="final_product", quantity="0", unit="bottle")
    world.db.commit()
    body = world.session("admin").get("/api/core/inventory?type=final_product&limit=2").get_json()
    assert len(body["inventory_items"]) == 2 and body["has_more"] is True
    assert body["total_count"] == 3, "sold-out lines are hidden from the page, so from the count too"
    assert body["totals"]["quantity_by_unit"] == [{"unit": "bottle", "quantity": "6", "lot_count": 3}]


def test_m1_the_executions_page_carries_the_count_of_every_match(world):
    process = ProcessFactory(org_id=world.org.id, name=f"Totals {uuid4().hex[:6]}")
    world.db.commit()
    for _ in range(4):
        ExecutionFactory(org_id=world.org.id, process_id=process.id)
    world.db.commit()
    body = world.session("admin").get(f"/api/core/executions?process_id={process.id}&limit=1").get_json()
    assert len(body["executions"]) == 1 and body["has_more"] is True
    assert body["total_count"] == 4


def test_m1_lists_the_app_returns_whole_say_how_many_there_are(world):
    client = world.session("admin")
    for path, key in (("/api/core/processes", "processes"), ("/api/core/holds", "holds")):
        body = client.get(path).get_json()
        assert body["total_count"] == len(body[key]), path


def _invoice(world, number: str, *, sub_total, total, tax, status="AUTHORISED", currency="NZD"):
    world.db.add(
        XeroInvoice(
            org_id=world.org.id,
            xero_invoice_id=f"inv-{uuid4()}",
            xero_tenant_id="t",
            invoice_type="ACCREC",
            status=status,
            invoice_number=number,
            date=date(2026, 10, 20),
            sub_total=Decimal(sub_total),
            total=Decimal(total),
            total_tax=Decimal(tax),
            currency_code=currency,
        )
    )


def test_m1_invoices_carry_ex_gst_revenue_of_every_match_by_the_one_revenue_rule(world):
    for i in range(3):
        _invoice(world, f"TOT-{i}", sub_total="100", total="115", tax="15")
    _invoice(world, "TOT-USD", sub_total="50", total="50", tax="0", currency="USD")
    _invoice(world, "TOT-DRAFT", sub_total="999", total="999", tax="0", status="DRAFT")
    world.db.commit()
    body = world.session("admin").get("/api/crm/invoices?kind=all&page_size=2").get_json()
    assert len(body["invoices"]) == 2
    assert body["total_count"] == body["total"] == 5
    revenue = body["totals"]["revenue"]
    assert revenue["total"] == "300.00", "ex GST, base currency, authorised or paid: the rule from !738"
    assert revenue["currency"] == "NZD"
    assert revenue["not_converted"] == 1
    assert revenue["invoiced_inc_gst"] == "395.00"


def test_m1_execute_says_a_page_must_not_be_summed():
    from bize_mcp.tools.execute import DESCRIPTION

    assert "total_count" in DESCRIPTION
    assert "has_more" in DESCRIPTION and "never add up" in DESCRIPTION.lower()


# ---- M2: complete or fail --------------------------------------------------------------------

TRACE_PATH = "/api/core/inventory/trace-backward/"
ITEM_ID = "6f1c1d52-1f6e-4a54-9f0f-2f7c7a9d1c11"


def _trace(nodes: int, *, bulky: bool = False) -> dict:
    # Text is clipped at 2,000 characters a field, so a bulky trace repeats its nodes in three lists.
    items = [{"id": str(i), "name": f"node {i}" + ("x" * 1990 if bulky else "")} for i in range(nodes)]
    return {
        "traced_item": items[0],
        "all_items": items,
        "connections": [{"from": str(i), "to": str(i + 1)} for i in range(nodes - 1)],
        "raw_materials": items if bulky else [],
        "intermediates": items if bulky else [],
        "trace_steps": [],
    }


def _run_trace(body: dict):
    transport = stub_app({TRACE_PATH + ITEM_ID: json_response(200, body)})
    with Mcp(transport) as mcp:
        return mcp.execute("bza_x", call("t", "trace_inventory_backward", {"inventory_item_id": ITEM_ID}))


def test_m2_a_trace_with_60_nodes_returns_incomplete_not_50_nodes():
    result = _run_trace(_trace(60))
    entry = result.results[0]
    assert entry["ok"] is False, "a cut trace must never come back as an answer"
    assert "data" not in entry or entry["data"] is None
    error = entry["error"]
    assert error["kind"] == "incomplete"
    assert error["counts"] == {"all_items": 60, "connections": 59}
    assert error["limit"] == 50
    assert error["app_url"].endswith("/core/sourcemap")
    assert error["app_url"].startswith("https://")


def test_m2_a_complete_operation_under_the_limits_returns_whole():
    entry = _run_trace(_trace(50)).results[0]
    assert entry["ok"], entry
    assert len(entry["data"]["all_items"]) == 50 and len(entry["data"]["connections"]) == 49
    assert "notes" not in entry


def test_m2_a_complete_operation_over_256_kb_is_incomplete_not_trimmed():
    entry = _run_trace(_trace(45, bulky=True)).results[0]
    assert entry["ok"] is False, "no list is over 50 rows, but 256 KB would trim one: still incomplete"
    assert entry["error"]["kind"] == "incomplete"
    assert entry["error"]["counts"]["all_items"] == 45


def test_m2_a_list_operation_is_still_cut_with_a_note_not_failed():
    holds = [{"id": str(i), "reason": f"r{i}"} for i in range(130)]
    transport = stub_app({"/api/core/holds": json_response(200, {"holds": holds, "total_count": 130})})
    with Mcp(transport) as mcp:
        entry = mcp.execute("bza_x", call("a", "list_open_holds")).results[0]
    assert entry["ok"] and len(entry["data"]["holds"]) == 50
    assert entry["total_count"] == 130
