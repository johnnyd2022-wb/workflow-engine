"""Xero credit-note import, tenant-safe return decisions, and net overview revenue."""

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.features.crm.models.product_mapping import ProductMapping
from app.features.crm.models.xero_credit_note import XeroCreditNote
from app.features.crm.models.xero_credit_note_line import XeroCreditNoteLine
from app.features.crm.models.xero_invoice import XeroInvoice
from app.features.crm.repositories.xero_invoice_repo import XeroInvoiceRepository
from app.features.crm.services import xero_api_client as xero_api_client_module
from app.features.crm.services.xero_sync_service import XeroSyncService
from tests import test_crm as crm_fixtures
from tests.test_crm_contact_sync import _connect

db = crm_fixtures.db
org = crm_fixtures.org
user = crm_fixtures.user
app_client = crm_fixtures.app_client


@pytest.fixture(autouse=True)
def cleanup_credit_note_rows(db, org):
    yield
    db.query(XeroCreditNoteLine).filter(XeroCreditNoteLine.org_id == org.id).delete(synchronize_session=False)
    db.query(XeroCreditNote).filter(XeroCreditNote.org_id == org.id).delete(synchronize_session=False)
    db.commit()


def _credit_note(note_id, number, status, total, *, line_id="line-1", description="Dry gin"):
    return SimpleNamespace(
        credit_note_id=note_id,
        credit_note_number=number,
        type="ACCRECCREDIT",
        status=status,
        contact=SimpleNamespace(name="Kererū Botanicals"),
        date=date(2026, 10, 12),
        total=Decimal(str(total)),
        currency_code=SimpleNamespace(value="NZD"),
        updated_date_utc=datetime(2026, 10, 13, tzinfo=UTC),
        sub_total=Decimal(str(total)),
        total_tax=Decimal("0"),
        allocations=[SimpleNamespace(invoice=SimpleNamespace(invoice_id="invoice-origin"))],
        line_items=[
            SimpleNamespace(
                line_item_id=line_id,
                item_code="GIN-700",
                description=description,
                quantity=Decimal("1"),
                unit_amount=Decimal(str(total)),
                line_amount=Decimal(str(total)),
            )
        ],
    )


def test_full_sync_imports_and_idempotently_upserts_credit_notes_lines_and_statuses(db, org, user, monkeypatch):
    _connect(db, org.id)
    mapping = ProductMapping(
        org_id=org.id,
        biz_e_product_name="Dry gin 700ml",
        xero_description_pattern="Dry gin",
        match_type="exact",
    )
    db.add(mapping)
    db.commit()
    remote = [
        _credit_note("cn-partial", "CN-1", "AUTHORISED", "25"),
        _credit_note("cn-full", "CN-2", "AUTHORISED", "100", line_id="line-2"),
        _credit_note("cn-void", "CN-3", "VOIDED", "100", line_id="line-3"),
        _credit_note("cn-deleted", "CN-4", "DELETED", "10", line_id="line-4"),
    ]
    monkeypatch.setattr(xero_api_client_module.XeroAPIClient, "get_all_contacts", lambda self, **kw: [])
    monkeypatch.setattr(xero_api_client_module.XeroAPIClient, "get_all_invoices", lambda self, **kw: [])
    monkeypatch.setattr(xero_api_client_module.XeroAPIClient, "fetch_all_credit_notes", lambda self, **kw: remote)

    assert XeroSyncService(db).full_sync(org.id, triggered_by="test").credit_notes_synced == 4
    first = (
        db.query(XeroCreditNoteLine)
        .filter(XeroCreditNoteLine.org_id == org.id)
        .order_by(XeroCreditNoteLine.line_key)
        .first()
    )
    assert first.product_mapping_id == mapping.id
    assert db.query(XeroCreditNote).filter(XeroCreditNote.org_id == org.id, XeroCreditNote.status == "VOIDED").count() == 1
    assert db.query(XeroCreditNote).filter(XeroCreditNote.org_id == org.id, XeroCreditNote.status == "DELETED").count() == 1
    assert db.query(XeroCreditNote).filter(XeroCreditNote.org_id == org.id, XeroCreditNote.allocated_invoice_ids == ["invoice-origin"]).count() == 4

    first.no_return_note = "Customer kept the goods"
    first.no_return_by_user_id = user.id
    first.no_return_at = datetime.now(UTC)
    db.commit()
    result = XeroSyncService(db).full_sync(org.id, triggered_by="test")
    assert result.credit_notes_synced == 4
    assert db.query(XeroCreditNote).filter(XeroCreditNote.org_id == org.id).count() == 4
    assert db.query(XeroCreditNoteLine).filter(XeroCreditNoteLine.org_id == org.id).count() == 4
    db.refresh(first)
    assert first.no_return_note == "Customer kept the goods"


def test_overview_period_and_monthly_revenue_subtract_authorised_partial_and_full_credits(db, org):
    month = date(2026, 10, 8)
    db.add_all(
        [
            XeroInvoice(
                org_id=org.id,
                xero_invoice_id=f"sales-{uuid4()}",
                xero_tenant_id="tenant",
                invoice_type="ACCREC",
                status="AUTHORISED",
                date=month,
                total=Decimal("100"),
            ),
            XeroInvoice(
                org_id=org.id,
                xero_invoice_id=f"sales-{uuid4()}",
                xero_tenant_id="tenant",
                invoice_type="ACCREC",
                status="PAID",
                date=month,
                total=Decimal("100"),
            ),
            XeroCreditNote(
                org_id=org.id,
                xero_credit_note_id=f"partial-{uuid4()}",
                xero_tenant_id="tenant",
                status="AUTHORISED",
                date=month,
                total=Decimal("25"),
                currency="NZD",
            ),
            XeroCreditNote(
                org_id=org.id,
                xero_credit_note_id=f"full-{uuid4()}",
                xero_tenant_id="tenant",
                status="PAID",
                date=month,
                total=Decimal("100"),
                currency="NZD",
            ),
            XeroCreditNote(
                org_id=org.id,
                xero_credit_note_id=f"voided-{uuid4()}",
                xero_tenant_id="tenant",
                status="VOIDED",
                date=month,
                total=Decimal("100"),
                currency="NZD",
            ),
        ]
    )
    db.commit()

    repo = XeroInvoiceRepository(db)
    assert repo.sales_totals_for_period(org.id, date(2026, 10, 1), date(2026, 11, 1)) == {
        "total": 75.0,
        "invoice_count": 2,
    }
    assert repo.monthly_sales_totals(org.id, months=1) == [{"month": "2026-10", "total": 75.0, "invoice_count": 2}]
    assert repo.daily_sales_totals_for_period(org.id, date(2026, 10, 1), date(2026, 11, 1)) == [
        {"day": "2026-10-08", "total": 75.0, "invoice_count": 2}
    ]


def test_pending_return_list_dismissal_is_audited_and_tenant_scoped(db, org, user, app_client):
    mapping = ProductMapping(
        org_id=org.id,
        biz_e_product_name="Dry gin 700ml",
        xero_description_pattern="Dry gin",
        match_type="exact",
    )
    note = XeroCreditNote(
        org_id=org.id,
        xero_credit_note_id=f"pending-{uuid4()}",
        xero_tenant_id="tenant",
        number="CN-42",
        contact="Kererū Botanicals",
        date=date(2026, 10, 12),
        status="AUTHORISED",
        total=Decimal("25"),
        currency="NZD",
    )
    db.add_all([mapping, note])
    db.flush()
    line = XeroCreditNoteLine(
        org_id=org.id,
        credit_note_id=note.id,
        line_key="xero-line-42",
        description="Dry gin",
        quantity=Decimal("1"),
        line_amount=Decimal("25"),
        product_mapping_id=mapping.id,
    )
    db.add(line)
    db.commit()

    response = app_client.get("/api/crm/returns/pending")
    assert response.status_code == 200
    assert response.get_json()["items"][0]["product_name"] == "Dry gin 700ml"
    path = f"/api/crm/credit-notes/{note.id}/lines/{line.id}/no-return"
    assert app_client.post(path, json={"note": "  Customer retained the bottles  "}).status_code == 200
    assert app_client.post(path, json={"note": "duplicate"}).status_code == 409
    db.refresh(line)
    assert line.no_return_note == "Customer retained the bottles"
    assert line.no_return_by_user_id == user.id and line.no_return_at is not None
    assert app_client.get("/api/crm/returns/pending").get_json()["items"] == []

    from app.core.db.models.audit_log import AuditLog

    audit = db.query(AuditLog).filter(AuditLog.org_id == org.id, AuditLog.entity_id == line.id).one()
    assert audit.action == "credit_note_line_no_return"
    assert audit.meta_data["note"] == "Customer retained the bottles"

    from app.core.db.models.organisation import Organisation
    from app.core.db.repositories.organisation_repo import OrganisationRepository

    other_org = OrganisationRepository(db).create_org(f"Credit-note isolation {uuid4()}")
    other_mapping = ProductMapping(
        org_id=other_org.id,
        biz_e_product_name="Other tenant gin",
        xero_description_pattern="Other gin",
        match_type="exact",
    )
    other_note = XeroCreditNote(
        org_id=other_org.id,
        xero_credit_note_id=f"other-{uuid4()}",
        xero_tenant_id="other-tenant",
        status="AUTHORISED",
        total=Decimal("10"),
        currency="NZD",
    )
    db.add_all([other_mapping, other_note])
    db.flush()
    other_line = XeroCreditNoteLine(
        org_id=other_org.id,
        credit_note_id=other_note.id,
        line_key="other-line",
        product_mapping_id=other_mapping.id,
    )
    db.add(other_line)
    db.commit()

    foreign_path = f"/api/crm/credit-notes/{other_note.id}/lines/{other_line.id}/no-return"
    assert app_client.post(foreign_path, json={"note": "No goods"}).status_code == 404
    assert app_client.get("/api/crm/returns/pending").get_json()["items"] == []
    db.query(XeroCreditNoteLine).filter(XeroCreditNoteLine.org_id == other_org.id).delete(synchronize_session=False)
    db.query(XeroCreditNote).filter(XeroCreditNote.org_id == other_org.id).delete(synchronize_session=False)
    db.query(ProductMapping).filter(ProductMapping.org_id == other_org.id).delete(synchronize_session=False)
    db.query(Organisation).filter(Organisation.id == other_org.id).delete(synchronize_session=False)
    db.commit()


def test_return_routes_require_sales_view_and_sales_record():
    from app.core.db.models.user import UserRole
    from app.core.security.access_policy import allows

    class UserWithRole:
        def __init__(self, role):
            self.role = role

    assert allows(UserWithRole(UserRole.SALES), "crm.crm_api.list_pending_returns", "GET")
    assert not allows(UserWithRole(UserRole.PRODUCTION), "crm.crm_api.list_pending_returns", "GET")
    assert allows(UserWithRole(UserRole.SALES), "crm.crm_api.record_credit_note_line_no_return", "POST")
    assert not allows(UserWithRole(UserRole.AUDITOR), "crm.crm_api.record_credit_note_line_no_return", "POST")
    assert allows(UserWithRole(UserRole.MEMBER), "crm.crm_api.record_credit_note_line_no_return", "POST")
