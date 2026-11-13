"""Live-cogs 8.1g: the Xero bridge (spec .agents/specs/live-cogs.md, "8.1g build contract").

Written before the implementation. Xero's P&L is a real ``xero_python`` report built in the
shape the API returns; the HTTP call is replaced per test. Periods are labelled by each
snapshot's ``as_of_date`` (the tests pass them in) while their cutoffs are "now", so rows a test
writes fall inside the window they should.
"""

# ruff: noqa: F811 -- flask_app is re-exported as a fixture and used as a test argument

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from xero_python.accounting.models import ReportAttribute, ReportCell, ReportRows

from app.core.db.models.inventory_item import InventoryType
from app.core.db.models.user import UserRole
from app.core.db.repositories.inventory_repo import InventoryRepository
from tests.costing_helpers import D, complete, lot, new_org, price, produced_lots, purge, user_client, workflow
from tests.test_compliant_routes import flask_app  # noqa: F401 -- fixture re-export
from tests.test_costing_allocations import _record, _row, _sync_purchase
from tests.test_costing_purchases import FULL_SCOPES, FakeXero, connect

API = "/api/core/costing"
PL_SCOPE = "accounting.reports.profitandloss.read"
PL_SCOPES = f"{FULL_SCOPES} {PL_SCOPE}"
FINAL = InventoryType.FINAL_PRODUCT.value
OPENING, CLOSING = date(2026, 10, 31), date(2026, 11, 30)  # as_of labels; the period is November


def pl_rows(sections):
    """``sections``: title -> [(account_id | None, name, amount)]. The report rows as Xero sends them."""
    out = [ReportRows(row_type="Header", cells=[ReportCell(value="Account"), ReportCell(value="1 Nov 2026-30 Nov 2026")])]
    for title, rows in sections.items():
        body = [
            ReportRows(
                row_type="Row",
                cells=[
                    ReportCell(
                        value=name, attributes=[ReportAttribute(id="account", value=account_id)] if account_id else None
                    ),
                    ReportCell(value=amount),
                ],
            )
            for account_id, name, amount in rows
        ]
        body.append(ReportRows(row_type="SummaryRow", cells=[ReportCell(value=f"Total {title}"), ReportCell(value="1.00")]))
        out.append(ReportRows(row_type="Section", title=title, rows=body))
    return out


def install_pl(monkeypatch, fake, build):
    """``build(from_date, to_date)`` returns the report rows; calls are recorded on the fake."""
    from app.features.crm.services import xero_api_client as module

    def get_profit_and_loss(_self, from_date, to_date):
        fake.calls.append(("profit_and_loss", {"from": from_date, "to": to_date}))
        return build(from_date, to_date)

    monkeypatch.setattr(module.XeroAPIClient, "get_profit_and_loss", get_profit_and_loss, raising=False)


def account_ids(db, org_id):
    from app.features.crm.models.xero_account import XeroAccount

    db.expire_all()
    return {a.code: a.xero_account_id for a in db.query(XeroAccount).filter(XeroAccount.org_id == org_id).all()}


@pytest.fixture
def world(db, flask_app, monkeypatch):
    org = new_org(db)
    connect(db, org.id, scopes=PL_SCOPES)
    fake = FakeXero().install(monkeypatch)
    install_pl(monkeypatch, fake, lambda *_: pl_rows({"Cost of Sales": []}))
    client = user_client(db, flask_app, org)
    yield {"org": org, "client": client, "fake": fake, "sync": {"org": org, "fake": fake}}
    purge(db, org)


@pytest.fixture
def plain(db, flask_app):
    """An org with costing and no Xero at all."""
    org = new_org(db)
    client = user_client(db, flask_app, org)
    yield org, client
    purge(db, org)


def snap(db, org, as_of):
    from app.features.costing import stock_value

    made = stock_value.take_snapshot(db, org.id, kind="manual", trigger="manual", as_of_date=as_of)
    db.commit()
    return made


def bridge(client, opening, closing, expect=200):
    response = client.get(f"{API}/bridge?from={opening.id}&to={closing.id}")
    assert response.status_code == expect, response.get_json()
    return response.get_json()


def sample(db, org, item, quantity):
    """What a tasting dispatch does to a lot: lower it, with the event naming the reason."""
    from app.core.backend.event_writer import EventWriter
    from app.core.db.repositories.inventory_repo import _item_snapshot
    from app.core.domain.inventory_quantity_guard import InventoryQuantityWriteReason, allow_inventory_quantity_write

    row = InventoryRepository(db).get_inventory_item_by_id_for_update(item.id, org.id)
    before = str(row.quantity)
    with allow_inventory_quantity_write(InventoryQuantityWriteReason.TASTING_DISPATCH):
        row.quantity = row.quantity - D(str(quantity))
        db.flush()
    EventWriter(db, org.id).emit(
        event_type="inventory_item.quantity_adjusted",
        entity_type="inventory_item",
        entity_id=row.id,
        payload={
            **_item_snapshot(row),
            "quantity_before": before,
            "quantity_after": str(row.quantity),
            "delta": str(-D(str(quantity))),
            "reason": "tasting_dispatch",
        },
        diff={"quantity": {"before": before, "after": str(row.quantity)}},
    )
    db.commit()


def waste(client, item, quantity):
    response = client.post(
        "/api/core/inventory/wastage",
        json={"entries": [{"inventory_item_id": str(item.id), "quantity_wasted": str(quantity), "reason": "spillage"}]},
    )
    assert response.status_code == 201, response.get_json()


# --- AC138: the P&L fetch ----------------------------------------------------------------------


def test_ac138_scope_is_requested_and_the_report_is_parsed_by_account_id():
    from app.features.costing import bridge as bridge_module
    from app.features.crm.services.xero_oauth_service import XERO_SCOPES

    assert PL_SCOPE in XERO_SCOPES.split()
    rows = pl_rows(
        {
            "Cost of Sales": [("id-310", "Purchases - Ingredients", "1,234.50"), (None, "Freight", "-12.50")],
            "Operating Expenses": [("id-429", "Office Expense", "(5.00)")],
        }
    )

    parsed = bridge_module.parse_profit_and_loss(rows)

    assert [(p["account_id"], p["name"], p["amount"]) for p in parsed] == [
        ("id-310", "Purchases - Ingredients", D("1234.50")),
        (None, "Freight", D("-12.50")),
        ("id-429", "Office Expense", D("-5.00")),
    ]
    assert [p["section"] for p in parsed] == ["Cost of Sales", "Cost of Sales", "Operating Expenses"]


def test_ac138_client_returns_the_report_rows_for_the_period(db, monkeypatch):
    from xero_python.accounting import AccountingApi
    from xero_python.accounting.models import ReportWithRow, ReportWithRows

    from app.features.crm.services.xero_api_client import XeroAPIClient

    rows = pl_rows({"Cost of Sales": [("id-310", "Purchases", "10.00")]})
    seen = {}

    def fake_report(_self, tenant_id, **kwargs):
        seen.update(kwargs, tenant=tenant_id)
        return ReportWithRows(reports=[ReportWithRow(rows=rows)])

    monkeypatch.setattr(AccountingApi, "get_report_profit_and_loss", fake_report)
    org = new_org(db)
    try:
        client = XeroAPIClient(db, org.id)
        monkeypatch.setattr(client, "_get_api_client", lambda: object())
        client._xero_tenant_id = "tenant-1"
        assert client.get_profit_and_loss(date(2026, 11, 1), date(2026, 11, 30)) == rows
        assert (seen["from_date"], seen["to_date"], seen["tenant"]) == (date(2026, 11, 1), date(2026, 11, 30), "tenant-1")
    finally:
        purge(db, org)


# --- AC139 (= AC51): the tie-out -------------------------------------------------------------------


def test_ac139_tie_out_lists_every_stock_line_not_recorded_and_the_journals_gap(world, db, monkeypatch):
    org, client, fake, sync_world = world["org"], world["client"], world["fake"], world["sync"]
    opening = snap(db, org, OPENING)

    _doc, recorded, *_ = _sync_purchase(sync_world, db, "300", on=date(2026, 11, 10), description="Juniper")
    _doc, open_line, *_ = _sync_purchase(sync_world, db, "120", on=date(2026, 11, 12), description="Orris root")
    _doc, not_stock, *_ = _sync_purchase(sync_world, db, "50", on=date(2026, 11, 14), description="Gift basket")
    _sync_purchase(sync_world, db, "70", on=date(2026, 10, 20), description="Last month's botanicals")
    assert _record(client, recorded.id, [_row("Juniper", 6, 300)]).status_code == 200
    assert client.post(f"{API}/purchases/{not_stock.id}/not-stock", json={}, headers={"Idempotency-Key": str(uuid4())}).status_code == 200
    ids = account_ids(db, org.id)
    install_pl(
        monkeypatch,
        fake,
        lambda *_: pl_rows(
            {
                "Cost of Sales": [
                    (ids["310"], "Purchases - Ingredients", "500.00"),
                    (ids["320"], "Excise Duty", "40.00"),
                    (ids["330"], "Direct Rent Costs", "25.00"),
                ]
            }
        ),
    )
    closing = snap(db, org, CLOSING)

    body = bridge(client, opening, closing)

    assert body["state"] == "ok" and body["xero"]["state"] == "ok"
    assert body["period"] == {"from": "2026-11-01", "to": "2026-11-30"}
    assert [c for c in fake.calls if c[0] == "profit_and_loss"][-1][1] == {"from": date(2026, 11, 1), "to": date(2026, 11, 30)}
    tie = body["tie_out"]
    assert (D(tie["xero_stock_total"]), D(tie["recorded"]), D(tie["difference"])) == (D("500"), D("300"), D("200"))
    listed = {row["description"]: row for row in tie["not_recorded"]}
    assert set(listed) == {"Orris root", "Gift basket"}  # not the recorded line, not October's
    assert (D(listed["Orris root"]["listed"]), listed["Orris root"]["state"]) == (D("120"), "open")
    assert (D(listed["Gift basket"]["listed"]), listed["Gift basket"]["state"]) == (D("50"), "not_stock")
    assert D(tie["not_recorded_total"]) == D("170")
    assert D(tie["other_entries"]) == D("30")  # 500 - (300 + 120 + 50): journals Biz-E never saw
    assert D(tie["not_recorded_total"]) + D(tie["other_entries"]) == D(tie["difference"])
    assert D(body["overhead"]["xero_total"]) == D("25")
    assert D(body["duty"]["xero_total"]) == D("40")
    assert body["duty"]["tracked"] is False and body["duty"]["computed"] is None
    assert open_line.id is not None


def test_ac139_a_partly_recorded_line_lists_only_what_is_left(world, db, monkeypatch):
    org, client, fake, sync_world = world["org"], world["client"], world["fake"], world["sync"]
    opening = snap(db, org, OPENING)
    _doc, line, *_ = _sync_purchase(sync_world, db, "200", on=date(2026, 11, 10), description="Juniper and more")
    assert _record(client, line.id, [_row("Juniper", 2, 80)]).status_code == 200  # $80 of $200, the rest later
    ids = account_ids(db, org.id)
    install_pl(monkeypatch, fake, lambda *_: pl_rows({"Cost of Sales": [(ids["310"], "Purchases - Ingredients", "200.00")]}))
    closing = snap(db, org, CLOSING)

    tie = bridge(client, opening, closing)["tie_out"]

    (row,) = tie["not_recorded"]
    assert (D(row["listed"]), row["state"]) == (D("120"), "partly_recorded")
    assert (D(tie["recorded"]), D(tie["other_entries"])) == (D("80"), D("0"))


# --- AC140 (= AC50): the roll-forward ---------------------------------------------------------------


def test_ac140_opening_plus_purchases_minus_closing_is_what_left_stock(world, db):
    org, client, sync_world = world["org"], world["client"], world["sync"]
    juniper = lot(db, org.id, "Juniper", 10, "kg")
    price(db, org.id, juniper.id, 50, 10)
    opening = snap(db, org, OPENING)

    _doc, line, *_ = _sync_purchase(sync_world, db, "80", on=date(2026, 11, 10), description="Orris")
    assert _record(client, line.id, [_row("Orris", 4, 80)]).status_code == 200
    execution, (step,) = workflow(db, org.id, [[{"name": "Gin", "unit": "bottles"}]])
    complete(client, execution, step, [(juniper, 6, "kg")], [{"name": "Gin", "quantity": 10, "unit": "bottles"}])
    (gin,) = produced_lots(db, org.id, step.id)
    InventoryRepository(db).consume_final_product_fifo(org.id, "Gin", "4")  # sold: 4 x $3
    sample(db, org, gin, 1)
    waste(client, gin, 1)
    InventoryRepository(db).set_inventory_item_quantity(gin.id, org.id, "3")  # counted: one fewer
    closing = snap(db, org, CLOSING)

    body = bridge(client, opening, closing)

    roll = body["roll_forward"]
    assert (D(roll["opening"]), D(roll["purchases"]), D(roll["closing"]), D(roll["cost_left"])) == (
        D("50"),
        D("80"),
        D("109"),
        D("21"),
    )
    parts = {k: D(v) for k, v in roll["components"].items()}
    assert parts == {
        "cogs": D("12"),
        "wastage": D("3"),
        "samples": D("3"),
        "variance": D("3"),
        "production_loss": D("0"),
        "estimate_changes": D("0"),
        "other": D("0"),
    }
    assert sum(parts.values()) == D(roll["cost_left"]) == D(roll["opening"]) + D(roll["purchases"]) - D(roll["closing"])
    assert roll["balanced"] is True and D(roll["rounding"]) == 0


def test_ac141_cost_used_after_a_batchs_last_output_is_a_production_loss(plain, db):
    org, client = plain
    juniper = lot(db, org.id, "Juniper", 10, "kg")
    price(db, org.id, juniper.id, 50, 10)
    opening = snap(db, org, OPENING)

    execution, (first, last) = workflow(db, org.id, [[{"name": "Mash", "unit": "L"}], []])
    complete(client, execution, first, [(juniper, 2, "kg")], [{"name": "Mash", "quantity": 2, "unit": "L"}])
    complete(client, execution, last, [(juniper, 3, "kg")], [])  # $15 used, nothing made: the batch ends
    closing = snap(db, org, CLOSING)

    roll = bridge(client, opening, closing)["roll_forward"]

    assert (D(roll["opening"]), D(roll["closing"]), D(roll["cost_left"])) == (D("50"), D("35"), D("15"))
    assert {k: D(v) for k, v in roll["components"].items() if D(v)} == {"production_loss": D("15")}
    assert D(client.get(f"{API}/stock-value/snapshots/{closing.id}").get_json()["total"]) == D("35")


def _estimate_world(db, org):
    one = lot(db, org.id, "Orris", 1, "kg")
    price(db, org.id, one.id, 30, 1)
    two = lot(db, org.id, "Orris", 2, "kg")  # estimated at $30/kg: $60
    opening = snap(db, org, OPENING)
    price(db, org.id, two.id, 50, 2)  # found to have cost $25/kg
    closing = snap(db, org, CLOSING)
    return two, opening, closing


def test_ac142_a_cost_found_later_is_an_estimate_change(plain, db):
    org, client = plain
    _two, opening, closing = _estimate_world(db, org)

    roll = bridge(client, opening, closing)["roll_forward"]

    assert (D(roll["opening"]), D(roll["closing"]), D(roll["cost_left"])) == (D("90"), D("80"), D("10"))
    assert D(roll["components"]["estimate_changes"]) == D("10")
    assert D(roll["estimate_detail"]["revaluation"]) == D("-10")  # stock value fell by 2 x (30 - 25)
    assert D(roll["estimate_detail"]["added_other"]) == D("0")
    assert roll["balanced"] is True


def test_ac143_a_closed_month_does_not_move_and_changes_since_close_show_the_difference(plain, db):
    org, client = plain
    two, opening, closing = _estimate_world(db, org)
    before = client.get(f"{API}/stock-value/snapshots/{closing.id}").get_json()
    roll_before = bridge(client, opening, closing)["roll_forward"]

    price(db, org.id, two.id, 100, 2)  # a late correction: $50/kg
    lot(db, org.id, "Elderflower", 3, "kg")

    after = client.get(f"{API}/stock-value/snapshots/{closing.id}").get_json()
    assert {k: after[k] for k in ("total", "categories", "split", "unknown_lots")} == {
        k: before[k] for k in ("total", "categories", "split", "unknown_lots")
    }
    assert after["lines"] == before["lines"]
    detail = bridge(client, opening, closing)
    assert detail["roll_forward"] == roll_before
    changes = after["changes_since_close"]
    assert (D(changes["total_then"]), D(changes["total_now"]), D(changes["delta"])) == (D("80"), D("130"), D("50"))
    assert D(detail["changes_since_close"]["delta"]) == D("50")


# --- AC144 / AC145: states, permissions, isolation -----------------------------------------------------


def test_ac144_needs_two_snapshots_then_without_xero_the_roll_forward_still_shows(plain, db):
    org, client = plain
    lot(db, org.id, "Juniper", 4, "kg")
    first = snap(db, org, OPENING)
    body = client.get(f"{API}/bridge").get_json()
    assert body["state"] == "needs_snapshots" and body["snapshots"] == 1

    second = snap(db, org, CLOSING)
    body = client.get(f"{API}/bridge").get_json()  # the latest two by default
    assert body["state"] == "ok" and (body["from"]["id"], body["to"]["id"]) == (str(first.id), str(second.id))
    assert body["xero"]["state"] == "not_connected" and body["tie_out"] is None
    assert body["roll_forward"]["balanced"] is True
    assert body["duty"]["tracked"] is False and body["duty"]["xero_total"] is None
    assert bridge(client, second, first, expect=400)["error"]


def test_ac145_permissions_isolation_and_a_token_without_the_report_scope(world, db, flask_app, monkeypatch):
    org, client, fake = world["org"], world["client"], world["fake"]
    first, second = snap(db, org, OPENING), snap(db, org, CLOSING)

    production = user_client(db, flask_app, org, role=UserRole.PRODUCTION)
    assert production.get(f"{API}/bridge").status_code == 403
    viewer = user_client(db, flask_app, org, permissions=["costs.view", "inventory.view"])
    assert viewer.get(f"{API}/bridge").status_code == 200

    other_org = new_org(db)
    try:
        other = user_client(db, flask_app, other_org)
        assert other.get(f"{API}/bridge?from={first.id}&to={second.id}").status_code == 404
        assert client.get(f"{API}/bridge?from={uuid4()}&to={second.id}").status_code == 404
        assert client.get(f"{API}/bridge?from=not-a-uuid&to={second.id}").status_code == 404
    finally:
        purge(db, other_org)

    connect(db, org.id, scopes=FULL_SCOPES)  # reconnected without the P&L permission
    assert client.get(f"{API}/bridge").get_json()["xero"]["state"] == "needs_reconnect"
    assert not [c for c in fake.calls if c[0] == "profit_and_loss"]

    connect(db, org.id, scopes=PL_SCOPES)

    def boom(*_args):
        raise RuntimeError("SELECT secret FROM somewhere")

    install_pl(monkeypatch, fake, boom)
    failed = client.get(f"{API}/bridge").get_json()
    assert failed["xero"]["state"] == "failed" and failed["xero"]["ref"]
    assert "SELECT" not in str(failed) and failed["roll_forward"]["balanced"] is True
