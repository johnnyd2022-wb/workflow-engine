"""GL-P08 part 2: a contract order's goods leaving the CCA.

The order's duty responsibility decides: customer-liable goods are a transfer to the
customer's CCA (left out of duty, listed in Customs → Transfers until the customer
acknowledges receipt); producer-liable goods are a removal on the excise draft. Either way
the stock comes off the lots the order's batches made, and nothing else.
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from app.core.db.models.inventory_item import InventoryItem
from app.features.compliant.modules.nz_alcohol import cca_transfers, excise
from app.features.contract_manufacturing.models import (
    ContractCustomer,
    ContractDispatch,
    ContractDispatchLine,
    ContractOrder,
    ContractOrderExecution,
    ContractOrderLine,
)
from tests.factories import ExecutionFactory, ProcessFactory
from tests.test_compliant_routes import _admin_client, flask_app  # noqa: F401 -- fixture re-export
from tests.test_excise import GIN, world  # noqa: F401 -- fixture re-export

API = "/api/core/contract-orders"


@pytest.fixture
def contract(world):  # noqa: F811
    db, org = world["db"], world["org"]
    customer = ContractCustomer(org_id=org.id, name="Kapiti Craft Spirits")
    db.add(customer)
    db.flush()
    process = ProcessFactory(org_id=org.id, name="Contract gin")
    made = []

    def order(duty="customer_underbond", cca="LMA-KAP-0210", status="confirmed", bottles=120):
        row = ContractOrder(
            org_id=org.id,
            customer_id=customer.id,
            reference=f"CO-{uuid4().hex[:6]}",
            due_date=date(2026, 8, 30),
            status=status,
            duty_responsibility=duty,
            customer_cca_reference=cca,
        )
        db.add(row)
        db.flush()
        line = ContractOrderLine(
            org_id=org.id,
            order_id=row.id,
            product_name="Gin",
            quantity=bottles,
            unit="bottles",
            materials_source="producer",
        )
        db.add(line)
        db.flush()
        batch = ExecutionFactory(org_id=org.id, process_id=process.id)
        db.add(ContractOrderExecution(org_id=org.id, order_id=row.id, line_id=line.id, execution_id=batch.id))
        lot = world["repo"].create_inventory_item(
            org_id=org.id,
            name=GIN,
            quantity=str(bottles),
            unit="bottles",
            inventory_type="final_product",
            supplier_batch_number=f"K{len(made) + 1}",
            extra_data={"abv_percent": "44"},
            source_execution_id=batch.id,
        )
        db.commit()
        made.append(row)
        return row, lot

    yield {**world, "order": order, "customer": customer}
    db.rollback()
    for model in (ContractDispatchLine, ContractDispatch, ContractOrderExecution, ContractOrderLine, ContractOrder):
        db.query(model).filter(model.org_id == org.id).delete(synchronize_session=False)
    db.query(ContractCustomer).filter(ContractCustomer.org_id == org.id).delete(synchronize_session=False)
    db.commit()


def _dispatch(client, order, lot, qty="48", moved_at="2026-08-12T10:00"):
    return client.post(
        f"{API}/{order.id}/dispatches",
        json={
            "moved_at": moved_at,
            "carrier": "Mainfreight",
            "consignment_note": "MF-1",
            "lines": [{"inventory_item_id": str(lot.id), "quantity": qty}],
        },
    )


def _stock(db, lot):
    db.expire_all()
    return Decimal(str(db.get(InventoryItem, lot.id).quantity))


def _draft(w):
    return excise.draft(w["db"], w["org"].id, date(2026, 8, 1), "monthly", today=date(2026, 10, 1))


def test_a_customer_liable_dispatch_is_a_transfer_to_their_cca(contract):
    order, lot = contract["order"]()
    resp = _dispatch(contract["client"], order, lot)
    assert resp.status_code == 201, resp.get_json()
    d = resp.get_json()
    assert d["treatment"] == "cca_transfer" and d["destination_cca"] == "LMA-KAP-0210"
    assert d["status"] in ("awaiting_receipt", "receipt_overdue")
    assert _stock(contract["db"], lot) == 72

    draft = _draft(contract)
    assert Decimal(draft["total_lal"]) == 0  # not entered for duty
    (moved,) = draft["cca_transfers"]
    assert moved["destination"]["cca_code"] == "LMA-KAP-0210" and moved["quantity"] == "48"
    assert Decimal(moved["lal"]) == Decimal("14.784")  # 48 x 0.7 L x 44%, for the register
    # It is in the Transfers register, with somewhere to record the customer's receipt.
    (row,) = cca_transfers.register(contract["db"], contract["org"].id, since=date(2026, 8, 1))["transfers"]
    assert row["kind"] == "contract" and row["receipt_url"].endswith(f"/dispatches/{d['id']}/receipt")


def test_a_producer_liable_dispatch_is_a_removal_for_duty(contract):
    order, lot = contract["order"](duty="producer_licensee", cca=None)
    resp = _dispatch(contract["client"], order, lot)
    assert resp.status_code == 201 and resp.get_json()["treatment"] == "removal"
    draft = _draft(contract)
    assert Decimal(draft["total_lal"]) == Decimal("14.784")
    (line,) = draft["lines"]
    assert [r["kind"] for r in line["removals"]] == ["contract_dispatch"]
    assert draft["cca_transfers"] == []
    assert cca_transfers.register(contract["db"], contract["org"].id, since=date(2026, 8, 1))["transfers"] == []


def test_the_day_it_left_is_the_nz_day(contract):
    order, lot = contract["order"](duty="producer_licensee", cca=None)
    # 00:30 on 1 September NZ time is still 31 August in UTC: it belongs to September's entry.
    assert _dispatch(contract["client"], order, lot, moved_at="2026-09-01T00:30").status_code == 201
    assert Decimal(_draft(contract)["total_lal"]) == 0
    september = excise.draft(contract["db"], contract["org"].id, date(2026, 9, 1), "monthly", today=date(2026, 10, 1))
    assert Decimal(september["total_lal"]) == Decimal("14.784")


def test_only_the_orders_own_lots_can_leave_and_never_more_than_is_there(contract):
    order, lot = contract["order"]()
    _other_order, other_lot = contract["order"]()
    stranger = contract["lot"]("S1", 50)  # house stock, not made for any order
    client = contract["client"]
    assert _dispatch(client, order, other_lot).status_code == 400
    assert _dispatch(client, order, stranger).status_code == 400
    too_many = _dispatch(client, order, lot, qty="121")
    assert too_many.status_code == 400 and "only has" in too_many.get_json()["error"]
    assert _dispatch(client, order, lot, qty="1.5").status_code == 400  # bottles are whole
    assert _stock(contract["db"], lot) == 120 and _stock(contract["db"], other_lot) == 120
    assert contract["db"].query(ContractDispatch).filter(ContractDispatch.org_id == contract["org"].id).count() == 0


def test_a_draft_order_cannot_be_dispatched(contract):
    order, lot = contract["order"](status="draft")
    assert _dispatch(contract["client"], order, lot).status_code == 409
    assert _stock(contract["db"], lot) == 120


def test_the_customers_receipt_closes_the_transfer(contract):
    order, lot = contract["order"]()
    d = _dispatch(contract["client"], order, lot).get_json()
    url = f"{API}/{order.id}/dispatches/{d['id']}/receipt"
    early = contract["client"].put(url, json={"received_on": "2026-08-11", "receipt_reference": "Docket"})
    assert early.status_code == 400 and "before they left" in early.get_json()["error"]
    no_evidence = contract["client"].put(url, json={"received_on": "2026-08-13"})
    assert no_evidence.status_code == 400
    ok = contract["client"].put(url, json={"received_on": "2026-08-13", "receipt_reference": "Signed docket K-77"})
    assert ok.status_code == 200 and ok.get_json()["status"] == "received"


def test_a_removal_has_no_receipt(contract):
    order, lot = contract["order"](duty="producer_licensee", cca=None)
    d = _dispatch(contract["client"], order, lot).get_json()
    resp = contract["client"].put(
        f"{API}/{order.id}/dispatches/{d['id']}/receipt", json={"received_on": "2026-08-13", "receipt_reference": "x"}
    )
    assert resp.status_code == 409


def test_dispatching_takes_stock_so_it_needs_stock_permission():
    from app.core.db.models.user import UserRole
    from app.core.security.access_policy import ROLE_PERMISSIONS, requirement_for

    assert requirement_for("contracts.dispatch_order", "POST") == "inventory.adjust"
    assert "inventory.adjust" not in ROLE_PERMISSIONS[UserRole.SALES]


def test_another_org_cannot_dispatch_or_see_the_order(contract, db, flask_app):  # noqa: F811
    order, lot = contract["order"]()
    other_org, other = _admin_client(db, flask_app)
    try:
        assert _dispatch(other, order, lot).status_code == 404
        assert other.get(f"{API}/{order.id}/dispatches").status_code == 404
        assert _stock(contract["db"], lot) == 120
    finally:
        from tests.dag_traversal_helpers import clear_org_synthetic_data

        clear_org_synthetic_data(db, other_org.id)
