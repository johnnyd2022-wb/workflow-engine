"""Live-cogs 8.1f-3a: material price history (spec build contract)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import pytest

from app.core.db.models.user import UserRole
from app.features.costing import price_history
from app.features.costing.models import LotCostEntry, PurchaseAllocation, PurchaseDocument, PurchaseLine
from tests.costing_helpers import flows, lot, new_org, price, purge, user_client
from tests.test_compliant_routes import flask_app  # noqa: F401 -- fixture re-export
from tests.test_costing_allocations import _record, _row, _sync_purchase, connect
from tests.test_costing_purchases import FakeXero

API = "/api/core/costing"
D = Decimal


@pytest.fixture
def world(db, flask_app, monkeypatch):  # noqa: F811
    org = new_org(db)
    connect(db, org.id)
    fake = FakeXero()
    fake.install(monkeypatch)
    client = user_client(db, flask_app, org)
    yield {"org": org, "client": client, "sync": {"org": org, "fake": fake}}
    purge(db, org)


def _purchase(sync_world, db, client, amount, quantity, *, name="Juniper", on=date(2026, 11, 10), unit="kg"):
    doc, line, *_ = _sync_purchase(
        sync_world, db, amount=str(amount), on=on, description=f"{name} purchase", payee=f"{name} supplier"
    )
    response = _record(client, line.id, [_row(name, quantity, amount, unit=unit)])
    assert response.status_code == 200, response.get_json()
    db.expire_all()
    from app.core.db.models.inventory_item import InventoryItem

    item = (
        db.query(InventoryItem)
        .filter(InventoryItem.org_id == sync_world["org"].id, InventoryItem.name == name)
        .order_by(InventoryItem.created_at.desc())
        .first()
    )
    return doc, line, item


def _history(client, name="Juniper", **params):
    query = "&".join(f"{'from' if key == 'from_' else key}={value}" for key, value in params.items())
    suffix = f"?{query}" if query else ""
    return client.get(f"{API}/materials/{name}/history{suffix}")


def _reverse_price_facts(monkeypatch):
    load_facts = price_history._facts

    def reversed_facts(*args):
        allocations, entries = load_facts(*args)
        return list(reversed(allocations)), list(reversed(entries))

    monkeypatch.setattr(price_history, "_facts", reversed_facts)


def test_ac105_weighted_average_across_two_purchases(world, db):
    client = world["client"]
    _purchase(world["sync"], db, client, 20, 2)
    _purchase(world["sync"], db, client, 60, 3, on=date(2026, 11, 20))

    response = _history(client, from_="2026-11", to="2026-11")
    assert response.status_code == 200, response.get_json()
    month = response.get_json()["months"][0]
    assert (month["month"], month["unit"], D(month["average_unit_cost"])) == (
        "2026-11",
        "kg",
        D("16"),
    )
    assert D(month["priced_quantity"]) == D("5")
    assert month["purchases"] == 2
    assert D(month["min_unit_price"]) == D("10")
    assert D(month["max_unit_price"]) == D("20")
    assert response.get_json()["latest"]["date"] >= "2026-11-20"


def test_ac106_refund_reduces_month_amount_only(world, db):
    org, client = world["org"], world["client"]
    _doc, line, item = _purchase(world["sync"], db, client, 100, 10)
    doc = db.get(PurchaseDocument, line.document_id)
    refund_doc = PurchaseDocument(
        **{
            column.name: getattr(doc, column.name)
            for column in PurchaseDocument.__table__.columns
            if column.name not in ("id", "external_id", "kind", "created_at", "updated_at")
        },
        external_id=f"refund-{line.id}",
        kind="refund",
    )
    db.add(refund_doc)
    db.flush()
    refund_line = PurchaseLine(
        **{
            column.name: getattr(line, column.name)
            for column in PurchaseLine.__table__.columns
            if column.name
            not in ("id", "document_id", "line_key", "fingerprint", "amount_ex_tax", "created_at", "updated_at")
        },
        document_id=refund_doc.id,
        line_key=f"refund-{line.id}",
        fingerprint=f"refund-{line.id}",
        amount_ex_tax=D("-20"),
    )
    db.add(refund_line)
    db.flush()
    db.add(
        PurchaseAllocation(
            org_id=org.id,
            purchase_line_id=refund_line.id,
            inventory_item_id=item.id,
            cost_flow_id=None,
            amount=D("-20"),
            quantity=D("0"),
            status="active",
        )
    )
    db.commit()
    month = _history(client, from_="2026-11", to="2026-11").get_json()["months"][0]
    assert D(month["amount"]) == D("80")
    assert D(month["priced_quantity"]) == D("10")
    assert month["purchases"] == 1


def test_ac106_manual_and_free_entries_are_history_prices(world, db):
    org = world["org"]
    manual = lot(db, org.id, "Kawakawa", 2, "kg")
    free = lot(db, org.id, "Kawakawa", 3, "kg")
    manual_entry = price(db, org.id, manual.id, 30, 2)
    free_entry = price(db, org.id, free.id, 0, 3, kind="free")
    manual_entry.created_at = free_entry.created_at = datetime(2026, 11, 8, tzinfo=UTC)
    db.commit()
    month = _history(world["client"], "Kawakawa", **{"from": "2026-11", "to": "2026-11"}).get_json()["months"][0]
    assert D(month["amount"]) == D("30")
    assert D(month["priced_quantity"]) == D("5")
    assert D(month["average_unit_cost"]) == D("6")


def test_ac55_whole_lot_and_flow_prices_use_engine_precedence(world, db):
    org = world["org"]
    item = lot(db, org.id, "Cubeb", 2, "kg")
    whole = price(db, org.id, item.id, 80, 2)
    flow = next(flow for flow in flows(db, org.id, item.id, kind="created"))
    specific = price(db, org.id, item.id, 90, 2, cost_flow_id=flow.id)
    whole.created_at = datetime(2026, 11, 2, tzinfo=UTC)
    specific.created_at = datetime(2026, 11, 3, tzinfo=UTC)

    month = _history(world["client"], "Cubeb", **{"from": "2026-11", "to": "2026-11"}).get_json()["months"][0]
    assert D(month["amount"]) == D("90")
    assert D(month["priced_quantity"]) == D("2")
    assert D(month["average_unit_cost"]) == D("45")


def test_ac55_whole_lot_price_only_fills_unpriced_direct_quantity(world, db):
    org = world["org"]
    item = lot(db, org.id, "Grains of Paradise", 2, "kg")
    flow = next(flow for flow in flows(db, org.id, item.id, kind="created"))
    specific = price(db, org.id, item.id, 90, 2, cost_flow_id=flow.id)
    from app.core.db.repositories.inventory_repo import InventoryRepository

    InventoryRepository(db).add_quantity_to_inventory_item(item.id, org.id, "3")
    db.flush()
    whole = price(db, org.id, item.id, 60, 3)
    specific.created_at = datetime(2026, 11, 3, tzinfo=UTC)
    whole.created_at = datetime(2026, 11, 4, tzinfo=UTC)

    month = _history(world["client"], "Grains of Paradise", **{"from": "2026-11", "to": "2026-11"}).get_json()[
        "months"
    ][0]
    assert D(month["amount"]) == D("150")
    assert D(month["priced_quantity"]) == D("5")
    assert D(month["average_unit_cost"]) == D("30")


def test_ac107_converts_compatible_units_and_counts_unconvertible(world, db):
    org, client = world["org"], world["client"]
    kg = lot(db, org.id, "Salt", 1, "kg")
    lot(db, org.id, "Salt", 1, "kg")  # make kg the most common unit
    grams = lot(db, org.id, "Salt", 500, "g")
    strange = lot(db, org.id, "Salt", 2, "bottles")
    price(db, org.id, kg.id, 10, 1)
    price(db, org.id, grams.id, 2.5, 500)
    price(db, org.id, strange.id, 6, 2)
    response = _history(client, "Salt", **{"from": "2026-11", "to": "2026-11"})
    assert response.status_code == 200
    month = response.get_json()["months"][0]
    assert month["unit"] == "kg"
    assert D(month["priced_quantity"]) == D("1.5")
    assert D(month["amount"]) == D("12.5")
    assert D(month["average_unit_cost"]) == D("8.333333")
    assert D(month["min_unit_price"]) == D("5")
    assert D(month["max_unit_price"]) == D("10")
    assert month["unconverted"] == 1


def test_ac107_unconverted_counts_prices_not_refunds(world, db):
    org, client = world["org"], world["client"]
    lot(db, org.id, "Bottle Refund", 1, "kg")
    lot(db, org.id, "Bottle Refund", 1, "kg")
    doc, line, item = _purchase(world["sync"], db, client, 6, 2, name="Bottle Refund", unit="bottles")
    refund_doc = PurchaseDocument(
        **{
            column.name: getattr(doc, column.name)
            for column in PurchaseDocument.__table__.columns
            if column.name not in ("id", "external_id", "kind", "created_at", "updated_at")
        },
        external_id=f"refund-{line.id}",
        kind="refund",
    )
    db.add(refund_doc)
    db.flush()
    refund_line = PurchaseLine(
        **{
            column.name: getattr(line, column.name)
            for column in PurchaseLine.__table__.columns
            if column.name
            not in ("id", "document_id", "line_key", "fingerprint", "amount_ex_tax", "created_at", "updated_at")
        },
        document_id=refund_doc.id,
        line_key=f"refund-{line.id}",
        fingerprint=f"refund-{line.id}",
        amount_ex_tax=D("-1"),
    )
    db.add(refund_line)
    db.flush()
    db.add(
        PurchaseAllocation(
            org_id=org.id,
            purchase_line_id=refund_line.id,
            inventory_item_id=item.id,
            cost_flow_id=None,
            amount=D("-1"),
            quantity=D("0"),
            status="active",
        )
    )
    db.commit()
    month = _history(client, "Bottle Refund", **{"from": "2026-11", "to": "2026-11"}).get_json()["months"][0]
    assert month["unconverted"] == 1
    # r2: the bottle refund belongs to the bottle price left out, so it can't lower the kg figures
    assert D(month["amount"]) == D("0") and month["average_unit_cost"] is None


@pytest.mark.parametrize(
    "instant,expected_month,expected_date",
    [
        (datetime(2026, 7, 31, 12, 30, tzinfo=UTC), "2026-08", "2026-08-01"),  # NZST
        (datetime(2026, 11, 30, 11, 30, tzinfo=UTC), "2026-12", "2026-12-01"),  # NZDT
    ],
)
def test_ac106_manual_timestamps_use_new_zealand_calendar(world, db, instant, expected_month, expected_date):
    org = world["org"]
    item = lot(db, org.id, "Boundary Herb", 1, "kg")
    entry = price(db, org.id, item.id, 9, 1)
    entry.created_at = instant
    db.commit()

    response = _history(world["client"], "Boundary Herb", **{"from": expected_month, "to": expected_month})
    assert response.status_code == 200
    assert response.get_json()["months"][0]["month"] == expected_month
    assert response.get_json()["latest"]["date"].startswith(expected_date)


def test_ac108_latest_manual_fact_uses_timestamp_within_same_day(world, db):
    org = world["org"]
    item = lot(db, org.id, "Same Day", 2, "kg")
    older = price(db, org.id, item.id, 10, 1)
    created = next(flow for flow in flows(db, org.id, item.id, kind="created"))
    newer = price(db, org.id, item.id, 30, 1, cost_flow_id=created.id)
    older.id, newer.id = UUID(int=2), UUID(int=1)  # UUID ordering contradicts timestamp ordering.
    older.created_at = datetime(2026, 11, 10, 1, tzinfo=UTC)
    newer.created_at = datetime(2026, 11, 10, 2, tzinfo=UTC)
    db.commit()

    latest = _history(world["client"], "Same Day", **{"from": "2026-11", "to": "2026-11"}).get_json()["latest"]
    assert latest["unit_price"] == "30.000000"
    picker = world["client"].get(f"{API}/materials").get_json()["materials"]
    assert picker[0]["latest_unit_price"] == "30.000000"


def test_ac108_date_only_purchase_sorts_after_timed_fact_on_same_day(world, db):
    doc, _line, _purchase_item = _purchase(
        world["sync"], db, world["client"], 20, 2, name="Date Tie", on=date(2026, 11, 10)
    )
    manual_item = lot(db, world["org"].id, "Date Tie", 2, "kg")
    manual = price(db, world["org"].id, manual_item.id, 30, 2)
    manual.created_at = datetime(2026, 11, 10, 10, tzinfo=UTC)
    db.commit()

    latest = _history(world["client"], "Date Tie", **{"from": "2026-11", "to": "2026-11"}).get_json()["latest"]
    assert doc.document_date == date(2026, 11, 10)
    assert latest["source"] == "purchase"
    assert latest["unit_price"] == "10.000000"


def test_ac108_month_bounds_and_unknown_material(world, db):
    org, client = world["org"], world["client"]
    item = lot(db, org.id, "Dried Citrus", 1, "kg")
    entry = price(db, org.id, item.id, 4, 1)
    entry.created_at = datetime(2025, 1, 15, tzinfo=UTC)
    db.commit()
    assert _history(client, "Dried%20Citrus", **{"from": "2025-01", "to": "2025-01"}).status_code == 200
    outside = _history(client, "Dried%20Citrus", **{"from": "2025-02", "to": "2025-02"}).get_json()
    assert outside["months"] == []
    assert outside["latest"]["date"].startswith("2025-01-15")
    assert _history(client, "Missing", **{"from": "2025-01", "to": "2025-01"}).status_code == 404
    assert _history(client, "Dried%20Citrus", **{"from": "2023-01", "to": "2026-01"}).status_code == 400
    for params in (
        {"from": "2026-1", "to": "2026-02"},
        {"from": "2026-01"},
        {"to": "2026-01"},
        {"from": "2026-02", "to": "2026-01"},
        {"from": "2023-01", "to": "2026-01"},
    ):
        assert _history(client, "Dried%20Citrus", **params).status_code == 400
    assert _history(client, "Dried%20Citrus", **{"from": "2024-01", "to": "2026-12"}).status_code == 200
    default = _history(client, "Dried%20Citrus").get_json()
    default_start = date.fromisoformat(f"{default['from']}-01")
    default_end = date.fromisoformat(f"{default['to']}-01")
    assert (default_end.year - default_start.year) * 12 + default_end.month - default_start.month + 1 == 12


def test_ac109_org_isolation_production_role_and_material_picker(world, db, flask_app):  # noqa: F811
    org, client = world["org"], world["client"]
    item = lot(db, org.id, "Juniper", 1, "kg")
    price(db, org.id, item.id, 7, 1)
    unpriced = lot(db, org.id, "Unpriced", 1, "kg")
    other = new_org(db)
    try:
        intruder = user_client(db, flask_app, other)
        assert _history(intruder, "Juniper", **{"from": "2026-11", "to": "2026-11"}).status_code == 404
        assert intruder.get(f"{API}/materials").get_json()["materials"] == []
    finally:
        purge(db, other)
    production = user_client(db, flask_app, org, role=UserRole.PRODUCTION)
    assert _history(production, "Juniper").status_code == 403
    assert production.get(f"{API}/materials").status_code == 403
    listed = client.get(f"{API}/materials")
    assert listed.status_code == 200
    assert listed.get_json()["materials"] == [
        {
            "name": "Juniper",
            "unit": "kg",
            "latest_unit_price": "7.000000",
            "latest_date": listed.get_json()["materials"][0]["latest_date"],
        }
    ]
    assert unpriced.name == "Unpriced"


def test_r2_a_zero_dollar_purchase_is_a_price(world, db):
    _purchase(world["sync"], db, world["client"], 0, 5, name="Gifted Juniper")
    body = _history(world["client"], "Gifted Juniper", **{"from": "2026-11", "to": "2026-11"}).get_json()
    (month,) = body["months"]
    assert D(month["average_unit_cost"]) == D("0") and D(month["priced_quantity"]) == D("5")
    assert month["purchases"] == 1
    assert D(body["latest"]["unit_price"]) == D("0")
    names = [m["name"] for m in world["client"].get(f"{API}/materials").get_json()["materials"]]
    assert "Gifted Juniper" in names


def test_r2_identical_timestamps_pick_the_same_latest_in_history_and_picker(world, db, monkeypatch):
    org = world["org"]
    item = lot(db, org.id, "Tie Break", 2, "kg")
    first = price(db, org.id, item.id, 10, 1)
    created = next(flow for flow in flows(db, org.id, item.id, kind="created"))
    second = price(db, org.id, item.id, 30, 1, cost_flow_id=created.id)
    first.id, second.id = UUID(int=1), UUID(int=9)
    first.created_at = second.created_at = datetime(2026, 11, 10, 1, tzinfo=UTC)
    db.commit()
    _reverse_price_facts(monkeypatch)
    history = _history(world["client"], "Tie Break", **{"from": "2026-11", "to": "2026-11"}).get_json()["latest"]
    picker = world["client"].get(f"{API}/materials").get_json()["materials"][0]
    assert history["unit_price"] == "30.000000"
    assert picker["latest_unit_price"] == "30.000000"


def test_r2_flow_cap_scales_purchase_allocation_and_manual_entry_together(world, db):
    _doc, line, item = _purchase(world["sync"], db, world["client"], 20, 2, name="Capped Herb")
    allocation = (
        db.query(PurchaseAllocation)
        .filter(PurchaseAllocation.org_id == world["org"].id, PurchaseAllocation.purchase_line_id == line.id)
        .one()
    )
    manual = LotCostEntry(
        org_id=world["org"].id,
        inventory_item_id=item.id,
        cost_flow_id=allocation.cost_flow_id,
        kind="manual",
        amount=D("30"),
        quantity=D("2"),
        created_at=datetime(2026, 11, 10, 12, tzinfo=UTC),
    )
    db.add(manual)
    db.commit()

    response = _history(world["client"], "Capped Herb", **{"from": "2026-11", "to": "2026-11"})
    assert response.status_code == 200, response.get_json()
    month = response.get_json()["months"][0]
    assert D(month["amount"]) == D("25")
    assert D(month["priced_quantity"]) == D("2")
    assert D(month["average_unit_cost"]) == D("12.5")
    assert month["purchases"] == 1


def test_r2_same_document_allocations_use_higher_allocation_id_for_latest(world, db, monkeypatch):
    doc, line, *_ = _sync_purchase(
        world["sync"], db, amount="40", on=date(2026, 11, 10), description="Split Herb purchase", payee="Split supplier"
    )
    response = _record(
        world["client"],
        line.id,
        [_row("Split Herb", 1, 10), _row("Split Herb", 1, 30)],
    )
    assert response.status_code == 200, response.get_json()
    allocations = (
        db.query(PurchaseAllocation)
        .filter(PurchaseAllocation.org_id == world["org"].id, PurchaseAllocation.purchase_line_id == line.id)
        .all()
    )
    assert len(allocations) == 2
    lower_price_allocation = next(allocation for allocation in allocations if D(allocation.amount) == D("10"))
    higher_price_allocation = next(allocation for allocation in allocations if D(allocation.amount) == D("30"))
    lower_price_allocation.id, higher_price_allocation.id = UUID(int=1), UUID(int=9)
    db.commit()
    _reverse_price_facts(monkeypatch)

    history = _history(world["client"], "Split Herb", **{"from": "2026-11", "to": "2026-11"}).get_json()
    picker = world["client"].get(f"{API}/materials").get_json()["materials"][0]
    assert doc.document_date == date(2026, 11, 10)
    assert history["latest"]["unit_price"] == "30.000000"
    assert picker["latest_unit_price"] == "30.000000"


def test_r4_an_unconvertible_purchase_still_counts_and_lists(world, db):
    org, client = world["org"], world["client"]
    lot(db, org.id, "Odd Unit", 1, "kg")
    lot(db, org.id, "Odd Unit", 1, "kg")
    _purchase(world["sync"], db, client, 6, 2, name="Odd Unit", unit="bottles")
    (month,) = _history(client, "Odd Unit", **{"from": "2026-11", "to": "2026-11"}).get_json()["months"]
    assert (month["unconverted"], month["purchases"]) == (1, 1)
    row = next(m for m in client.get(f"{API}/materials").get_json()["materials"] if m["name"] == "Odd Unit")
    assert row["latest_unit_price"] is None


def test_r4_picker_ignores_a_whole_lot_price_the_engine_displaces(world, db):
    org = world["org"]
    item = lot(db, org.id, "Displaced", 2, "kg")
    created = next(flow for flow in flows(db, org.id, item.id, kind="created"))
    flow_price = price(db, org.id, item.id, 90, 2, cost_flow_id=created.id)
    whole = price(db, org.id, item.id, 80, 2)
    flow_price.created_at = datetime(2026, 11, 10, 1, tzinfo=UTC)
    whole.created_at = datetime(2026, 11, 10, 2, tzinfo=UTC)  # newer, but covers nothing unpriced
    db.commit()
    history = _history(world["client"], "Displaced", **{"from": "2026-11", "to": "2026-11"}).get_json()["latest"]
    picker = next(
        m for m in world["client"].get(f"{API}/materials").get_json()["materials"] if m["name"] == "Displaced"
    )
    assert history["unit_price"] == picker["latest_unit_price"] == "45.000000"


def test_r5_a_lot_too_long_to_cost_is_unknown_not_an_error(world, db, monkeypatch):
    from app.features.costing import engine as engine_module

    org = world["org"]
    item = lot(db, org.id, "Deep History", 2, "kg")
    price(db, org.id, item.id, 10, 2)
    db.commit()

    def too_large(self, key):
        raise engine_module.TooLargeError("over budget")

    monkeypatch.setattr(engine_module.CostEngine, "_solve", too_large)
    response = _history(world["client"], "Deep History", **{"from": "2026-11", "to": "2026-11"})
    assert response.status_code == 200, response.get_json()
    (row,) = response.get_json()["lots"]
    assert (row["status"], row["unit_cost"]) == ("unknown", None)


def test_r6_over_the_real_engine_budget_both_endpoints_answer(world, db, monkeypatch):
    """Review r6: with the engine's actual work budget exhausted, history says it's too large and the
    picker still lists the material, rather than either returning a 500."""
    from app.features.costing import engine as engine_module

    org = world["org"]
    item = lot(db, org.id, "Huge History", 2, "kg")
    price(db, org.id, item.id, 10, 2)
    db.commit()
    monkeypatch.setattr(engine_module, "MAX_WORK", 0)
    response = _history(world["client"], "Huge History", **{"from": "2026-11", "to": "2026-11"})
    assert response.status_code == 200, response.get_json()
    body = response.get_json()
    assert body["too_large"] is True and body["months"] == []
    assert [(r["status"], r["unit_cost"]) for r in body["lots"]] == [("unknown", None)]
    picker = world["client"].get(f"{API}/materials")
    assert picker.status_code == 200
    row = next(m for m in picker.get_json()["materials"] if m["name"] == "Huge History")
    assert row["latest_unit_price"] is None


def test_r8_history_queries_stay_flat_as_produced_lots_grow(world, db):
    """Review: each produced lot comes from its own batch; with the engine's bulk priming (!698) the
    history's query count doesn't grow with the number of batches."""
    from sqlalchemy import event

    from tests.costing_helpers import complete, workflow

    org, client = world["org"], world["client"]
    spirit = lot(db, org.id, "Base spirit", 100, "L")
    price(db, org.id, spirit.id, 1000, 100)

    def batches(n):
        for _ in range(n):
            execution, (step,) = workflow(db, org.id, [[{"name": "Batch Gin", "unit": "bottles"}]])
            complete(
                client, execution, step, [(spirit, 1, "L")], [{"name": "Batch Gin", "quantity": 1, "unit": "bottles"}]
            )

    def count():
        statements = []
        engine = getattr(db.get_bind(), "engine", db.get_bind())
        listener = lambda *_a: statements.append(1)  # noqa: E731
        event.listen(engine, "before_cursor_execute", listener)
        try:
            assert _history(client, "Batch Gin").status_code == 200
        finally:
            event.remove(engine, "before_cursor_execute", listener)
        return len(statements)

    batches(2)
    few = count()
    batches(6)
    many = count()
    assert many <= few + 3, (few, many)
