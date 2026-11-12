"""Live-cogs 8.1f-3a: material price history (spec build contract)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app.core.db.models.user import UserRole
from app.features.costing.models import PurchaseAllocation, PurchaseDocument, PurchaseLine
from tests.costing_helpers import lot, new_org, price, purge, user_client
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
    assert month["unconverted"] == 1


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
