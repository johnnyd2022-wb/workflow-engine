"""Live-cogs 8.1f-1: bills and supplier credits from Xero, through the purchases pipeline.

Spec .agents/specs/live-cogs.md, "8.1f-1 build contract" (AC44, AC98-AC101). Written before the code.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from xero_python.accounting import Contact, CreditNote, CurrencyCode, Invoice, LineAmountTypes

from app.features.costing.models import PurchaseAllocation, PurchaseDocument, PurchaseLine
from app.features.costing.purchase_sources import nz_today
from tests.costing_helpers import user_client
from tests.test_compliant_routes import flask_app  # noqa: F401 -- fixture re-export
from tests.test_costing_allocations import (  # noqa: F401 -- fixture re-export
    _assert_success,
    _record,
    _row,
    _set_start_date,
    world,
)
from tests.test_costing_purchases import line, sync

API = "/api/core/costing"
D = Decimal
ON = nz_today() - timedelta(days=2)


def bill(lines, *, status="AUTHORISED", bill_id=None, number="INV-0042", payee="Tanner Bros", on=ON, amounts="NoTax"):
    return Invoice(
        type="ACCPAY",
        invoice_id=bill_id or str(uuid4()),
        invoice_number=number,
        reference="PO 77",
        contact=Contact(contact_id=str(uuid4()), name=payee),
        date=on,
        status=status,
        line_amount_types=LineAmountTypes(amounts),
        line_items=lines,
        currency_code=CurrencyCode("NZD"),
        updated_date_utc=datetime.now(UTC),
    )


def credit(lines, *, status="AUTHORISED", credit_id=None, payee="Tanner Bros", on=ON):
    return CreditNote(
        type="ACCPAYCREDIT",
        credit_note_id=credit_id or str(uuid4()),
        credit_note_number="CN-9",
        contact=Contact(contact_id=str(uuid4()), name=payee),
        date=on,
        status=status,
        line_amount_types=LineAmountTypes("NoTax"),
        line_items=lines,
        currency_code=CurrencyCode("NZD"),
        updated_date_utc=datetime.now(UTC),
    )


def _bill_line(amount, *, qty=None, item_code=None, description="Juniper berries 10 kg", key=None):
    li = line("310", amount, line_item_id=key or str(uuid4()), description=description, qty=qty)
    li.item_code = item_code
    return li


def _docs(db, org_id, source=None):
    db.expire_all()
    q = db.query(PurchaseDocument).filter(PurchaseDocument.org_id == org_id)
    if source:
        q = q.filter(PurchaseDocument.source == source)
    return q.all()


def _lines(db, doc):
    return db.query(PurchaseLine).filter(PurchaseLine.document_id == doc.id).all()


def _sync(world, db, *, bills=(), credits=()):  # noqa: F811
    _set_start_date(db, world["org"].id)
    world["fake"].bills = list(bills)
    world["fake"].bill_credits = list(credits)
    assert sync(db, world["org"].id).success
    db.expire_all()


def test_ac98_paid_bill_and_credit_sync_with_their_own_source(world, db):  # noqa: F811
    org = world["org"]
    _sync(world, db, bills=[bill([_bill_line("120")], status="PAID")], credits=[credit([_bill_line("20")])])
    (b,) = _docs(db, org.id, "xero_bill")
    (c,) = _docs(db, org.id, "xero_bill_credit")
    assert (b.kind, b.status) == ("spend", "active") and "INV-0042" in b.reference
    assert c.kind == "refund"
    assert D(str(_lines(db, b)[0].amount_ex_tax)) == D("120")
    assert D(str(_lines(db, c)[0].amount_ex_tax)) == D("-20")


def test_ac98_bank_transaction_and_bill_with_the_same_id_never_collide(world, db):  # noqa: F811
    from tests.test_costing_purchases import txn

    org = world["org"]
    shared = str(uuid4())
    world["fake"].transactions = [
        txn([line("310", "50", line_item_id=str(uuid4()))], txn_id=shared, on=ON, amounts="NoTax")
    ]
    _sync(world, db, bills=[bill([_bill_line("70")], bill_id=shared)])
    assert len(_docs(db, org.id, "xero_bank")) == 1 and len(_docs(db, org.id, "xero_bill")) == 1


@pytest.mark.parametrize("status", ["DRAFT", "SUBMITTED"])
def test_ac44_draft_and_submitted_bills_are_not_synced(world, db, status):  # noqa: F811
    _sync(world, db, bills=[bill([_bill_line("120")], status=status)])
    assert _docs(db, world["org"].id, "xero_bill") == []


def test_ac44_ac101_bill_quantity_and_item_code_prefill_a_row(flask_app, world, db):  # noqa: F811
    org = world["org"]
    _sync(world, db, bills=[bill([_bill_line("120", qty="10", item_code="JUN-10")])])
    (doc,) = _docs(db, org.id, "xero_bill")
    (row,) = _lines(db, doc)
    assert (D(str(row.quantity)), row.item_code) == (D("10"), "JUN-10")
    client = user_client(db, flask_app, org)
    body = client.get(f"{API}/purchases?tab=to_record").get_json()
    card = next(c for c in body["cards"] if c["line_id"] == str(row.id))
    assert card["document"]["source"] == "xero_bill"
    assert card["prefill"]["source"] == "none"
    (pre,) = card["prefill"]["rows"]
    assert D(pre["quantity"]) == D("10") and D(pre["amount"]) == D("120")
    assert pre["name"] == "Juniper berries 10 kg"


def test_ac99_recorded_bill_voided_in_xero_goes_to_review(flask_app, world, db):  # noqa: F811
    org = world["org"]
    key, bid = str(uuid4()), str(uuid4())
    _sync(world, db, bills=[bill([_bill_line("120", qty="10", key=key)], bill_id=bid)])
    (doc,) = _docs(db, org.id, "xero_bill")
    (row,) = _lines(db, doc)
    client = user_client(db, flask_app, org)
    _assert_success(_record(client, row.id, [_row("Juniper berries", 10, 120)]))
    _sync(world, db, bills=[bill([_bill_line("120", qty="10", key=key)], bill_id=bid, status="VOIDED")])
    db.expire_all()
    assert db.get(PurchaseLine, row.id).review_reason == "deleted_in_xero"
    (alloc,) = db.query(PurchaseAllocation).filter(PurchaseAllocation.purchase_line_id == row.id).all()
    assert alloc.status == "orphaned"


def test_ac99_stored_bill_moved_back_to_draft_is_treated_as_voided(world, db):  # noqa: F811
    org = world["org"]
    key, bid = str(uuid4()), str(uuid4())
    _sync(world, db, bills=[bill([_bill_line("120", key=key)], bill_id=bid)])
    _sync(world, db, bills=[bill([_bill_line("120", key=key)], bill_id=bid, status="DRAFT")])
    (doc,) = _docs(db, org.id, "xero_bill")
    assert doc.status == "voided"


def test_ac100_purchases_phase_fetches_bills_with_the_cursor_rules(world, db):  # noqa: F811
    fake = world["fake"]
    _sync(world, db)
    first = [c[1] for c in fake.calls if c[0] in ("bills", "bill_credits")]
    assert len(first) == 2 and all(c["modified_after"] is None and c["from_date"] is not None for c in first)
    fake.calls.clear()
    _sync(world, db)
    second = [c[1] for c in fake.calls if c[0] in ("bills", "bill_credits")]
    assert len(second) == 2 and all(c["modified_after"] is not None for c in second)


def test_ac100_historical_run_fetches_bills_for_the_range(flask_app, world, db):  # noqa: F811
    org, fake = world["org"], world["fake"]
    _sync(world, db)
    fake.calls.clear()
    old = date.today() - timedelta(days=200)
    fake.bills = [bill([_bill_line("55")], on=old)]
    client = user_client(db, flask_app, org)
    frm, to = (date.today() - timedelta(days=300)).isoformat(), date.today().isoformat()
    run = client.post(f"{API}/purchases/historical-run", json={"from": frm, "to": to})
    assert run.status_code == 200, run.get_json()
    (call,) = [c[1] for c in fake.calls if c[0] == "bills"]
    assert (call["from_date"].isoformat(), call["to_date"].isoformat()) == (frm, to)
    assert len(_docs(db, org.id, "xero_bill")) == 1


def test_supplier_credit_lowers_a_lots_cost_through_the_refund_action(flask_app, world, db):  # noqa: F811
    from tests.costing_helpers import lot, lot_cost, price

    org = world["org"]
    juniper = lot(db, org.id, "Juniper", 10, "kg")
    price(db, org.id, juniper.id, 120, 10)
    _sync(world, db, credits=[credit([_bill_line("20")])])
    (doc,) = _docs(db, org.id, "xero_bill_credit")
    (row,) = _lines(db, doc)
    client = user_client(db, flask_app, org)
    response = client.post(
        f"{API}/purchases/{row.id}/refund",
        json={"lots": [{"inventory_item_id": str(juniper.id), "amount": "-20"}]},
        headers={"Idempotency-Key": str(uuid4())},
    )
    _assert_success(response)
    assert D(lot_cost(db, org.id, juniper.id)["unit_cost"]) == D("10")


def test_migration_widens_the_source_constraint(world, db):  # noqa: F811
    from sqlalchemy import text

    _sync(world, db, bills=[bill([_bill_line("10")])])
    constraint = db.execute(
        text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'ck_purchase_documents_source'")
    ).scalar()
    assert "xero_bill" in constraint and "xero_bill_credit" in constraint


def test_r1_blank_description_falls_back_to_the_item_code(flask_app, world, db):  # noqa: F811
    org = world["org"]
    _sync(world, db, bills=[bill([_bill_line("60", qty="5", item_code="COR-5", description="   ")])])
    (doc,) = _docs(db, org.id, "xero_bill")
    (row,) = _lines(db, doc)
    client = user_client(db, flask_app, org)
    card = next(
        c for c in client.get(f"{API}/purchases?tab=to_record").get_json()["cards"] if c["line_id"] == str(row.id)
    )
    (pre,) = card["prefill"]["rows"]
    assert pre["name"] == "COR-5" and pre["ask"] == ["unit"]
    assert card["document"]["reference"].startswith("Bill INV-0042")


def test_r1_bill_cards_show_their_reference():
    from pathlib import Path

    js = (Path(__file__).resolve().parents[1] / "app/features/costing/frontend/static/purchases.js").read_text()
    assert "card.document.reference" in js
