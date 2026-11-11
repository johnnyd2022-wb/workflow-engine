"""Live-cogs 8.1c-1: record Xero purchases into stock.

The purchase source in every test is the real 8.1b sync seam.  The tests deliberately use
the HTTP actions from the 8.1c-1 contract, then assert both the public cost result and the
persisted allocation facts.
"""

# ruff: noqa: F811 -- flask_app is re-exported as a fixture and used as a test argument

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from app.core.db.models.inventory_item import InventoryItem
from app.features.costing.models import CostingSettings, PurchaseAllocation, PurchaseLine
from tests.costing_helpers import (
    complete,
    execution_cost,
    flows,
    lot,
    lot_cost,
    new_org,
    price,
    purge,
    user_client,
    workflow,
)
from tests.test_compliant_routes import flask_app  # noqa: F401 -- fixture re-export
from tests.test_costing_purchases import (
    FakeXero,
    account,
    connect,
    documents,
    line,
    live_lines,
    sync,
    txn,
)

API = "/api/core/costing"
D = Decimal
PURCHASE_DATE = date(2026, 11, 10)
EARLY_START = date(2026, 1, 1)


@pytest.fixture
def world(db, monkeypatch):
    org = new_org(db)
    connect(db, org.id)
    fake = FakeXero().install(monkeypatch)
    yield {"org": org, "fake": fake}
    purge(db, org)


def _set_start_date(db, org_id, value=EARLY_START):
    settings = db.query(CostingSettings).filter(CostingSettings.org_id == org_id).one_or_none()
    if settings is None:
        settings = CostingSettings(org_id=org_id, start_date=value)
        db.add(settings)
    else:
        settings.start_date = value
    db.commit()


def _sync_purchase(
    world,
    db,
    amount="90",
    *,
    tax="0",
    account_code="310",
    description="Juniper purchase",
    payee="Botanical Supply Co",
    on=PURCHASE_DATE,
    kind="SPEND",
    status="AUTHORISED",
    currency="NZD",
    txn_id=None,
    line_item_id=None,
    positional=False,
):
    """Sync one new Xero transaction and return its document, line and stable Xero ids."""
    org, fake = world["org"], world["fake"]
    txn_id = txn_id or str(uuid4())
    if positional:
        line_item_id = None
    else:
        line_item_id = line_item_id or str(uuid4())
    # Seed the activation anchor before the 8.1b bootstrap applies its date predicate.
    _set_start_date(db, org.id)
    remote = txn(
        [
            line(
                account_code,
                amount,
                tax=tax,
                line_item_id=line_item_id,
                description=description,
            )
        ],
        txn_id=txn_id,
        payee=payee,
        on=on,
        kind=kind,
        status=status,
        amounts="NoTax" if tax == "0" else "Inclusive",
        currency=currency,
    )
    fake.transactions = [remote]
    result = sync(db, org.id)
    assert result.success, result.errors
    doc = next(row for row in documents(db, org.id) if row.external_id == txn_id)
    (purchase_line,) = live_lines(db, org.id, doc.id)
    _set_start_date(db, org.id)
    return doc, purchase_line, txn_id, line_item_id


def _resync_purchase(
    world,
    db,
    txn_id,
    line_item_id,
    amount,
    *,
    account_code="310",
    description="Juniper purchase",
    payee="Botanical Supply Co",
    status="AUTHORISED",
    kind="SPEND",
    positional=False,
):
    remote_line_id = None if positional else line_item_id
    world["fake"].transactions = [
        txn(
            [
                line(
                    account_code,
                    amount,
                    line_item_id=remote_line_id,
                    description=description,
                )
            ],
            txn_id=txn_id,
            payee=payee,
            on=PURCHASE_DATE,
            status=status,
            kind=kind,
            amounts="NoTax",
        )
    ]
    result = sync(db, world["org"].id)
    assert result.success, result.errors
    db.expire_all()


def _record(client, line_id, rows, *, rest="later", key=None):
    return client.post(
        f"{API}/purchases/{line_id}/record",
        json={"rows": rows, "rest": rest},
        headers={"Idempotency-Key": key or str(uuid4())},
    )


def _link(client, line_id, lots, *, rest="later", key=None):
    return client.post(
        f"{API}/purchases/{line_id}/link",
        json={"lots": lots, "rest": rest},
        headers={"Idempotency-Key": key or str(uuid4())},
    )


def _row(name, quantity, amount, unit="kg", inventory_type="raw_material", **extra):
    return {
        "name": name,
        "inventory_type": inventory_type,
        "quantity": str(quantity),
        "unit": unit,
        "amount": str(amount),
        **extra,
    }


def _assert_success(response):
    assert 200 <= response.status_code < 300, response.get_json()


def _allocations(db, org_id, line_id=None):
    db.expire_all()
    query = db.query(PurchaseAllocation).filter(PurchaseAllocation.org_id == org_id)
    if line_id is not None:
        query = query.filter(PurchaseAllocation.purchase_line_id == line_id)
    return query.order_by(PurchaseAllocation.created_at, PurchaseAllocation.id).all()


def _cards(response):
    assert response.status_code == 200, response.get_json()
    body = response.get_json()
    assert set(body) >= {"cards", "counts"}
    return body["cards"], body["counts"]


def _candidate_rows(response):
    assert response.status_code == 200, response.get_json()
    body = response.get_json()
    assert set(body) == {"candidates"}
    return body["candidates"]


def _item_ids(db, org_id):
    return {row.id for row in db.query(InventoryItem.id).filter(InventoryItem.org_id == org_id).all()}


def test_ac5_record_creates_lot_flow_allocation_and_actual_cost(flask_app, world, db):  # noqa: F811
    org = world["org"]
    doc, purchase_line, _, _ = _sync_purchase(world, db, "90", payee="Juniper Merchants")
    client = user_client(db, flask_app, org)

    response = _record(
        client,
        purchase_line.id,
        [
            _row(
                "Juniper Berries",
                2,
                90,
                supplier_batch_number="JB-110",
                expiry_date="2027-11-10",
            )
        ],
    )
    _assert_success(response)

    db.expire_all()
    item = db.query(InventoryItem).filter(InventoryItem.org_id == org.id, InventoryItem.name == "Juniper Berries").one()
    assert item.inventory_type == "raw_material"
    assert D(str(item.quantity)) == D("2") and item.unit == "kg"
    assert item.supplier == "Juniper Merchants" and item.purchase_date == doc.document_date
    assert item.supplier_batch_number == "JB-110" and item.expiry_date == date(2027, 11, 10)
    (created,) = flows(db, org.id, item.id, "created")
    assert D(str(created.quantity)) == D("2")
    (allocation,) = _allocations(db, org.id, purchase_line.id)
    assert allocation.org_id == org.id
    assert allocation.purchase_line_id == purchase_line.id
    assert allocation.inventory_item_id == item.id and allocation.cost_flow_id == created.id
    assert D(str(allocation.amount)) == D("90.0000")
    assert D(str(allocation.quantity)) == D("2.0000")
    assert allocation.status == "active" and allocation.created_by_user_id is not None
    cost = lot_cost(db, org.id, item.id)
    assert (D(cost["unit_cost"]), cost["status"], cost["source"]) == (D("45"), "actual", "purchase")
    db.expire_all()
    assert db.get(PurchaseLine, purchase_line.id).state == "recorded"


def test_ac6_split_rows_support_not_stock_later_and_reject_overallocation(flask_app, world, db):  # noqa: F811
    org = world["org"]
    client = user_client(db, flask_app, org)

    _, line_not_stock, _, _ = _sync_purchase(world, db, "100", description="Split not stock")
    response = _record(
        client,
        line_not_stock.id,
        [_row("Juniper", 2, 60), _row("Coriander", 5, 25)],
        rest="not_stock",
    )
    _assert_success(response)
    db.expire_all()
    saved = db.get(PurchaseLine, line_not_stock.id)
    assert D(str(saved.not_stock_amount)) == D("15.0000") and saved.state == "recorded"
    assert sorted(D(str(a.amount)) for a in _allocations(db, org.id, saved.id)) == [D("25"), D("60")]

    _, line_later, _, _ = _sync_purchase(world, db, "100", description="Split later")
    response = _record(
        client,
        line_later.id,
        [_row("Angelica", 3, 60), _row("Orris", 1, 25)],
        rest="later",
    )
    _assert_success(response)
    db.expire_all()
    saved = db.get(PurchaseLine, line_later.id)
    assert D(str(saved.not_stock_amount)) == 0 and saved.state == "partly_recorded"
    cards, _ = _cards(client.get(f"{API}/purchases?tab=to_record"))
    card = next(row for row in cards if row["line_id"] == str(line_later.id))
    assert D(card["amount"]) == D("100.0000") and D(card["open"]) == D("15.0000")

    _, line_too_much, _, _ = _sync_purchase(world, db, "100", description="Over allocated")
    items_before = _item_ids(db, org.id)
    allocations_before = {row.id for row in _allocations(db, org.id)}
    response = _record(client, line_too_much.id, [_row("Impossible", 1, 101)])
    assert response.status_code == 400
    assert _item_ids(db, org.id) == items_before
    assert {row.id for row in _allocations(db, org.id)} == allocations_before
    db.expire_all()
    rejected = db.get(PurchaseLine, line_too_much.id)
    assert rejected.state == "open" and D(str(rejected.not_stock_amount)) == 0


def test_ac7_idempotency_replays_the_first_record_response(flask_app, world, db):  # noqa: F811
    org = world["org"]
    _, purchase_line, _, _ = _sync_purchase(world, db, "90")
    client = user_client(db, flask_app, org)
    key = f"record-{uuid4()}"
    body = [_row("Idempotent Juniper", 2, 90)]

    first = _record(client, purchase_line.id, body, key=key)
    _assert_success(first)
    item_ids = _item_ids(db, org.id)
    allocation_ids = {row.id for row in _allocations(db, org.id)}
    replay = _record(client, purchase_line.id, body, key=key)

    assert replay.status_code == first.status_code
    assert replay.get_data() == first.get_data()
    assert replay.headers["Idempotent-Replay"] == "true"
    assert _item_ids(db, org.id) == item_ids
    assert {row.id for row in _allocations(db, org.id)} == allocation_ids


def test_ac8_link_replaces_manual_price_without_creating_a_lot(flask_app, world, db):  # noqa: F811
    from app.features.costing.models import LotCostEntry

    org = world["org"]
    _, purchase_line, _, _ = _sync_purchase(world, db, "90")
    existing = lot(
        db,
        org.id,
        "Hand-entered Juniper",
        2,
        "kg",
        supplier="Botanical Supply Co",
        purchase_date=PURCHASE_DATE,
    )
    manual = price(db, org.id, existing.id, 80, 2)
    items_before = _item_ids(db, org.id)
    client = user_client(db, flask_app, org)

    response = _link(
        client,
        purchase_line.id,
        [{"inventory_item_id": str(existing.id), "amount": "90"}],
    )
    _assert_success(response)

    assert _item_ids(db, org.id) == items_before
    (created,) = flows(db, org.id, existing.id, "created")
    (allocation,) = _allocations(db, org.id, purchase_line.id)
    assert allocation.inventory_item_id == existing.id and allocation.cost_flow_id == created.id
    assert D(str(allocation.quantity)) == D("2") and D(str(allocation.amount)) == D("90")
    db.expire_all()
    replaced = db.get(LotCostEntry, manual.id)
    assert replaced.is_active is False and replaced.deactivated_at is not None
    cost = lot_cost(db, org.id, existing.id)
    assert D(cost["unit_cost"]) == D("45") and cost["source"] == "purchase"


def test_ac9_candidates_apply_window_ranking_allocated_exclusion_and_include_manual(flask_app, world, db):  # noqa: F811
    org = world["org"]
    _, target_line, _, _ = _sync_purchase(world, db, "90", payee=" Same  Supplier ")
    same_supplier = lot(
        db,
        org.id,
        "Manual candidate",
        2,
        "kg",
        supplier="same supplier",
        purchase_date=date(2026, 11, 8),
    )
    price(db, org.id, same_supplier.id, 80, 2)
    closer_other_supplier = lot(
        db,
        org.id,
        "Closer candidate",
        1,
        "kg",
        supplier="Someone else",
        purchase_date=PURCHASE_DATE,
    )
    too_early = lot(db, org.id, "Too early", 1, "kg", purchase_date=date(2026, 11, 1))
    too_late = lot(db, org.id, "Too late", 1, "kg", purchase_date=date(2026, 11, 25))
    already_allocated = lot(
        db,
        org.id,
        "Already allocated",
        1,
        "kg",
        supplier="same supplier",
        purchase_date=date(2026, 11, 9),
    )
    _, source_line, _, _ = _sync_purchase(world, db, "10", description="Prior allocation")
    client = user_client(db, flask_app, org)
    _assert_success(
        _link(
            client,
            source_line.id,
            [{"inventory_item_id": str(already_allocated.id), "quantity": "1", "amount": "10"}],
        )
    )

    candidates = _candidate_rows(client.get(f"{API}/purchases/{target_line.id}/candidates"))
    ids = [row["inventory_item_id"] for row in candidates]
    assert ids[:2] == [str(same_supplier.id), str(closer_other_supplier.id)]
    assert str(same_supplier.id) in ids, "a manual price does not disqualify the lot"
    assert str(too_early.id) not in ids and str(too_late.id) not in ids
    assert str(already_allocated.id) not in ids


def test_ac11_skip_moves_tabs_and_a_later_action_clears_it(flask_app, world, db):  # noqa: F811
    org = world["org"]
    _, purchase_line, _, _ = _sync_purchase(world, db, "40")
    client = user_client(db, flask_app, org)

    skipped = client.post(f"{API}/purchases/{purchase_line.id}/skip", json={})
    _assert_success(skipped)
    cards, _ = _cards(client.get(f"{API}/purchases?tab=skipped"))
    assert [row["line_id"] for row in cards] == [str(purchase_line.id)]
    cards, _ = _cards(client.get(f"{API}/purchases?tab=to_record"))
    assert str(purchase_line.id) not in {row["line_id"] for row in cards}

    reopened = client.post(f"{API}/purchases/{purchase_line.id}/reopen", json={})
    _assert_success(reopened)
    db.expire_all()
    saved = db.get(PurchaseLine, purchase_line.id)
    assert saved.state == "open" and D(str(saved.not_stock_amount)) == 0
    cards, _ = _cards(client.get(f"{API}/purchases?tab=to_record"))
    assert str(purchase_line.id) in {row["line_id"] for row in cards}

    _assert_success(client.post(f"{API}/purchases/{purchase_line.id}/skip", json={}))
    decided = client.post(f"{API}/purchases/{purchase_line.id}/not-stock", json={})
    _assert_success(decided)
    db.expire_all()
    saved = db.get(PurchaseLine, purchase_line.id)
    assert saved.state == "not_stock" and D(str(saved.not_stock_amount)) == D("40")
    cards, _ = _cards(client.get(f"{API}/purchases?tab=skipped"))
    assert str(purchase_line.id) not in {row["line_id"] for row in cards}


def test_ac12_refund_reduces_cost_once_without_changing_quantity(flask_app, world, db):  # noqa: F811
    org = world["org"]
    _, purchase_line, _, _ = _sync_purchase(world, db, "90", description="Original purchase")
    client = user_client(db, flask_app, org)
    _assert_success(_record(client, purchase_line.id, [_row("Refunded Juniper", 2, 90)]))
    item = (
        db.query(InventoryItem).filter(InventoryItem.org_id == org.id, InventoryItem.name == "Refunded Juniper").one()
    )
    quantity_before = D(str(item.quantity))

    _, refund_line, _, _ = _sync_purchase(
        world,
        db,
        "20",
        description="Returned Juniper",
        kind="RECEIVE",
    )
    response = client.post(
        f"{API}/purchases/{refund_line.id}/refund",
        json={"lots": [{"inventory_item_id": str(item.id), "amount": "-20"}]},
    )
    _assert_success(response)

    (refund,) = _allocations(db, org.id, refund_line.id)
    assert D(str(refund.amount)) == D("-20")
    assert D(str(refund.quantity)) == 0 and refund.cost_flow_id is None
    db.expire_all()
    assert D(str(db.get(InventoryItem, item.id).quantity)) == quantity_before == D("2")
    cost = lot_cost(db, org.id, item.id)
    assert D(cost["unit_cost"]) == (D("90") - D("20")) / D("2") == D("35")
    assert cost["status"] == "actual"


def test_ac30_late_purchase_updates_consuming_batch_and_output_lot(flask_app, world, db):  # noqa: F811
    org = world["org"]
    client = user_client(db, flask_app, org)
    raw = lot(
        db,
        org.id,
        "Late-priced Juniper",
        2,
        "kg",
        supplier="Botanical Supply Co",
        purchase_date=PURCHASE_DATE,
    )
    execution, (step,) = workflow(db, org.id, [[{"name": "Late-cost Gin", "unit": "bottles"}]])
    complete(
        client,
        execution,
        step,
        [(raw, 1, "kg")],
        [{"name": "Late-cost Gin", "quantity": 2, "unit": "bottles"}],
    )
    before = execution_cost(db, org.id, execution.id)
    assert before["status"] == "partial" and before["outputs"][0]["unit_cost"] is None

    _, purchase_line, _, _ = _sync_purchase(world, db, "90", description="Late price")
    _assert_success(
        _link(
            client,
            purchase_line.id,
            [{"inventory_item_id": str(raw.id), "quantity": "2", "amount": "90"}],
        )
    )

    after = execution_cost(db, org.id, execution.id)
    assert after["status"] == "actual"
    assert D(after["known_input_cost"]) == D("45")
    assert D(after["outputs"][0]["unit_cost"]) == D("22.5")
    produced_flow_id = after["outputs"][0]["flow_id"]
    from app.features.costing.models import CostFlow

    produced = db.query(CostFlow).filter(CostFlow.id == produced_flow_id, CostFlow.org_id == org.id).one()
    output_cost = lot_cost(db, org.id, produced.inventory_item_id)
    assert (D(output_cost["unit_cost"]), output_cost["status"]) == (D("22.5"), "actual")


def test_ac34_amount_change_rescales_allocation_and_cost(flask_app, world, db):  # noqa: F811
    org = world["org"]
    _, purchase_line, txn_id, line_id = _sync_purchase(world, db, "90")
    client = user_client(db, flask_app, org)
    _assert_success(_record(client, purchase_line.id, [_row("Rescaled Juniper", 2, 90)]))
    (allocation,) = _allocations(db, org.id, purchase_line.id)

    _resync_purchase(world, db, txn_id, line_id, "99")

    db.expire_all()
    changed = db.get(PurchaseAllocation, allocation.id)
    saved_line = db.get(PurchaseLine, purchase_line.id)
    assert D(str(changed.amount)) == D("99.0000")
    assert D(str(changed.quantity)) == D("2.0000")
    assert saved_line.review_reason == "amount_changed"
    assert D(lot_cost(db, org.id, changed.inventory_item_id)["unit_cost"]) == D("99") / D("2") == D("49.5")


def test_ac35_voided_purchase_is_orphaned_estimated_and_review_keep_clears_reason(flask_app, world, db):  # noqa: F811
    org = world["org"]
    _, purchase_line, txn_id, line_id = _sync_purchase(world, db, "90")
    client = user_client(db, flask_app, org)
    _assert_success(_record(client, purchase_line.id, [_row("Voided Juniper", 2, 90)]))
    (allocation,) = _allocations(db, org.id, purchase_line.id)
    item_id = allocation.inventory_item_id

    _resync_purchase(world, db, txn_id, line_id, "90", status="DELETED")

    db.expire_all()
    assert db.get(PurchaseAllocation, allocation.id).status == "orphaned"
    assert db.get(PurchaseLine, purchase_line.id).review_reason == "deleted_in_xero"
    assert D(str(db.get(InventoryItem, item_id).quantity)) == D("2")
    cost = lot_cost(db, org.id, item_id)
    assert D(cost["unit_cost"]) == D("45") and cost["status"] == "estimated"
    cards, _ = _cards(client.get(f"{API}/purchases?tab=to_record"))
    assert str(purchase_line.id) in {row["line_id"] for row in cards}

    kept = client.post(f"{API}/purchases/{purchase_line.id}/review", json={"action": "keep"})
    _assert_success(kept)
    db.expire_all()
    assert db.get(PurchaseLine, purchase_line.id).review_reason is None
    assert db.get(PurchaseAllocation, allocation.id).status == "orphaned"
    cards, _ = _cards(client.get(f"{API}/purchases?tab=to_record"))
    assert str(purchase_line.id) not in {row["line_id"] for row in cards}


def test_ac35_review_unlink_removes_allocation_but_keeps_lot(flask_app, world, db):  # noqa: F811
    org = world["org"]
    name = f"Unlinked-{uuid4()}"
    _, purchase_line, txn_id, line_id = _sync_purchase(world, db, "90")
    client = user_client(db, flask_app, org)
    _assert_success(_record(client, purchase_line.id, [_row(name, 2, 90)]))
    (allocation,) = _allocations(db, org.id, purchase_line.id)
    item_id = allocation.inventory_item_id
    _resync_purchase(world, db, txn_id, line_id, "90", status="VOIDED")

    response = client.post(f"{API}/purchases/{purchase_line.id}/review", json={"action": "unlink"})
    _assert_success(response)

    db.expire_all()
    assert db.get(PurchaseAllocation, allocation.id) is None
    assert db.get(InventoryItem, item_id) is not None
    assert db.get(PurchaseLine, purchase_line.id).review_reason is None
    cost = lot_cost(db, org.id, item_id)
    assert cost["unit_cost"] is None and cost["status"] == "unknown"


def test_ac35_review_edit_amounts_recomputes_open_and_rejects_overallocation(flask_app, world, db):  # noqa: F811
    org = world["org"]
    _, purchase_line, txn_id, line_id = _sync_purchase(world, db, "90")
    client = user_client(db, flask_app, org)
    _assert_success(_record(client, purchase_line.id, [_row("Edited Juniper", 2, 90)]))
    (allocation,) = _allocations(db, org.id, purchase_line.id)
    _resync_purchase(world, db, txn_id, line_id, "99")

    edited = client.put(
        f"{API}/purchases/{purchase_line.id}/allocations",
        json={"allocations": [{"id": str(allocation.id), "amount": "90", "quantity": "2"}]},
    )
    _assert_success(edited)
    db.expire_all()
    saved_line = db.get(PurchaseLine, purchase_line.id)
    saved_allocation = db.get(PurchaseAllocation, allocation.id)
    assert saved_line.state == "partly_recorded"
    assert D(str(saved_allocation.amount)) == D("90") and D(str(saved_allocation.quantity)) == D("2")
    cards, _ = _cards(client.get(f"{API}/purchases?tab=to_record"))
    card = next(row for row in cards if row["line_id"] == str(purchase_line.id))
    assert D(card["open"]) == D("99") - D("90") == D("9")

    rejected = client.put(
        f"{API}/purchases/{purchase_line.id}/allocations",
        json={"allocations": [{"id": str(allocation.id), "amount": "100", "quantity": "2"}]},
    )
    assert rejected.status_code == 400
    db.expire_all()
    assert D(str(db.get(PurchaseAllocation, allocation.id).amount)) == D("90"), "the failed edit is atomic"


def test_ac35_recoded_purchase_keeps_active_allocation_and_moves_to_review(flask_app, world, db):  # noqa: F811
    org = world["org"]
    _, purchase_line, txn_id, line_id = _sync_purchase(world, db, "90")
    client = user_client(db, flask_app, org)
    _assert_success(_record(client, purchase_line.id, [_row("Recoded Juniper", 2, 90)]))
    (allocation,) = _allocations(db, org.id, purchase_line.id)

    world["fake"].accounts.append(account("777", "General office expense", kind="EXPENSE"))
    _resync_purchase(world, db, txn_id, line_id, "90", account_code="777")

    db.expire_all()
    saved = db.get(PurchaseLine, purchase_line.id)
    assert saved.treatment == "not_stock" and saved.review_reason == "recoded"
    assert db.get(PurchaseAllocation, allocation.id).status == "active"
    cards, _ = _cards(client.get(f"{API}/purchases?tab=to_record"))
    assert str(purchase_line.id) in {row["line_id"] for row in cards}


def test_ac35_superseded_record_is_orphaned_and_replacement_is_a_new_card(flask_app, world, db):  # noqa: F811
    org = world["org"]
    _, purchase_line, txn_id, _ = _sync_purchase(world, db, "90", positional=True)
    client = user_client(db, flask_app, org)
    _assert_success(_record(client, purchase_line.id, [_row("Superseded Juniper", 2, 90)]))
    (allocation,) = _allocations(db, org.id, purchase_line.id)

    _resync_purchase(
        world,
        db,
        txn_id,
        None,
        "100",
        description="Replacement purchase line",
        positional=True,
    )

    db.expire_all()
    old = db.get(PurchaseLine, purchase_line.id)
    assert old.superseded_at is not None and old.review_reason == "deleted_in_xero"
    assert db.get(PurchaseAllocation, allocation.id).status == "orphaned"
    doc = next(row for row in documents(db, org.id) if row.external_id == txn_id)
    (replacement,) = live_lines(db, org.id, doc.id)
    assert replacement.id != old.id and replacement.state == "open"
    cards, _ = _cards(client.get(f"{API}/purchases?tab=to_record"))
    assert {str(old.id), str(replacement.id)} <= {row["line_id"] for row in cards}


def test_ac74_overallocation_is_atomic_and_both_remainder_choices_recompute_state(flask_app, world, db):  # noqa: F811
    org = world["org"]
    client = user_client(db, flask_app, org)
    _, rejected, _, _ = _sync_purchase(world, db, "40", description="AC74 rejected")
    item_ids = _item_ids(db, org.id)
    response = _record(client, rejected.id, [_row("Over by a cent", 1, "40.01")])
    assert response.status_code == 400
    assert _item_ids(db, org.id) == item_ids and _allocations(db, org.id, rejected.id) == []

    _, later, _, _ = _sync_purchase(world, db, "100", description="AC74 later")
    _assert_success(_record(client, later.id, [_row("Later", 2, 85)], rest="later"))
    db.expire_all()
    later_saved = db.get(PurchaseLine, later.id)
    assert later_saved.state == "partly_recorded"
    assert D(str(later_saved.amount_ex_tax)) - sum(
        D(str(a.amount)) for a in _allocations(db, org.id, later.id) if a.status == "active"
    ) - D(str(later_saved.not_stock_amount)) == D("15.0000")

    _, not_stock, _, _ = _sync_purchase(world, db, "100", description="AC74 not stock")
    _assert_success(_record(client, not_stock.id, [_row("Stock share", 2, 85)], rest="not_stock"))
    db.expire_all()
    not_stock_saved = db.get(PurchaseLine, not_stock.id)
    assert not_stock_saved.state == "recorded" and D(str(not_stock_saved.not_stock_amount)) == D("15")


def test_ac75_link_quantity_limit_and_deactivates_flow_and_whole_lot_prices(flask_app, world, db):  # noqa: F811
    from app.features.costing.models import LotCostEntry

    org = world["org"]
    client = user_client(db, flask_app, org)
    item = lot(db, org.id, "Two-price Juniper", 2, "kg", purchase_date=PURCHASE_DATE)
    (created,) = flows(db, org.id, item.id, "created")
    flow_entry = price(db, org.id, item.id, 70, 2, cost_flow_id=created.id)
    whole_entry = price(db, org.id, item.id, 80, 2)

    _, too_large, _, _ = _sync_purchase(world, db, "90", description="Quantity too large")
    response = _link(
        client,
        too_large.id,
        [{"inventory_item_id": str(item.id), "quantity": "2.0001", "amount": "90"}],
    )
    assert response.status_code == 400 and _allocations(db, org.id, too_large.id) == []
    db.expire_all()
    assert db.get(LotCostEntry, flow_entry.id).is_active is True
    assert db.get(LotCostEntry, whole_entry.id).is_active is True

    _, valid, _, _ = _sync_purchase(world, db, "90", description="Valid link")
    _assert_success(
        _link(
            client,
            valid.id,
            [{"inventory_item_id": str(item.id), "quantity": "2", "amount": "90"}],
        )
    )
    db.expire_all()
    for entry_id in (flow_entry.id, whole_entry.id):
        entry = db.get(LotCostEntry, entry_id)
        assert entry.is_active is False and entry.deactivated_at is not None
    assert (D(lot_cost(db, org.id, item.id)["unit_cost"]), lot_cost(db, org.id, item.id)["source"]) == (
        D("45"),
        "purchase",
    )


@pytest.mark.parametrize(
    ("case", "line_changes", "document_status", "start_date", "expected_tab"),
    [
        (
            "review-on-voided-document",
            {"review_reason": "deleted_in_xero", "state": "recorded"},
            "voided",
            EARLY_START,
            "to_record",
        ),
        (
            "review-on-superseded-line",
            {
                "review_reason": "deleted_in_xero",
                "state": "recorded",
                "superseded_at": datetime(2026, 11, 11, tzinfo=UTC),
            },
            "active",
            EARLY_START,
            "to_record",
        ),
        ("live-open", {"state": "open"}, "active", EARLY_START, "to_record"),
        ("live-partly-recorded", {"state": "partly_recorded"}, "active", EARLY_START, "to_record"),
        ("live-recorded", {"state": "recorded"}, "active", EARLY_START, "recorded"),
        ("live-skipped", {"state": "skipped"}, "active", EARLY_START, "skipped"),
        (
            "live-not-stock",
            {"state": "not_stock", "not_stock_amount": D("90")},
            "active",
            EARLY_START,
            "not_stock",
        ),
        ("before-start-date", {"state": "open"}, "active", date(2026, 11, 11), None),
        ("non-stock-treatment", {"state": "open", "treatment": "duty"}, "active", EARLY_START, None),
        ("voided-without-review", {"state": "open"}, "voided", EARLY_START, None),
        (
            "superseded-without-review",
            {"state": "open", "superseded_at": datetime(2026, 11, 11, tzinfo=UTC)},
            "active",
            EARLY_START,
            None,
        ),
        ("null-amount", {"state": "open", "amount_ex_tax": None}, "active", EARLY_START, None),
    ],
    ids=lambda value: value if isinstance(value, str) else None,
)
def test_ac76_tab_rule_first_match_wins_row_by_row(
    flask_app,
    world,
    db,
    case,
    line_changes,
    document_status,
    start_date,
    expected_tab,
):  # noqa: F811
    org = world["org"]
    doc, purchase_line, _, _ = _sync_purchase(world, db, "90", description=case)
    client = user_client(db, flask_app, org)
    for field, value in line_changes.items():
        setattr(purchase_line, field, value)
    doc.status = document_status
    settings = db.query(CostingSettings).filter(CostingSettings.org_id == org.id).one()
    settings.start_date = start_date
    db.commit()

    tabs = ("to_record", "recorded", "skipped", "not_stock")
    for tab in tabs:
        cards, counts = _cards(client.get(f"{API}/purchases?tab={tab}"))
        present = str(purchase_line.id) in {row["line_id"] for row in cards}
        assert present is (tab == expected_tab), (case, tab, cards)
        assert counts[tab] == (1 if tab == expected_tab else 0), (case, tab, counts)


def test_ac77_amount_rescale_splits_60_30_into_66_33_and_preserves_quantities(flask_app, world, db):  # noqa: F811
    org = world["org"]
    _, purchase_line, txn_id, line_id = _sync_purchase(world, db, "90")
    client = user_client(db, flask_app, org)
    _assert_success(
        _record(
            client,
            purchase_line.id,
            [_row("Sixty-dollar lot", 2, 60), _row("Thirty-dollar lot", 3, 30)],
        )
    )
    before = {row.inventory_item_id: (D(str(row.amount)), D(str(row.quantity))) for row in _allocations(db, org.id)}

    _resync_purchase(world, db, txn_id, line_id, "99")

    after = {row.inventory_item_id: (D(str(row.amount)), D(str(row.quantity))) for row in _allocations(db, org.id)}
    expected = {item_id: (amount * D("99") / D("90"), quantity) for item_id, (amount, quantity) in before.items()}
    assert after == expected
    assert sorted(amount for amount, _ in after.values()) == [D("33.0000"), D("66.0000")]
    assert db.get(PurchaseLine, purchase_line.id).review_reason == "amount_changed"


def test_ac77_amount_to_zero_orphans_instead_of_rescaling_across_zero(flask_app, world, db):  # noqa: F811
    org = world["org"]
    _, purchase_line, txn_id, line_id = _sync_purchase(world, db, "90")
    client = user_client(db, flask_app, org)
    _assert_success(_record(client, purchase_line.id, [_row("Zeroed Juniper", 2, 90)]))
    (allocation,) = _allocations(db, org.id, purchase_line.id)

    _resync_purchase(world, db, txn_id, line_id, "0")

    db.expire_all()
    zeroed = db.get(PurchaseAllocation, allocation.id)
    assert zeroed.status == "orphaned"
    assert D(str(zeroed.amount)) == D("90.0000"), "orphaning preserves the historical price fact"
    assert D(str(zeroed.quantity)) == D("2.0000")


def test_ac78_manage_without_inventory_adjust_cannot_record_or_link_but_can_decide(flask_app, world, db):  # noqa: F811
    org = world["org"]
    _, record_line, _, _ = _sync_purchase(world, db, "90", description="Permission record")
    _, link_line, _, _ = _sync_purchase(world, db, "90", description="Permission link")
    _, skip_line, _, _ = _sync_purchase(world, db, "20", description="Permission skip")
    _, not_stock_line, _, _ = _sync_purchase(world, db, "30", description="Permission not stock")
    existing = lot(db, org.id, "Permission candidate", 2, "kg", purchase_date=PURCHASE_DATE)
    manager = user_client(db, flask_app, org, permissions=["costs.manage"])

    assert _record(manager, record_line.id, [_row("Forbidden", 2, 90)]).status_code == 403
    assert (
        _link(
            manager,
            link_line.id,
            [{"inventory_item_id": str(existing.id), "quantity": "2", "amount": "90"}],
        ).status_code
        == 403
    )
    _assert_success(manager.post(f"{API}/purchases/{skip_line.id}/skip", json={}))
    _assert_success(manager.post(f"{API}/purchases/{not_stock_line.id}/not-stock", json={}))
    db.expire_all()
    assert db.get(PurchaseLine, skip_line.id).state == "skipped"
    assert db.get(PurchaseLine, not_stock_line.id).state == "not_stock"
    assert _allocations(db, org.id, record_line.id) == []
    assert _allocations(db, org.id, link_line.id) == []


def test_ac78_view_only_is_forbidden_from_every_purchase_write(flask_app, world, db):  # noqa: F811
    org = world["org"]
    _, purchase_line, _, _ = _sync_purchase(world, db, "90")
    existing = lot(db, org.id, "Viewer candidate", 2, "kg", purchase_date=PURCHASE_DATE)
    viewer = user_client(db, flask_app, org, permissions=["costs.view"])
    posts = [
        ("record", {"rows": [_row("No", 2, 90)], "rest": "later"}),
        (
            "link",
            {
                "lots": [{"inventory_item_id": str(existing.id), "quantity": "2", "amount": "90"}],
                "rest": "later",
            },
        ),
        ("refund", {"lots": [{"inventory_item_id": str(existing.id), "amount": "-10"}]}),
        ("not-stock", {}),
        ("skip", {}),
        ("reopen", {}),
        ("review", {"action": "keep"}),
    ]
    for action, body in posts:
        response = viewer.post(
            f"{API}/purchases/{purchase_line.id}/{action}",
            json=body,
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert response.status_code == 403, action
    response = viewer.put(
        f"{API}/purchases/{purchase_line.id}/allocations",
        json={"allocations": []},
    )
    assert response.status_code == 403
    db.expire_all()
    assert db.get(PurchaseLine, purchase_line.id).state == "open"
    assert _allocations(db, org.id, purchase_line.id) == []


def test_ac79_foreign_line_actions_are_404_and_change_nothing(flask_app, world, db):  # noqa: F811
    intruder_org = world["org"]
    victim_org = new_org(db)
    try:
        connect(db, victim_org.id)
        _set_start_date(db, victim_org.id)
        world["fake"].transactions = [
            txn(
                [line("310", "90", line_item_id=str(uuid4()), description="Victim purchase")],
                payee="Victim supplier",
                on=PURCHASE_DATE,
                amounts="NoTax",
            )
        ]
        result = sync(db, victim_org.id)
        assert result.success, result.errors
        victim_doc = documents(db, victim_org.id)[0]
        (victim_line,) = live_lines(db, victim_org.id, victim_doc.id)
        victim_lot = lot(db, victim_org.id, "Victim lot", 2, "kg", purchase_date=PURCHASE_DATE)
        intruder = user_client(db, flask_app, intruder_org)
        before = (
            victim_line.state,
            D(str(victim_line.not_stock_amount)),
            victim_line.review_reason,
            _item_ids(db, victim_org.id),
            {row.id for row in _allocations(db, victim_org.id)},
        )
        actions = [
            ("record", {"rows": [_row("Stolen", 2, 90)], "rest": "later"}),
            (
                "link",
                {
                    "lots": [{"inventory_item_id": str(victim_lot.id), "quantity": "2", "amount": "90"}],
                    "rest": "later",
                },
            ),
            ("refund", {"lots": [{"inventory_item_id": str(victim_lot.id), "amount": "-10"}]}),
            ("not-stock", {}),
            ("skip", {}),
            ("reopen", {}),
            ("review", {"action": "unlink"}),
        ]
        for action, body in actions:
            response = intruder.post(
                f"{API}/purchases/{victim_line.id}/{action}",
                json=body,
                headers={"Idempotency-Key": str(uuid4())},
            )
            assert response.status_code == 404, action
        assert (
            intruder.put(
                f"{API}/purchases/{victim_line.id}/allocations",
                json={"allocations": []},
            ).status_code
            == 404
        )
        assert intruder.get(f"{API}/purchases/{victim_line.id}/candidates").status_code == 404
        db.expire_all()
        unchanged = db.get(PurchaseLine, victim_line.id)
        after = (
            unchanged.state,
            D(str(unchanged.not_stock_amount)),
            unchanged.review_reason,
            _item_ids(db, victim_org.id),
            {row.id for row in _allocations(db, victim_org.id)},
        )
        assert after == before
    finally:
        purge(db, victim_org)


def test_ac79_candidates_never_cross_organisations(flask_app, world, db):  # noqa: F811
    org = world["org"]
    _, purchase_line, _, _ = _sync_purchase(world, db, "90", payee="Shared supplier")
    local = lot(
        db,
        org.id,
        "Local lot",
        1,
        "kg",
        supplier="Shared supplier",
        purchase_date=PURCHASE_DATE,
    )
    other = new_org(db)
    try:
        foreign = lot(
            db,
            other.id,
            "Foreign lot",
            1,
            "kg",
            supplier="Shared supplier",
            purchase_date=PURCHASE_DATE,
        )
        client = user_client(db, flask_app, org)
        rows = _candidate_rows(client.get(f"{API}/purchases/{purchase_line.id}/candidates"))
        ids = {row["inventory_item_id"] for row in rows}
        assert str(local.id) in ids and str(foreign.id) not in ids
    finally:
        purge(db, other)


def test_ac80_record_replay_creates_no_second_lot_or_allocation(flask_app, world, db):  # noqa: F811
    org = world["org"]
    _, purchase_line, _, _ = _sync_purchase(world, db, "50")
    client = user_client(db, flask_app, org)
    key = f"ac80-{uuid4()}"
    rows = [_row("Replay-proof lot", 5, 50)]
    _assert_success(_record(client, purchase_line.id, rows, key=key))
    first_items = _item_ids(db, org.id)
    first_allocations = {row.id for row in _allocations(db, org.id)}

    replay = _record(client, purchase_line.id, rows, key=key)
    _assert_success(replay)
    assert replay.headers["Idempotent-Replay"] == "true"
    assert _item_ids(db, org.id) == first_items
    assert {row.id for row in _allocations(db, org.id)} == first_allocations


def test_ac80_needs_rate_line_rejects_every_action_without_writes(flask_app, world, db):  # noqa: F811
    org = world["org"]
    _, purchase_line, _, _ = _sync_purchase(world, db, "90", currency="USD")
    assert purchase_line.amount_ex_tax is None
    existing = lot(db, org.id, "FX candidate", 2, "kg", purchase_date=PURCHASE_DATE)
    client = user_client(db, flask_app, org)
    items_before = _item_ids(db, org.id)
    actions = [
        ("record", {"rows": [_row("FX lot", 2, 90)], "rest": "later"}),
        (
            "link",
            {
                "lots": [{"inventory_item_id": str(existing.id), "quantity": "2", "amount": "90"}],
                "rest": "later",
            },
        ),
        ("refund", {"lots": [{"inventory_item_id": str(existing.id), "amount": "-20"}]}),
        ("not-stock", {}),
        ("skip", {}),
        ("reopen", {}),
        ("review", {"action": "keep"}),
    ]
    for action, body in actions:
        response = client.post(
            f"{API}/purchases/{purchase_line.id}/{action}",
            json=body,
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert response.status_code == 400, (action, response.get_json())
    response = client.put(
        f"{API}/purchases/{purchase_line.id}/allocations",
        json={"allocations": []},
    )
    assert response.status_code == 400
    assert _item_ids(db, org.id) == items_before
    assert _allocations(db, org.id, purchase_line.id) == []


def test_ac77_rescale_rounding_remainder_keeps_the_total(flask_app, world, db):  # noqa: F811
    """$100 split 33.3333 / 33.3333 / 33.3334, Xero changes it to $110: each ×1.1 rounds to
    36.6666 / 36.6666 / 36.6667 (109.9999); the 0.0001 goes to the largest allocation."""
    org = world["org"]
    _, purchase_line, txn_id, line_id = _sync_purchase(world, db, "100")
    client = user_client(db, flask_app, org)
    _assert_success(
        _record(
            client,
            purchase_line.id,
            [_row("A lot", 1, "33.3333"), _row("B lot", 1, "33.3333"), _row("C lot", 1, "33.3334")],
        )
    )
    _resync_purchase(world, db, txn_id, line_id, "110")
    amounts = sorted(D(str(row.amount)) for row in _allocations(db, org.id, purchase_line.id))
    assert amounts == [D("36.6666"), D("36.6666"), D("36.6668")]
    assert sum(amounts) == D("110.0000")


# --- build-review round 1 regressions (8.1c-1) ----------------------------------------------------


def _resync_raw(world, db, txn_id, line_item_id, amount, **kw):
    world["fake"].transactions = [
        txn([line("310", amount, line_item_id=line_item_id)], txn_id=txn_id, on=PURCHASE_DATE, amounts="NoTax", **kw)
    ]
    assert sync(db, world["org"].id).success
    db.expire_all()


def test_r1_recorded_line_turning_needs_rate_is_orphaned_for_review(flask_app, world, db):  # noqa: F811
    org = world["org"]
    _, pl, txn_id, lid = _sync_purchase(world, db, "90")
    client = user_client(db, flask_app, org)
    _assert_success(_record(client, pl.id, [_row("FX Juniper", 2, 90)]))
    _resync_raw(world, db, txn_id, lid, "90", currency="AUD")
    (alloc,) = _allocations(db, org.id, pl.id)
    line_row = db.get(PurchaseLine, pl.id)
    assert alloc.status == "orphaned" and line_row.review_reason == "amount_changed"
    assert lot_cost(db, org.id, alloc.inventory_item_id)["status"] == "estimated"


def test_r1_rescale_with_not_stock_never_exceeds_the_line(flask_app, world, db):  # noqa: F811
    org = world["org"]
    _, pl, txn_id, lid = _sync_purchase(world, db, "2")
    client = user_client(db, flask_app, org)
    _assert_success(_record(client, pl.id, [_row("Half", 1, 1)], rest="not_stock"))
    _resync_raw(world, db, txn_id, lid, "0.0001")
    line_row = db.get(PurchaseLine, pl.id)
    used = sum(D(str(a.amount)) for a in _allocations(db, org.id, pl.id)) + D(str(line_row.not_stock_amount))
    assert used == D("0.0001")


@pytest.mark.parametrize("keep_first", [False, True])
def test_r1_voided_then_active_again_is_restored(flask_app, world, db, keep_first):  # noqa: F811
    org = world["org"]
    _, pl, txn_id, lid = _sync_purchase(world, db, "90")
    client = user_client(db, flask_app, org)
    _assert_success(_record(client, pl.id, [_row("Back Again", 2, 90)]))
    _resync_raw(world, db, txn_id, lid, "90", status="DELETED")
    if keep_first:
        _assert_success(
            client.post(
                f"{API}/purchases/{pl.id}/review", json={"action": "keep"}, headers={"Idempotency-Key": str(uuid4())}
            )
        )
    _resync_raw(world, db, txn_id, lid, "90")
    (alloc,) = _allocations(db, org.id, pl.id)
    line_row = db.get(PurchaseLine, pl.id)
    assert alloc.status == "active" and line_row.review_reason is None and line_row.state == "recorded"
    assert lot_cost(db, org.id, alloc.inventory_item_id)["status"] == "actual"


def test_r1_voided_refund_makes_the_lot_estimated(flask_app, world, db):  # noqa: F811
    org = world["org"]
    item = lot(db, org.id, "Refunded Juniper", 2, "kg")
    price(db, org.id, item.id, 90, 2)
    _, pl, txn_id, lid = _sync_purchase(world, db, "20", kind="RECEIVE")
    client = user_client(db, flask_app, org)
    response = client.post(
        f"{API}/purchases/{pl.id}/refund",
        json={"lots": [{"inventory_item_id": str(item.id), "amount": "-20"}]},
        headers={"Idempotency-Key": str(uuid4())},
    )
    _assert_success(response)
    cost = lot_cost(db, org.id, item.id)
    assert (D(cost["unit_cost"]), cost["status"]) == (D("35"), "actual")
    _resync_raw(world, db, txn_id, lid, "20", kind="RECEIVE", status="DELETED")
    assert lot_cost(db, org.id, item.id)["status"] == "estimated"


def test_r1_editing_an_orphaned_allocation_keeps_it_orphaned(flask_app, world, db):  # noqa: F811
    org = world["org"]
    _, pl, txn_id, lid = _sync_purchase(world, db, "90")
    client = user_client(db, flask_app, org)
    _assert_success(_record(client, pl.id, [_row("Gone Juniper", 2, 90)]))
    _resync_raw(world, db, txn_id, lid, "90", status="DELETED")
    (alloc,) = _allocations(db, org.id, pl.id)
    response = client.put(
        f"{API}/purchases/{pl.id}/allocations", json={"allocations": [{"id": str(alloc.id), "amount": "80"}]}
    )
    _assert_success(response)
    db.expire_all()
    assert db.get(PurchaseAllocation, alloc.id).status == "orphaned"


def test_r1_the_same_lot_twice_is_400_not_500(flask_app, world, db):  # noqa: F811
    org = world["org"]
    item = lot(db, org.id, "Twice", 2, "kg", purchase_date=PURCHASE_DATE)
    _, pl, _, _ = _sync_purchase(world, db, "90")
    client = user_client(db, flask_app, org)
    lots = [{"inventory_item_id": str(item.id), "quantity": "1", "amount": "40"}] * 2
    assert _link(client, pl.id, lots).status_code == 400
    assert _allocations(db, org.id, pl.id) == []


def test_r1_a_zero_dollar_allocation_counts_as_recorded(flask_app, world, db):  # noqa: F811
    org = world["org"]
    _, pl, _, _ = _sync_purchase(world, db, "90")
    client = user_client(db, flask_app, org)
    _assert_success(_record(client, pl.id, [_row("Free sample", 1, 0)], rest="not_stock"))
    assert db.get(PurchaseLine, pl.id).state == "recorded"


def test_r1_review_unlink_replays_with_the_same_key(flask_app, world, db):  # noqa: F811
    org = world["org"]
    _, pl, txn_id, lid = _sync_purchase(world, db, "90")
    client = user_client(db, flask_app, org)
    _assert_success(_record(client, pl.id, [_row("Replay", 2, 90)]))
    _resync_raw(world, db, txn_id, lid, "99")
    key = str(uuid4())
    first = client.post(f"{API}/purchases/{pl.id}/review", json={"action": "unlink"}, headers={"Idempotency-Key": key})
    again = client.post(f"{API}/purchases/{pl.id}/review", json={"action": "unlink"}, headers={"Idempotency-Key": key})
    assert first.status_code == 200 and again.status_code == 200
    assert again.headers.get("Idempotent-Replay") == "true"


def test_r1_review_on_a_needs_rate_line_is_400(flask_app, world, db):  # noqa: F811
    org = world["org"]
    _, pl, txn_id, lid = _sync_purchase(world, db, "90")
    client = user_client(db, flask_app, org)
    _assert_success(_record(client, pl.id, [_row("Rate", 2, 90)]))
    _resync_raw(world, db, txn_id, lid, "90", currency="AUD")
    assert db.get(PurchaseLine, pl.id).review_reason is not None
    response = client.post(
        f"{API}/purchases/{pl.id}/review", json={"action": "keep"}, headers={"Idempotency-Key": str(uuid4())}
    )
    assert response.status_code == 400


@pytest.mark.parametrize("amount", ["abc", "NaN", "-1e30", "-0.00001", "20", None])
def test_r1_bad_refund_amounts_are_400(flask_app, world, db, amount):  # noqa: F811
    org = world["org"]
    item = lot(db, org.id, "Refund target", 2, "kg")
    _, pl, _, _ = _sync_purchase(world, db, "20", kind="RECEIVE")
    client = user_client(db, flask_app, org)
    response = client.post(
        f"{API}/purchases/{pl.id}/refund",
        json={"lots": [{"inventory_item_id": str(item.id), "amount": amount}]},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 400, response.get_json()
