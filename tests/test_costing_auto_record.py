"""Live-cogs 8.1f-3c: auto-record rules use the Purchases pre-fill and record actions."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from sqlalchemy import text

from app.core.db.models.inventory_item import InventoryItem
from app.core.db.repositories.inventory_repo import InventoryRepository
from app.features.costing.models import CostFlow, PurchaseAllocation, PurchaseDocument, PurchaseLine
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


def test_auto_record_requires_inventory_adjust_but_disabling_does_not(flask_app, world, db):  # noqa: F811
    admin = user_client(db, flask_app, world["org"])
    limited = user_client(db, flask_app, world["org"], permissions=["costs.manage"])
    template = _auto_template()

    denied_create = _rule(limited, payee_pattern="Limited Auto Supplier", auto_record=True, template=template)
    assert denied_create.status_code == 403, denied_create.get_json()

    created = _rule(limited, payee_pattern="Limited Manual Supplier", template=template)
    assert created.status_code == 201, created.get_json()
    enable = limited.put(f"{API}/rules/{created.get_json()['id']}", json={**created.get_json(), "auto_record": True})
    assert enable.status_code == 403, enable.get_json()

    automated = _rule(admin, payee_pattern="Disable Auto Supplier", auto_record=True, template=template)
    assert automated.status_code == 201, automated.get_json()
    preserve_auto = dict(automated.get_json())
    preserve_auto.pop("auto_record")
    preserved = limited.put(f"{API}/rules/{automated.get_json()['id']}", json=preserve_auto)
    assert preserved.status_code == 403, preserved.get_json()

    disable = limited.put(
        f"{API}/rules/{automated.get_json()['id']}",
        json={**automated.get_json(), "auto_record": False},
    )
    assert disable.status_code == 200, disable.get_json()
    assert disable.get_json()["auto_record"] is False


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


def test_auto_record_rounding_residual_is_assigned_and_line_fully_records(flask_app, world, db):  # noqa: F811
    client = user_client(db, flask_app, world["org"])
    template = [
        {
            "name": name,
            "inventory_type": "raw_material",
            "unit": "kg",
            "quantity_mode": "fixed",
            "quantity": "1",
            "share": share,
        }
        for name, share in (("A", "33.3334"), ("B", "33.3333"), ("C", "33.3333"))
    ]
    response = _rule(client, payee_pattern="Auto Supplier", auto_record=True, template=template)
    assert response.status_code == 201, response.get_json()

    _doc, purchase_line = _sync_line(world, db, amount="0.01")
    allocations = _allocations(db, world["org"].id, purchase_line.id)
    assert purchase_line.state == "recorded"
    assert sum((D(a.amount) for a in allocations), D("0")) == D("0.0100")
    assert len(allocations) == 3


def test_auto_record_unexpected_exception_logs_traceback_and_reference(flask_app, world, db, monkeypatch, caplog):  # noqa: F811
    from app.features.costing import actions

    client = user_client(db, flask_app, world["org"])
    _rule(client, payee_pattern="Auto Supplier", auto_record=True, template=_auto_template())

    def broken_prefill(*_args, **_kwargs):
        raise AttributeError("regression marker")

    monkeypatch.setattr(actions, "prefill", broken_prefill)
    _doc, purchase_line = _sync_line(world, db, amount="15")
    assert purchase_line.state == "open"
    assert "Traceback" in caplog.text
    assert str(purchase_line.id) in caplog.text
    assert "regression marker" in caplog.text


def test_auto_record_savepoint_rolls_back_rows_flushed_before_failure(flask_app, world, db, monkeypatch):  # noqa: F811
    client = user_client(db, flask_app, world["org"])
    _rule(
        client,
        payee_pattern="Auto Supplier",
        auto_record=True,
        template=[
            {"name": "Valid first row", "unit": "kg", "quantity_mode": "fixed", "quantity": "1", "share": "50"},
            {
                "name": "Invalid second row",
                "unit": "bottles",
                "quantity_mode": "fixed",
                "quantity": "1.5",
                "share": "50",
            },
        ],
    )
    before_items = db.query(InventoryItem).filter(InventoryItem.org_id == world["org"].id).count()
    before_flows = db.query(CostFlow).filter(CostFlow.org_id == world["org"].id).count()
    before_allocations = db.query(PurchaseAllocation).filter(PurchaseAllocation.org_id == world["org"].id).count()
    create_inventory_item = InventoryRepository.create_inventory_item
    first_row_flushed = []

    def track_first_row_flush(repository, **kwargs):
        item = create_inventory_item(repository, **kwargs)
        if kwargs["name"] == "Valid first row":
            assert db.query(InventoryItem).filter(InventoryItem.id == item.id).one_or_none() is not None
            first_row_flushed.append(item.id)
        return item

    monkeypatch.setattr(InventoryRepository, "create_inventory_item", track_first_row_flush)

    _doc, purchase_line = _sync_line(world, db, amount="15")
    assert len(first_row_flushed) == 1
    assert purchase_line.state == "open"
    assert _allocations(db, world["org"].id, purchase_line.id) == []
    assert db.query(InventoryItem).filter(InventoryItem.org_id == world["org"].id).count() == before_items
    assert db.query(CostFlow).filter(CostFlow.org_id == world["org"].id).count() == before_flows
    assert (
        db.query(PurchaseAllocation).filter(PurchaseAllocation.org_id == world["org"].id).count() == before_allocations
    )
    assert db.execute(text("SELECT 1")).scalar_one() == 1


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
    assert response.get_json()["auto_recorded"] == 1
    assert "'auto_recorded': 1" in caplog.text
    db.expire_all()
    purchase_line = db.query(PurchaseLine).filter(PurchaseLine.org_id == world["org"].id).one()
    allocations = _allocations(db, world["org"].id, purchase_line.id)
    assert len(allocations) == 1
    assert purchase_line.state == "recorded"


def test_purchases_page_says_when_a_rule_recorded_the_line():
    from pathlib import Path

    js = (Path(__file__).resolve().parents[1] / "app/features/costing/frontend/static/purchases.js").read_text()
    assert "card.auto_recorded ? 'Recorded by a rule'" in js


def test_rounding_cent_moves_the_from_price_quantity_with_it(flask_app, world, db):  # noqa: F811
    """Review r2: the row that takes the rounding cent derives its quantity from the final amount."""
    client = user_client(db, flask_app, world["org"])
    template = [
        {
            "name": name,
            "inventory_type": "raw_material",
            "unit": "kg",
            "quantity_mode": "from_price",
            "unit_price": "0.01",
            "share": share,
        }
        for name, share in (("A", "33.3334"), ("B", "33.3333"), ("C", "33.3333"))
    ]
    assert _rule(client, payee_pattern="Auto Supplier", auto_record=True, template=template).status_code == 201
    _doc, purchase_line = _sync_line(world, db, amount="0.01")
    assert purchase_line.state == "recorded"
    allocations = _allocations(db, world["org"].id, purchase_line.id)
    # Suggestions are whole cents (polish): $0.01 is one cent on one row, and its from-price
    # quantity follows that row's final amount; shares that came to $0 buy nothing and are dropped.
    pairs = sorted((D(a.amount), D(a.quantity)) for a in allocations)
    assert pairs == [(D("0.0100"), D("1.0000"))]


def test_r4_switching_an_automatic_rule_off_needs_no_stock_permission(flask_app, world, db):  # noqa: F811
    admin = user_client(db, flask_app, world["org"])
    limited = user_client(db, flask_app, world["org"], permissions=["costs.manage", "costs.view"])
    automated = _rule(admin, payee_pattern="Switch Off Supplier", auto_record=True, template=_auto_template())
    assert automated.status_code == 201, automated.get_json()
    off = limited.put(f"{API}/rules/{automated.get_json()['id']}", json={**automated.get_json(), "is_active": False})
    assert off.status_code == 200, off.get_json()
    assert off.get_json()["is_active"] is False
    back_on = limited.put(f"{API}/rules/{automated.get_json()['id']}", json={**off.get_json(), "is_active": True})
    assert back_on.status_code == 403, "switching an automatic rule back on records stock again"
    page = limited.get("/core/costing/rules").get_data(as_text=True)
    assert 'data-can-auto="false"' in page


def test_r4_over_rounding_never_makes_a_row_negative(flask_app, world, db):  # noqa: F811
    """Review r4: six 16.5% rows and one 1% row on $0.01 round up past the total; the excess comes off
    the largest rows, never pushing the 1% row below zero, and the line still records."""
    client = user_client(db, flask_app, world["org"])
    template = [
        {
            "name": f"Item {i}",
            "inventory_type": "raw_material",
            "unit": "kg",
            "quantity_mode": "fixed",
            "quantity": "1",
            "share": "16.5",
        }
        for i in range(6)
    ] + [
        {
            "name": "Small",
            "inventory_type": "raw_material",
            "unit": "kg",
            "quantity_mode": "fixed",
            "quantity": "1",
            "share": "1",
        }
    ]
    assert _rule(client, payee_pattern="Auto Supplier", auto_record=True, template=template).status_code == 201
    _doc, purchase_line = _sync_line(world, db, amount="0.01")
    allocations = _allocations(db, world["org"].id, purchase_line.id)
    assert purchase_line.state == "recorded"
    assert all(D(a.amount) >= 0 for a in allocations)
    assert sum((D(a.amount) for a in allocations), D("0")) == D("0.0100")


def test_r5_over_rounding_with_a_rest_row_still_records_the_whole_line(flask_app, world, db):  # noqa: F811
    client = user_client(db, flask_app, world["org"])
    template = [
        {
            "name": f"Item {i}",
            "inventory_type": "raw_material",
            "unit": "kg",
            "quantity_mode": "fixed",
            "quantity": "1",
            "share": "16.5",
        }
        for i in range(6)
    ] + [
        {
            "name": "Rest",
            "inventory_type": "raw_material",
            "unit": "kg",
            "quantity_mode": "fixed",
            "quantity": "1",
            "share": "rest",
        }
    ]
    assert _rule(client, payee_pattern="Auto Supplier", auto_record=True, template=template).status_code == 201
    _doc, purchase_line = _sync_line(world, db, amount="0.01")
    allocations = _allocations(db, world["org"].id, purchase_line.id)
    assert purchase_line.state == "recorded"
    assert all(D(a.amount) >= 0 for a in allocations)
    assert sum((D(a.amount) for a in allocations), D("0")) == D("0.0100")
