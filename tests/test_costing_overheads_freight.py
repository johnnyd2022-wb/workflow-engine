"""Live-cogs 8.1h: freight as landed cost (spec .agents/specs/live-cogs-overheads.md, "Freight").

Written before the implementation. Purchases arrive through the real 8.1b sync seam (fake Xero);
recording goes through the real HTTP actions.
"""

# ruff: noqa: F811 -- flask_app / world are re-exported fixtures used as test arguments

from __future__ import annotations

from uuid import uuid4

import pytest

from app.features.costing.models import PurchaseDocument, PurchaseLine
from tests.costing_helpers import D, lot_cost, new_org, purge, user_client
from tests.test_compliant_routes import flask_app  # noqa: F401 -- fixture re-export
from tests.test_costing_allocations import PURCHASE_DATE, _record, _row, _set_start_date
from tests.test_costing_purchases import FakeXero, connect, documents, line, live_lines, sync, txn

API = "/api/core/costing"


@pytest.fixture
def world(db, flask_app, monkeypatch):
    org = new_org(db)
    connect(db, org.id)
    fake = FakeXero().install(monkeypatch)
    client = user_client(db, flask_app, org)
    yield {"org": org, "fake": fake, "client": client}
    purge(db, org)


def _bill(world, db, lines, *, payee="Botanical Supply Co"):
    """One Xero spend transaction with ``lines`` = [(account_code, amount, description)], synced.
    Returns its purchase lines in order."""
    org, fake = world["org"], world["fake"]
    _set_start_date(db, org.id)
    txn_id = str(uuid4())
    fake.transactions = [
        txn(
            [line(code, amount, description=description) for code, amount, description in lines],
            txn_id=txn_id,
            payee=payee,
            on=PURCHASE_DATE,
            amounts="NoTax",
        )
    ]
    result = sync(db, org.id)
    assert result.success, result.errors
    doc = next(d for d in documents(db, org.id) if d.external_id == txn_id)
    _set_start_date(db, org.id)
    return live_lines(db, org.id, doc.id)


def _switch(client, on=True):
    response = client.put(f"{API}/settings", json={"include_overheads": on})
    assert response.status_code == 200, response.get_json()


def _lot_id(response):
    assert response.status_code == 200, response.get_json()
    (allocation,) = response.get_json()["allocations"]
    return allocation["inventory_item_id"]


def _unit(db, world, lot_id, field="unit_cost"):
    return D(lot_cost(db, world["org"].id, lot_id)[field])


JUNIPER_AND_CORIANDER = [
    ("310", "150", "Juniper berries"),
    ("310", "100", "Coriander seed"),
    ("331", "50", "Courier to the distillery"),  # "Freight, Postage & Courier": an overhead account
]


def test_ac_ov11_freight_spreads_by_value_within_the_purchase(world, db):
    client = world["client"]
    juniper_line, coriander_line, freight_line = _bill(world, db, JUNIPER_AND_CORIANDER)
    assert freight_line.treatment == "overhead"
    juniper = _lot_id(_record(client, juniper_line.id, [_row("Juniper berries", 2, 150)]))
    coriander = _lot_id(_record(client, coriander_line.id, [_row("Coriander seed", 1, 100)]))

    # Off: the lots cost what was recorded against them, exactly as before.
    assert _unit(db, world, juniper) == D("75.000000") and _unit(db, world, coriander) == D("100.000000")
    assert "overhead_unit_cost" not in lot_cost(db, world["org"].id, juniper)

    _switch(client)
    # $300 purchase: $250 of stock + $50 freight. Juniper 150 + 50 x 150/250 = 180 over 2 kg.
    cost = lot_cost(db, world["org"].id, juniper)
    assert D(cost["unit_cost"]) == D("90.000000") and cost["status"] == "actual"
    assert D(cost["overhead_unit_cost"]) == D("15.000000") and D(cost["materials_unit_cost"]) == D("75.000000")
    cost = lot_cost(db, world["org"].id, coriander)  # 100 + 50 x 100/250 = 120 over 1 kg
    assert D(cost["unit_cost"]) == D("120.000000")
    assert D(cost["overhead_unit_cost"]) == D("20.000000") and D(cost["materials_unit_cost"]) == D("100.000000")
    # The $50 is spread, not duplicated: 180 + 120 = 300 = 150 + 100 + 50.
    assert D("2") * _unit(db, world, juniper) + D("1") * _unit(db, world, coriander) == D("300.000000")


def test_ac_ov12_freight_boundaries(world, db):
    client = world["client"]
    org = world["org"]
    _switch(client)

    # Freight on a different purchase never reaches this one's stock.
    other = _bill(world, db, [("331", "50", "Courier, another day")], payee="Couriers Ltd")
    assert other[0].treatment == "overhead"
    stock_a, rent_a = _bill(world, db, [("310", "150", "Juniper berries"), ("330", "80", "Rent for the month")])
    juniper = _lot_id(_record(client, stock_a.id, [_row("Juniper berries", 2, 150)]))
    assert _unit(db, world, juniper) == D("75.000000")  # no freight in its own document; rent is not freight
    assert rent_a.treatment == "overhead"

    # Nothing recorded yet absorbs nothing; the freight lands on what is recorded, and re-spreads as more is.
    jun, cor, _freight = _bill(world, db, JUNIPER_AND_CORIANDER)
    first = _lot_id(_record(client, jun.id, [_row("Juniper berries", 2, 150)]))
    assert _unit(db, world, first) == D("100.000000")  # 150 + all 50 (only stock recorded so far) over 2 kg
    second = _lot_id(_record(client, cor.id, [_row("Coriander seed", 1, 100)]))
    assert _unit(db, world, first) == D("90.000000") and _unit(db, world, second) == D("120.000000")

    # A voided document's freight is gone; the lots keep what was allocated.
    db.query(PurchaseDocument).filter(PurchaseDocument.id == jun.document_id).update({"status": "voided"})
    db.commit()
    assert _unit(db, world, first) == D("75.000000")
    assert D(lot_cost(db, org.id, second)["overhead_unit_cost"]) == D("0")


def _bill_with_courier_on_a_stock_account(world, db):
    return _bill(world, db, [("310", "150", "Juniper berries"), ("310", "50", "Courier")])


def test_ac_ov13_mark_a_line_as_freight(world, db, flask_app):
    client, org = world["client"], world["org"]
    stock_line, courier = _bill_with_courier_on_a_stock_account(world, db)
    assert courier.treatment == "stock"

    # Overheads are off: there is nowhere for it to go.
    assert client.post(f"{API}/purchases/{courier.id}/freight").status_code == 400
    _switch(client)

    # A line someone has recorded stock against is not freight.
    refused = _record(client, courier.id, [_row("Courier", 1, 50)])
    assert refused.status_code == 200
    assert client.post(f"{API}/purchases/{courier.id}/freight").status_code == 400

    stock_line, courier = _bill_with_courier_on_a_stock_account(world, db)
    viewer = user_client(db, flask_app, org, permissions=["costs.view"])
    assert viewer.post(f"{API}/purchases/{courier.id}/freight").status_code == 403

    marked = client.post(f"{API}/purchases/{courier.id}/freight")
    assert marked.status_code == 200, marked.get_json()
    card = marked.get_json()
    assert card["freight"] is True and card["state"] == "not_stock"
    to_record = {c["line_id"] for c in client.get(f"{API}/purchases?tab=to_record").get_json()["cards"]}
    not_stock = {c["line_id"]: c for c in client.get(f"{API}/purchases?tab=not_stock").get_json()["cards"]}
    assert str(courier.id) not in to_record and not_stock[str(courier.id)]["freight"] is True

    juniper = _lot_id(_record(client, stock_line.id, [_row("Juniper berries", 2, 150)]))
    assert _unit(db, world, juniper) == D("100.000000")  # (150 + 50 freight) / 2 kg
    assert D(lot_cost(db, org.id, juniper)["overhead_unit_cost"]) == D("25.000000")

    # Reopen puts it back: not freight, back in To record.
    reopened = client.post(f"{API}/purchases/{courier.id}/reopen")
    assert reopened.status_code == 200 and "freight" not in reopened.get_json()
    assert reopened.get_json()["state"] == "open"
    assert _unit(db, world, juniper) == D("75.000000")
    db.expire_all()
    assert db.query(PurchaseLine).filter(PurchaseLine.id == courier.id).one().freight is False


def test_ac_ov13b_a_freight_line_cannot_be_skipped(world, db):
    client = world["client"]
    _stock, courier = _bill_with_courier_on_a_stock_account(world, db)
    _switch(client)
    assert client.post(f"{API}/purchases/{courier.id}/freight").status_code == 200
    assert client.post(f"{API}/purchases/{courier.id}/skip").status_code == 400
