"""Packs on the Purchases record dialog: a bought case is recorded with what it holds.

Purchases come in through the real 8.1b sync seam (FakeXero), the way the other 8.1c tests do;
recording goes through the HTTP API. Roadmap 8.1, multipacks (spec .agents/specs/live-cogs-packs.md).
"""

# ruff: noqa: F811 -- flask_app is re-exported as a fixture and used as a test argument

from __future__ import annotations

from decimal import Decimal

from app.core.db.models.inventory_item import InventoryItem
from tests.costing_helpers import lot_cost, user_client
from tests.test_compliant_routes import flask_app  # noqa: F401 -- fixture re-export
from tests.test_costing_allocations import _assert_success, _record, _row, _sync_purchase, world  # noqa: F401
from tests.test_costing_rules import _card, _purchase, _rule

D = Decimal
CASE = {"count": 24, "size": "200", "size_unit": "ml"}


def _lot(db, org_id, name):
    db.expire_all()
    return db.query(InventoryItem).filter(InventoryItem.org_id == org_id, InventoryItem.name == name).one()


def test_record_stores_the_pack_and_the_lot_prices_per_bottle(flask_app, world, db):
    org = world["org"]
    _, purchase_line, _, _ = _sync_purchase(world, db, "96", description="Tonic", payee="Drinks Wholesale")
    client = user_client(db, flask_app, org)

    response = _record(client, purchase_line.id, [_row("Tonic 24 x 200mL", 2, 96, unit="cases", pack="24 × 200 mL")])
    _assert_success(response)

    tonic = _lot(db, org.id, "Tonic 24 x 200mL")
    assert tonic.extra_data["pack"] == CASE
    split = lot_cost(db, org.id, tonic.id)["pack_breakdown"]
    assert D(split["per_container"]) == D("2") and D(split["per_litre"]) == D("10")


def test_record_without_a_pack_leaves_the_lot_as_it_was(flask_app, world, db):
    org = world["org"]
    _, purchase_line, _, _ = _sync_purchase(world, db, "90", payee="Juniper Merchants")
    client = user_client(db, flask_app, org)
    _assert_success(_record(client, purchase_line.id, [_row("Juniper Berries", 2, 90)]))
    assert "pack" not in (_lot(db, org.id, "Juniper Berries").extra_data or {})


def test_record_refuses_an_unreadable_pack_and_records_nothing(flask_app, world, db):
    org = world["org"]
    _, purchase_line, _, _ = _sync_purchase(world, db, "96", payee="Drinks Wholesale")
    client = user_client(db, flask_app, org)

    response = _record(client, purchase_line.id, [_row("Tonic", 2, 96, unit="cases", pack="a few")])
    assert response.status_code == 400 and "Pack size" in response.get_json()["error"]
    assert db.query(InventoryItem).filter(InventoryItem.org_id == org.id).count() == 0


def test_prefill_offers_a_pack_read_from_the_rule_name_for_counted_stock_only(flask_app, world, db):
    client = user_client(db, flask_app, world["org"])
    template = [
        {"name": name, "inventory_type": "raw_material", "unit": unit, "quantity_mode": "ask", "share": "rest"}
        for name, unit in (("Tonic 24 x 200ml", "cases"),)
    ]
    assert _rule(client, payee_pattern="Drinks Wholesale", template=template).status_code in (200, 201)
    card = _card(client, _purchase(world, db, "96", payee="Drinks Wholesale"))
    (row,) = card["prefill"]["rows"]
    assert row["pack"] == "24 × 200 mL", "offered to confirm; nothing is stored until it is recorded"

    kilos = [
        {
            "name": "Juniper 25 kg",
            "inventory_type": "raw_material",
            "unit": "kg",
            "quantity_mode": "ask",
            "share": "rest",
        }
    ]
    assert _rule(client, payee_pattern="Spice Co", template=kilos).status_code in (200, 201)
    (spice,) = _card(client, _purchase(world, db, "50", payee="Spice Co"))["prefill"]["rows"]
    assert spice["pack"] is None, "a lot held in kg needs no pack to be used in g"


def test_prefill_carries_the_last_lots_own_pack_over_the_name(flask_app, world, db):
    org = world["org"]
    client = user_client(db, flask_app, org)
    first = _purchase(world, db, "96", payee="Drinks Wholesale", description="Tonic")
    _assert_success(_record(client, first, [_row("Tonic 24 x 200mL", 2, 96, unit="cases", pack="6 x 700 mL")]))
    again = _card(client, _purchase(world, db, "48", payee="Drinks Wholesale", description="Tonic"))
    assert again["prefill"]["source"] == "last_time"
    (row,) = again["prefill"]["rows"]
    assert row["pack"] == "6 × 700 mL", "last time's lot carried its own pack, which wins over its name"
