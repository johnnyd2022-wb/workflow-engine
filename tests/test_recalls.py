"""GL-P03: a recall (or drill) on operational cases: scope, holds, notices, acks, recovery, closure."""
# ruff: noqa: F811 -- pytest fixtures re-exported from tests/test_operational_cases.py

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from app.core.db.models.inventory_item import InventoryItem
from app.core.db.models.lot_hold import LotHold
from app.core.db.models.user import UserRole
from app.core.domain.inventory_quantity_guard import InventoryQuantityWriteReason, allow_inventory_quantity_write
from app.core.services import lot_holds
from app.features.crm.models.sales_fifo_allocation import SalesFifoAllocation
from app.features.crm.models.xero_contact import XeroContact
from app.features.crm.models.xero_invoice import XeroInvoice
from app.features.recalls.models import Recall, RecallContact
from tests.factories import UserFactory
from tests.test_operational_cases import (  # noqa: F401 -- fixture re-exports
    _idem,
    _login,
    admin_client,
    admin_user,
    db,
    flask_app,
    org_a,
    org_b,
    org_b_client,
    org_b_user,
    owner_client,
    owner_user,
    verifier_client,
    verifier_user,
)

DUE = (datetime.now(UTC) + timedelta(days=3)).isoformat()


@pytest.fixture(autouse=True)
def cleanup(db, org_a, org_b):
    yield
    db.rollback()
    for org in (org_a, org_b):
        db.query(RecallContact).filter(RecallContact.org_id == org.id).delete(synchronize_session=False)
        db.query(Recall).filter(Recall.org_id == org.id).delete(synchronize_session=False)
        db.query(LotHold).filter(LotHold.org_id == org.id).update({LotHold.source_hold_id: None})
        db.query(LotHold).filter(LotHold.org_id == org.id).delete(synchronize_session=False)
        for model in (SalesFifoAllocation, XeroInvoice, XeroContact):
            db.query(model).filter(model.org_id == org.id).delete(synchronize_session=False)
    db.commit()


def _lot(db, org_id, name="Navy Gin batch 12", quantity="40"):
    with allow_inventory_quantity_write(InventoryQuantityWriteReason.REPOSITORY_CREATE):
        item = InventoryItem(
            org_id=org_id, name=name, quantity=Decimal(quantity), unit="each", inventory_type="final_product"
        )
        db.add(item)
        db.commit()
    return item


def _sold(db, org_id, lot, customer, qty, invoice_number):
    contact = db.query(XeroContact).filter(XeroContact.org_id == org_id, XeroContact.name == customer).one_or_none()
    if contact is None:
        contact = XeroContact(org_id=org_id, xero_contact_id=f"c-{uuid4()}", name=customer)
        db.add(contact)
        db.flush()
    inv_id = f"inv-{uuid4()}"
    db.add(
        XeroInvoice(
            org_id=org_id,
            xero_tenant_id="tenant",
            xero_invoice_id=inv_id,
            invoice_number=invoice_number,
            contact_id=contact.id,
            invoice_type="ACCREC",
            status="AUTHORISED",
        )
    )
    db.add(
        SalesFifoAllocation(
            org_id=org_id,
            xero_invoice_id=inv_id,
            xero_line_key=f"{inv_id}:1",
            inventory_item_id=lot.id,
            product_name="Navy Gin 700ml",
            quantity=Decimal(qty),
            unit="each",
        )
    )
    db.commit()
    return contact


@pytest.fixture
def world(db, org_a):
    lot = _lot(db, org_a.id)
    _sold(db, org_a.id, lot, "Kererū Bottle Store", "12", "INV-0101")
    _sold(db, org_a.id, lot, "Kererū Bottle Store", "6", "INV-0102")
    _sold(db, org_a.id, lot, "Harbour Bar", "4", "INV-0103")
    return lot


def _open(client, lot, **extra):
    body = {"lot_id": str(lot.id), "reason": "Glass fragments found in one bottle", "risk": "health", "due_at": DUE}
    body.update(extra)
    return client.post("/api/core/recalls", json=body)


def _case_to(client, case_id, version, status, **fields):
    return client.post(
        f"/api/core/cases/{case_id}/transitions",
        json={"target_status": status, "expected_version": version, **fields},
        headers=_idem(),
    )


# --- opening ---------------------------------------------------------------------------------------


def test_opening_a_recall_scopes_customers_and_holds_the_stock(db, org_a, admin_client, world):
    resp = _open(admin_client, world)
    assert resp.status_code == 201, resp.get_json()
    recall = resp.get_json()["recall"]
    assert recall["case"]["title"] == "Recall: Navy Gin batch 12"
    assert recall["case"]["source_type"] == "recall"
    assert [(c["customer_name"], c["quantity_supplied"], c["invoices"]) for c in recall["contacts"]] == [
        ("Harbour Bar", "4", ["INV-0103"]),
        ("Kererū Bottle Store", "18", ["INV-0101", "INV-0102"]),
    ]
    assert recall["progress"] == {
        "customers": 2,
        "acknowledged": 0,
        "unreachable": 0,
        "supplied": "22",
        "accounted": "0",
        "complete": False,
        "blockers": [
            "Harbour Bar hasn't acknowledged the notice (Navy Gin 700ml)",
            "4 each of Navy Gin 700ml at Harbour Bar not yet recovered or disposed of",
            "Kererū Bottle Store hasn't acknowledged the notice (Navy Gin 700ml)",
            "18 each of Navy Gin 700ml at Kererū Bottle Store not yet recovered or disposed of",
        ],
    }
    held = lot_holds.open_holds(db, org_a.id, [world.id])
    assert held[world.id].reason == "Recall: Glass fragments found in one bottle"
    assert recall["holds_placed"] == 1


def test_lots_made_from_it_are_held_too_and_sold_out_ones_are_not(db, org_a, admin_client, world, monkeypatch):
    from app.core.backend import dagtraversal

    child = _lot(db, org_a.id, name="Navy Gin gift pack", quantity="5")
    empty = _lot(db, org_a.id, name="Navy Gin minis", quantity="0")
    nodes = [
        {"id": str(x.id), "name": x.name, "quantity": str(x.quantity), "unit": "each"} for x in (world, child, empty)
    ]
    monkeypatch.setattr(dagtraversal, "trace_forward", lambda *a, **k: {"items": nodes, "connections": []})
    recall = _open(admin_client, world).get_json()["recall"]
    held = lot_holds.open_holds(db, org_a.id)
    assert set(held) == {world.id, child.id}
    assert recall["holds_placed"] == 2 and len(recall["lots_in_scope"]) == 3


def test_a_drill_holds_nothing_and_says_drill_everywhere(db, org_a, admin_client, world):
    recall = _open(admin_client, world, is_drill=True).get_json()["recall"]
    assert recall["is_drill"] is True and recall["case"]["title"] == "Recall drill: Navy Gin batch 12"
    assert lot_holds.open_holds(db, org_a.id) == {}
    contact = recall["contacts"][0]
    notice = admin_client.get(f"/api/core/recalls/{recall['id']}/contacts/{contact['id']}/notice").get_json()
    assert notice["sent"] is False
    assert notice["notice"]["subject"].startswith("[DRILL] ")
    assert notice["notice"]["body"].startswith("THIS IS A RECALL DRILL")


def test_one_open_recall_per_lot_and_bad_input(admin_client, world):
    assert _open(admin_client, world).status_code == 201
    dup = _open(admin_client, world)
    assert dup.status_code == 409 and "already has an open recall" in dup.get_json()["error"]
    assert _open(admin_client, world, risk="vibes").status_code == 400
    assert _open(admin_client, world, reason="  ").status_code == 400
    assert _open(admin_client, world, due_at="2020-01-01T00:00:00+00:00").status_code == 400
    assert _open(admin_client, world, lot_id=str(uuid4())).status_code == 404
    assert _open(admin_client, world, lot_id="nope").status_code == 404


def test_the_notice_is_drafted_with_what_they_received(admin_client, world):
    recall = _open(admin_client, world).get_json()["recall"]
    kb = next(c for c in recall["contacts"] if c["customer_name"] == "Kererū Bottle Store")
    notice = admin_client.get(f"/api/core/recalls/{recall['id']}/contacts/{kb['id']}/notice").get_json()["notice"]
    assert notice["subject"] == "Product recall: Navy Gin 700ml"
    for words in (
        "Dear Kererū Bottle Store",
        "18 each",
        "INV-0101, INV-0102",
        "a possible risk to health",
        "Glass fragments",
    ):
        assert words in notice["body"]


# --- working it and closing it ----------------------------------------------------------------------


def test_the_case_resolves_only_when_every_customer_is_accounted_for(db, org_a, admin_client, verifier_client, world):
    recall = _open(admin_client, world).get_json()["recall"]
    rid, case_id = recall["id"], recall["case"]["id"]
    assert _case_to(admin_client, case_id, 1, "acknowledged").status_code == 200
    assert _case_to(admin_client, case_id, 2, "in_progress").status_code == 200
    resolve = dict(cause="material", action_taken="Recalled the batch", outcome="All stock recovered or destroyed")
    blocked = _case_to(admin_client, case_id, 3, "resolved", **resolve)
    assert blocked.status_code == 409 and blocked.get_json()["error_code"] == "recall_incomplete"
    assert len(blocked.get_json()["blockers"]) == 4

    hb, kb = sorted(recall["contacts"], key=lambda c: c["customer_name"])
    base = f"/api/core/recalls/{rid}/contacts"
    assert admin_client.post(f"{base}/{kb['id']}/notice-sent", json={"channel": "email"}).status_code == 200
    ack = admin_client.post(
        f"{base}/{kb['id']}/acknowledged", json={"by": "Aroha (manager)", "note": "Pulled from shelf"}
    )
    assert ack.status_code == 200 and ack.get_json()["contact"]["done"] is False
    q = admin_client.post(f"{base}/{kb['id']}/quantities", json={"recovered": "15", "disposed": "3"})
    assert q.status_code == 200 and q.get_json()["contact"]["done"] is True
    assert admin_client.post(f"{base}/{hb['id']}/quantities", json={"recovered": "5"}).status_code == 400
    unreachable = admin_client.post(
        f"{base}/{hb['id']}/unreachable", json={"note": "Closed down; three calls, two emails"}
    )
    assert unreachable.status_code == 200

    # Unreachable is an answer, not a pass for the stock: Harbour Bar's 4 are still unaccounted for.
    progress = admin_client.get(f"/api/core/recalls/{rid}").get_json()["recall"]["progress"]
    assert progress["complete"] is False and progress["accounted"] == "18" and progress["unreachable"] == 1
    assert progress["blockers"] == [
        "4 each of Navy Gin 700ml at Harbour Bar (unreachable) not accounted for: "
        "record what came back, or what can't be recovered"
    ]
    still = _case_to(admin_client, case_id, 3, "resolved", **resolve)
    assert still.status_code == 409 and still.get_json()["error_code"] == "recall_incomplete"
    lost = admin_client.post(f"{base}/{hb['id']}/quantities", json={"recovered": "0", "unrecoverable": "4"})
    assert lost.status_code == 200 and lost.get_json()["contact"]["unrecoverable_qty"] == "4"
    progress = admin_client.get(f"/api/core/recalls/{rid}").get_json()["recall"]["progress"]
    assert progress["complete"] is True and progress["accounted"] == "22"
    assert _case_to(admin_client, case_id, 3, "resolved", **resolve).status_code == 200
    # Closed: the customer record is frozen.
    assert admin_client.post(f"{base}/{kb['id']}/quantities", json={"recovered": "18"}).status_code == 409
    # Independent verification, as for every case.
    verified = _case_to(verifier_client, case_id, 4, "verified", verification_note="Checked the returns log")
    assert verified.status_code == 200 and verified.get_json()["case"]["status"] == "verified"


def test_unreachable_is_refused_after_an_acknowledgement_and_refresh_does_not_apply(admin_client, world):
    recall = _open(admin_client, world).get_json()["recall"]
    c = recall["contacts"][0]
    base = f"/api/core/recalls/{recall['id']}/contacts/{c['id']}"
    assert admin_client.post(f"{base}/acknowledged", json={"by": "Sam"}).status_code == 200
    assert admin_client.post(f"{base}/unreachable", json={"note": "x"}).status_code == 409
    assert admin_client.post(f"{base}/acknowledged", json={"by": ""}).status_code == 400
    future = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    assert admin_client.post(f"{base}/notice-sent", json={"channel": "email", "sent_at": future}).status_code == 400
    assert (
        admin_client.post(f"{base}/notice-sent", json={"channel": "email", "sent_at": "2026-11-01"}).status_code == 400
    )
    refresh = admin_client.post(
        f"/api/core/cases/{recall['case']['id']}/refresh-source", json={"expected_version": 1}, headers=_idem()
    )
    assert refresh.status_code in (404, 405, 409)
    if refresh.status_code == 409:
        assert refresh.get_json()["error_code"] == "not_applicable"


# --- who and which business --------------------------------------------------------------------------


def test_opening_needs_compliance_manage_but_sales_can_work_the_list(db, org_a, flask_app, admin_client, world):
    member = UserFactory(org_id=org_a.id, email=f"r-member-{uuid4().hex}@example.test", role=UserRole.MEMBER)
    sales = UserFactory(org_id=org_a.id, email=f"r-sales-{uuid4().hex}@example.test", role=UserRole.SALES)
    db.commit()
    assert _open(_login(flask_app, member), world).status_code == 403
    recall = _open(admin_client, world).get_json()["recall"]
    sales_client = _login(flask_app, sales)
    assert sales_client.get(f"/api/core/recalls/{recall['id']}").status_code == 200
    c = recall["contacts"][0]
    assert (
        sales_client.post(
            f"/api/core/recalls/{recall['id']}/contacts/{c['id']}/acknowledged", json={"by": "Jo"}
        ).status_code
        == 200
    )


def test_another_business_sees_none_of_it(db, org_b, admin_client, org_b_client, world):
    recall = _open(admin_client, world).get_json()["recall"]
    c = recall["contacts"][0]
    assert org_b_client.get("/api/core/recalls").get_json()["recalls"] == []
    assert org_b_client.get(f"/api/core/recalls/{recall['id']}").status_code == 404
    assert org_b_client.get(f"/api/core/recalls/{recall['id']}/contacts/{c['id']}/notice").status_code == 404
    assert (
        org_b_client.post(
            f"/api/core/recalls/{recall['id']}/contacts/{c['id']}/acknowledged", json={"by": "x"}
        ).status_code
        == 404
    )
    assert _open(org_b_client, world).status_code == 404


def test_a_corrupt_nan_sale_line_refuses_the_recall_and_nan_cannot_be_stored(db, org_a, admin_client, world):
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    db.execute(
        text("UPDATE crm_sales_fifo_allocations SET quantity = 'NaN' WHERE org_id = :org AND quantity = 4"),
        {"org": org_a.id},
    )
    db.commit()
    db.expire_all()
    # Never silently drop a customer from a recall: refuse, naming the sale line to fix.
    refused = _open(admin_client, world)
    assert refused.status_code == 409
    assert "INV-0103" in refused.get_json()["error"] and "Harbour Bar" in refused.get_json()["error"]
    db.execute(
        text("UPDATE crm_sales_fifo_allocations SET quantity = 4 WHERE org_id = :org AND quantity = 'NaN'"),
        {"org": org_a.id},
    )
    db.commit()
    db.expire_all()
    recall = _open(admin_client, world).get_json()["recall"]
    assert [c["customer_name"] for c in recall["contacts"]] == ["Harbour Bar", "Kererū Bottle Store"]
    contact_id = recall["contacts"][0]["id"]
    with pytest.raises(IntegrityError):
        db.execute(text("UPDATE recall_contacts SET recovered_qty = 'NaN' WHERE id = :id"), {"id": contact_id})
        db.commit()
    db.rollback()


def test_only_an_unreachable_customer_can_have_stock_written_off(admin_client, world):
    recall = _open(admin_client, world).get_json()["recall"]
    c = recall["contacts"][0]
    resp = admin_client.post(
        f"/api/core/recalls/{recall['id']}/contacts/{c['id']}/quantities", json={"recovered": "0", "unrecoverable": "1"}
    )
    assert resp.status_code == 400 and "couldn't reach" in resp.get_json()["error"]
