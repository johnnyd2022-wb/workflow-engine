"""Live-cogs 8.1f-3c: auto-record rules use the Purchases pre-fill and record actions."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from app.core.db.models.inventory_item import InventoryItem
from app.features.costing.models import PurchaseAllocation, PurchaseDocument, PurchaseLine
from tests.costing_helpers import user_client
from tests.test_compliant_routes import flask_app  # noqa: F401 -- fixture re-export
from tests.test_costing_allocations import EARLY_START, _set_start_date, world  # noqa: F401 -- fixture re-export
from tests.test_costing_purchases import line, sync, txn

API = "/api/core/costing"
D = Decimal


def _rule(client, **body):
    body.setdefault("match_type", "exact")
    body.setdefault("treatment", "stock")
    return client.post(f"{API}/rules", json=body)


def _auto_template(**row_overrides):
    row = {
        "name": "Juniper berries",
        "inventory_type": "raw_material",
        "unit": "kg",
        "quantity_mode": "from_price",
        "unit_price": "10",
        "share": "100",
    }
    row.update(row_overrides)
    return [row]


def _sync_line(w, db, *, amount="100", payee="Auto Supplier", kind="SPEND", currency="NZD", txn_id=None):
    org = w["org"]
    _set_start_date(db, org.id, EARLY_START)
    txn_id = txn_id or str(uuid4())
    remote = txn(
        [line("310", amount, line_item_id=str(uuid4()), description="Juniper berries")],
        txn_id=txn_id,
        payee=payee,
        kind=kind,
        currency=currency,
        amounts="NoTax",
    )
    w["fake"].transactions = [remote]
    result = sync(db, org.id)
    assert result.success, result.errors
    db.expire_all()
    doc = (
        db.query(PurchaseDocument)
        .filter(PurchaseDocument.org_id == org.id, PurchaseDocument.external_id == txn_id)
        .one()
    )
    purchase_line = (
        db.query(PurchaseLine)
        .filter(
            PurchaseLine.org_id == org.id,
            PurchaseLine.document_id == doc.id,
            PurchaseLine.superseded_at.is_(None),
        )
        .one()
    )
    return doc, purchase_line


def _allocations(db, org_id, line_id):
    db.expire_all()
    return (
        db.query(PurchaseAllocation)
        .filter(
            PurchaseAllocation.org_id == org_id,
            PurchaseAllocation.purchase_line_id == line_id,
            PurchaseAllocation.status == "active",
        )
        .all()
    )


def test_auto_record_rule_validation(flask_app, world, db):  # noqa: F811
    client = user_client(db, flask_app, world["org"])
    good = _rule(client, payee_pattern="Auto Supplier", auto_record=True, template=_auto_template())
    assert good.status_code == 201, good.get_json()
    assert good.get_json()["auto_record"] is True

    invalid = [
        {"template": None},
        {"template": _auto_template(quantity_mode="ask")},
        {"template": _auto_template(ask_batch_number=True)},
        {"template": _auto_template(ask_expiry=True)},
        {"template": [{**_auto_template()[0], "share": "50"}]},
        {"template": _auto_template(), "treatment": "not_stock"},
        {"template": _auto_template(), "auto_record": "true"},
    ]
    for index, changes in enumerate(invalid):
        body = {"payee_pattern": f"Invalid Supplier {index}", "auto_record": True, **changes}
        response = _rule(client, **body)
        assert response.status_code == 400, response.get_json()
        assert response.get_json().get("error")


def test_new_matching_spend_is_recorded_from_rule_template(flask_app, world, db):  # noqa: F811
    client = user_client(db, flask_app, world["org"])
    response = _rule(
        client,
        payee_pattern="Auto Supplier",
        auto_record=True,
        template=[
            {"name": "Juniper berries", "unit": "kg", "quantity_mode": "fixed", "quantity": "3", "share": "60"},
            {"name": "Coriander", "unit": "kg", "quantity_mode": "from_price", "unit_price": "20", "share": "rest"},
        ],
    )
    assert response.status_code == 201, response.get_json()
    doc, purchase_line = _sync_line(world, db, amount="100")
    allocations = _allocations(db, world["org"].id, purchase_line.id)
    assert len(allocations) == 2
    assert {a.created_by_user_id for a in allocations} == {None}
    by_lot = {db.get(InventoryItem, a.inventory_item_id).name: (D(a.amount), D(a.quantity)) for a in allocations}
    assert by_lot == {"Juniper berries": (D("60.0000"), D("3.0000")), "Coriander": (D("40.0000"), D("2.0000"))}
    assert purchase_line.state == "recorded"
    assert doc.status == "active"
    assert _allocations(db, world["org"].id, purchase_line.id) == allocations

    card = client.get(f"{API}/purchases?tab=recorded").get_json()["cards"]
    matching = next(c for c in card if c["line_id"] == str(purchase_line.id))
    assert matching["auto_recorded"] is True

    assert sync(db, world["org"].id).success
    assert len(_allocations(db, world["org"].id, purchase_line.id)) == 2


def test_rule_does_not_touch_existing_open_line_and_excludes_refunds_and_needs_rate(flask_app, world, db):  # noqa: F811
    client = user_client(db, flask_app, world["org"])
    prior_doc, prior_line = _sync_line(world, db, amount="10", txn_id=str(uuid4()))
    assert _allocations(db, world["org"].id, prior_line.id) == []
    _rule(client, payee_pattern="Auto Supplier", auto_record=True, template=_auto_template())

    refund_doc, refund_line = _sync_line(world, db, amount="20", kind="RECEIVE")
    rate_doc, rate_line = _sync_line(world, db, amount="30", currency="AUD")
    assert _allocations(db, world["org"].id, prior_line.id) == []
    assert _allocations(db, world["org"].id, refund_line.id) == []
    assert _allocations(db, world["org"].id, rate_line.id) == []
    assert prior_doc.status == refund_doc.status == rate_doc.status == "active"
    assert prior_line.state == refund_line.state == rate_line.state == "open"
    assert rate_line.amount_ex_tax is None


def test_auto_record_failure_isolated_and_sync_succeeds(flask_app, world, db):  # noqa: F811
    client = user_client(db, flask_app, world["org"])
    _rule(
        client,
        payee_pattern="Auto Supplier",
        auto_record=True,
        template=_auto_template(unit="bottles", quantity="1.5", quantity_mode="fixed"),
    )
    _doc, purchase_line = _sync_line(world, db, amount="15")
    assert purchase_line.state == "open"
    assert _allocations(db, world["org"].id, purchase_line.id) == []


def test_historical_upsert_auto_records_and_reports_count(flask_app, world, db, caplog):  # noqa: F811
    client = user_client(db, flask_app, world["org"])
    _rule(client, payee_pattern="Auto Supplier", auto_record=True, template=_auto_template())
    world["fake"].transactions = [
        txn(
            [line("310", "50", line_item_id=str(uuid4()), description="Juniper berries")],
            payee="Auto Supplier",
            amounts="NoTax",
        )
    ]
    response = client.post(
        f"{API}/purchases/historical-run",
        json={"from": "2026-11-01", "to": "2026-11-12"},
    )
    assert response.status_code == 200, response.get_json()
    assert "'auto_recorded': 1" in caplog.text
    db.expire_all()
    purchase_line = db.query(PurchaseLine).filter(PurchaseLine.org_id == world["org"].id).one()
    allocations = _allocations(db, world["org"].id, purchase_line.id)
    assert len(allocations) == 1
    assert purchase_line.state == "recorded"
