"""Xero pull: incremental syncs must not lose edits, and one bad record must not sink a sync."""

import time
from datetime import UTC, datetime
from types import SimpleNamespace

from app.features.crm.models.xero_contact import XeroContact
from app.features.crm.models.xero_tenant import XeroTenant
from app.features.crm.services import xero_api_client as xero_api_client_module
from app.features.crm.services.xero_sync_service import XeroSyncService
from tests import test_crm as crm_fixtures
from tests.test_crm_contact_sync import _connect

db = crm_fixtures.db
org = crm_fixtures.org


def _xero_contact(contact_id, name, **fields):
    return SimpleNamespace(
        contact_id=contact_id,
        name=name,
        first_name=fields.get("first_name"),
        last_name=None,
        email_address=None,
        phones=[],
        addresses=[],
        payment_terms=None,
        tax_number=None,
        account_number=None,
        contact_status="ACTIVE",
        is_customer=True,
        is_supplier=False,
        updated_date_utc=datetime.now(UTC),
    )


def _tenant(db, org_id):
    db.expire_all()
    return db.query(XeroTenant).filter(XeroTenant.org_id == org_id, XeroTenant.is_connected.is_(True)).one()


def test_an_incremental_sync_resumes_from_when_it_started_not_when_it_finished(db, org, monkeypatch):
    """A Xero edit made while a sync runs, after its records were fetched, must be in the next sync.

    The next incremental sync asks Xero for records modified after the recorded time. Recording
    the finish time silently skips everything edited during the sync, until a full sync.
    """
    _connect(db, org.id)
    fetched = {}

    def contacts(self, modified_after=None):
        fetched.setdefault("first_fetch", datetime.now(UTC))
        fetched.setdefault("modified_after", []).append(modified_after)
        return []

    def invoices(self, modified_after=None):
        time.sleep(0.05)  # the sync keeps working after the fetch; Xero edits can land meanwhile
        return []

    monkeypatch.setattr(xero_api_client_module.XeroAPIClient, "get_all_contacts", contacts)
    monkeypatch.setattr(xero_api_client_module.XeroAPIClient, "get_all_invoices", invoices)
    assert XeroSyncService(db).incremental_sync(org.id, triggered_by="test").success
    resume_from = _tenant(db, org.id).last_successful_sync_at
    assert resume_from <= fetched["first_fetch"]

    assert XeroSyncService(db).incremental_sync(org.id, triggered_by="test").success
    assert fetched["modified_after"][-1] == resume_from


def test_one_record_the_database_rejects_does_not_sink_the_rest_of_the_sync(db, org, monkeypatch):
    _connect(db, org.id)
    good_before = _xero_contact("xero-good-1", "Harbour Spirits Co.")
    bad = _xero_contact("xero-bad", "Broken Ltd", first_name="Nul\x00Byte")  # Postgres refuses NUL in text
    good_after = _xero_contact("xero-good-2", "Kererū Botanicals")
    monkeypatch.setattr(
        xero_api_client_module.XeroAPIClient, "get_all_contacts", lambda self, **kw: [good_before, bad, good_after]
    )
    monkeypatch.setattr(xero_api_client_module.XeroAPIClient, "get_all_invoices", lambda self, **kw: [])

    result = XeroSyncService(db).full_sync(org.id, triggered_by="test")

    assert result.contacts_synced == 2
    assert len(result.errors) == 1 and "xero-bad" in result.errors[0]
    db.expire_all()
    stored = {c.xero_contact_id for c in db.query(XeroContact).filter(XeroContact.org_id == org.id)}
    assert {"xero-good-1", "xero-good-2"} <= stored
    assert "xero-bad" not in stored


def test_a_partial_sync_keeps_the_resume_point_so_failed_records_are_retried(db, org, monkeypatch):
    _connect(db, org.id)
    monkeypatch.setattr(xero_api_client_module.XeroAPIClient, "get_all_contacts", lambda self, **kw: [])
    monkeypatch.setattr(xero_api_client_module.XeroAPIClient, "get_all_invoices", lambda self, **kw: [])
    assert XeroSyncService(db).incremental_sync(org.id, triggered_by="test").success
    before = _tenant(db, org.id).last_successful_sync_at

    bad = _xero_contact("xero-bad", "Broken Ltd", first_name="Nul\x00Byte")
    monkeypatch.setattr(xero_api_client_module.XeroAPIClient, "get_all_contacts", lambda self, **kw: [bad])
    result = XeroSyncService(db).incremental_sync(org.id, triggered_by="test")
    assert result.errors and not result.success

    assert _tenant(db, org.id).last_successful_sync_at == before


def _xero_invoice(invoice_id, number, reference=None):
    return SimpleNamespace(
        invoice_id=invoice_id,
        contact=None,
        invoice_number=number,
        reference=reference,
        type="ACCREC",
        status="DRAFT",
        sub_total=10,
        total_tax=1.5,
        total=11.5,
        amount_due=11.5,
        amount_paid=0,
        currency_code=None,
        date=datetime.now(UTC).date(),
        due_date=None,
        fully_paid_on_date=None,
        updated_date_utc=datetime.now(UTC),
        line_items=[
            SimpleNamespace(
                line_item_id=f"{invoice_id}-line",
                description="Gin 700ml",
                item_code=None,
                quantity=1,
                unit_amount=10,
                line_amount=10,
                account_code="200",
                tax_type="OUTPUT2",
                tax_amount=1.5,
                discount_rate=None,
                tracking=None,
            )
        ],
    )


def test_an_invoice_the_database_rejects_fails_alone_and_the_others_keep_their_lines(db, org, monkeypatch):
    from app.features.crm.models.xero_invoice import XeroInvoice
    from app.features.crm.models.xero_invoice_line_item import XeroInvoiceLineItem

    _connect(db, org.id)
    invoices = [
        _xero_invoice("xi-good-1", "INV-1"),
        _xero_invoice("xi-bad", "INV-2", reference="Nul\x00Byte"),
        _xero_invoice("xi-good-2", "INV-3"),
    ]
    monkeypatch.setattr(xero_api_client_module.XeroAPIClient, "get_all_contacts", lambda self, **kw: [])
    monkeypatch.setattr(xero_api_client_module.XeroAPIClient, "get_all_invoices", lambda self, **kw: invoices)

    result = XeroSyncService(db).full_sync(org.id, triggered_by="test")

    assert result.invoices_synced == 2 and len(result.errors) == 1 and "xi-bad" in result.errors[0]
    db.expire_all()
    stored = {i.xero_invoice_id: i for i in db.query(XeroInvoice).filter(XeroInvoice.org_id == org.id)}
    assert set(stored) == {"xi-good-1", "xi-good-2"}
    for inv in stored.values():
        lines = db.query(XeroInvoiceLineItem).filter(XeroInvoiceLineItem.invoice_id == inv.id).count()
        assert lines == 1
