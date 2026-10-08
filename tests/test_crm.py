"""
Tests for the CRM/Xero integration.

Coverage:
  - Token encryption round-trip (Fernet)
  - XeroSyncService contact + invoice mapping helpers
  - CRMService: note and task CRUD (against real DB)
  - API endpoints: auth guard, org isolation, pagination, CRUD
  - Product mapping deduplication (409 on duplicate)
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.db import db_session
from app.core.db.models.entity_event import EntityEvent
from app.core.db.models.organisation import Organisation
from app.core.db.models.task_board_lane import TaskBoardLane  # noqa: F401 - registers CRM task FK target metadata
from app.core.db.repositories.organisation_repo import OrganisationRepository
from app.core.db.repositories.user_repo import UserRepository
from app.core.security.auth_service import AuthService

REPO_ROOT = Path(__file__).resolve().parent.parent

# ─────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────


def _latest_event(db, org_id, event_type: str) -> EntityEvent | None:
    return (
        db.query(EntityEvent)
        .filter(EntityEvent.org_id == org_id, EntityEvent.event_type == event_type)
        .order_by(EntityEvent.created_at.desc())
        .first()
    )


def test_overview_sales_summaries_cover_all_authorised_sales(db, org):
    """Footer summaries must not inherit the configurable Top-N display limit."""
    from app.features.crm.models.product_mapping import ProductMapping
    from app.features.crm.models.xero_contact import XeroContact
    from app.features.crm.models.xero_invoice import XeroInvoice
    from app.features.crm.models.xero_invoice_line_item import XeroInvoiceLineItem
    from app.features.crm.services.crm_service import CRMService

    contacts = []
    try:
        for name in ("Authorised customer", "Paid customer", "Draft customer"):
            contact = XeroContact(
                org_id=org.id,
                xero_contact_id=f"summary-contact-{uuid4()}",
                xero_tenant_id="summary-tenant",
                name=name,
            )
            db.add(contact)
            contacts.append(contact)
        db.flush()

        def add_invoice(contact, *, status, invoice_type, description, quantity, amount):
            invoice = XeroInvoice(
                org_id=org.id,
                xero_invoice_id=f"summary-invoice-{uuid4()}",
                xero_tenant_id="summary-tenant",
                contact_id=contact.id,
                invoice_type=invoice_type,
                status=status,
                date=date.today(),
                total=amount,
            )
            db.add(invoice)
            db.flush()
            db.add(
                XeroInvoiceLineItem(
                    org_id=org.id,
                    invoice_id=invoice.id,
                    description=description,
                    quantity=quantity,
                    line_amount=amount,
                )
            )

        add_invoice(
            contacts[0],
            status="AUTHORISED",
            invoice_type="ACCREC",
            description="Wildflower Gin",
            quantity=Decimal("3"),
            amount=Decimal("300"),
        )
        add_invoice(
            contacts[0],
            status="PAID",
            invoice_type="ACCREC",
            description="Wildflower Gin",
            quantity=Decimal("2"),
            amount=Decimal("200"),
        )
        add_invoice(
            contacts[1],
            status="PAID",
            invoice_type="ACCREC",
            description="Tonic Water",
            quantity=Decimal("4"),
            amount=Decimal("40"),
        )
        add_invoice(
            contacts[2],
            status="DRAFT",
            invoice_type="ACCREC",
            description="Draft-only product",
            quantity=Decimal("99"),
            amount=Decimal("9900"),
        )
        add_invoice(
            contacts[2],
            status="AUTHORISED",
            invoice_type="ACCPAY",
            description="Supplier purchase",
            quantity=Decimal("50"),
            amount=Decimal("500"),
        )
        db.add_all(
            [
                ProductMapping(
                    org_id=org.id,
                    biz_e_product_name="Wildflower Gin",
                    xero_description_pattern="Wildflower Gin",
                    match_type="exact",
                ),
                ProductMapping(
                    org_id=org.id,
                    biz_e_product_name="Tonic Water",
                    xero_description_pattern="Tonic Water",
                    match_type="exact",
                ),
            ]
        )
        db.commit()

        overview = CRMService(db).get_overview(org.id)

        assert overview["product_sales_summary"] == {"total_qty": 9.0, "total_revenue": 540.0}
        assert overview["authorised_customer_count"] == 2
        assert {row["description"] for row in overview["top_products"]} == {"Wildflower Gin", "Tonic Water"}
    finally:
        db.query(ProductMapping).filter(
            ProductMapping.org_id == org.id,
            ProductMapping.biz_e_product_name.in_(["Wildflower Gin", "Tonic Water"]),
        ).delete(synchronize_session=False)
        db.query(XeroInvoiceLineItem).filter(XeroInvoiceLineItem.org_id == org.id).delete(synchronize_session=False)
        db.query(XeroInvoice).filter(XeroInvoice.org_id == org.id).delete(synchronize_session=False)
        db.query(XeroContact).filter(XeroContact.org_id == org.id).delete(synchronize_session=False)
        db.commit()


def test_overview_invoice_download_uses_the_pdf_endpoint():
    overview_js = (REPO_ROOT / "app/features/crm/frontend/js/overview.js").read_text(encoding="utf-8")
    overview_template = (REPO_ROOT / "app/features/crm/frontend/templates/crm/overview.html").read_text(
        encoding="utf-8"
    )

    assert "CRMAPI.invoicePdfUrl(invoiceId)" in overview_js
    assert "application/json;charset=utf-8" not in overview_js
    assert '@click.stop="viewInvoice(inv)"' in overview_template
    assert "Download PDF" in overview_template


def test_mapped_product_quantities_use_pack_size():
    from app.features.crm.services.crm_service import CRMService

    class InvoiceRows:
        def top_products(self, *_args, **_kwargs):
            return [
                {"item_code": "CASE", "description": "Case of gin", "total_qty": 2, "total_revenue": 120},
                {"item_code": "BOTTLE", "description": "Gin bottle", "total_qty": 1, "total_revenue": 12},
            ]

    mappings = [
        SimpleNamespace(
            xero_description_pattern="Case of gin", match_type="exact", biz_e_product_name="Gin", units_per_line=6
        ),
        SimpleNamespace(
            xero_description_pattern="Gin bottle", match_type="exact", biz_e_product_name="Gin", units_per_line=1
        ),
    ]
    service = CRMService.__new__(CRMService)
    service.traceability_repo = SimpleNamespace(get_for_org=lambda _org_id: None)
    service.mapping_repo = SimpleNamespace(list_for_org=lambda _org_id: mappings)
    service.invoice_repo = InvoiceRows()

    products, unmapped, count = service._top_mapped_products(uuid4(), limit=8)

    assert products[0]["description"] == "Gin"
    assert products[0]["total_qty"] == 13.0
    assert products[0]["total_revenue"] == 132.0
    assert unmapped == []
    assert count == 0


@pytest.fixture()
def db():
    session = db_session()
    try:
        yield session
    finally:
        session.close()
        db_session.remove()


@pytest.fixture()
def org(db):
    org_repo = OrganisationRepository(db)
    o = org_repo.create_org(f"CRM Test Org {uuid4()}")
    db.commit()
    yield o
    db.query(Organisation).filter(Organisation.id == o.id).delete(synchronize_session=False)
    db.commit()


@pytest.fixture()
def user(db, org):
    user_repo = UserRepository(db)
    email = f"crm_test_{uuid4()}@test.com"
    password_hash = AuthService.hash_password("TestPass123!")
    u = user_repo.create_user(org_id=org.id, email=email, password_hash=password_hash)
    db.commit()
    yield u


@pytest.fixture()
def app_client(db, org, user):
    """Authenticated Flask test client scoped to one org."""
    from app.api.app_factory import create_app

    flask_app = create_app()
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False

    with flask_app.test_client() as client:
        client.environ_base["wsgi.url_scheme"] = "https"
        client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
        with flask_app.app_context():
            # Log in
            resp = client.post(
                "/auth/login",
                json={"email": user.email, "password": "TestPass123!"},
                content_type="application/json",
            )
            assert resp.status_code in (200, 201), f"Login failed: {resp.data}"
            yield client


# ─────────────────────────────────────────────
# Token Encryption
# ─────────────────────────────────────────────


def _make_fernet(key_str: str):
    """Build a Fernet instance from an arbitrary string (for testing)."""
    import base64
    import hashlib

    from cryptography.fernet import Fernet

    key = hashlib.sha256(key_str.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


class TestTokenEncryption:
    def test_round_trip(self):
        f = _make_fernet("test-secret-key-for-unit-testing")
        plaintext = "super_secret_access_token_abc123"
        encrypted = f.encrypt(plaintext.encode()).decode()
        decrypted = f.decrypt(encrypted.encode()).decode()

        assert decrypted == plaintext
        assert encrypted != plaintext

    def test_different_keys_produce_different_ciphertext(self):
        f1 = _make_fernet("key-one")
        f2 = _make_fernet("key-two")

        plaintext = "my_token"
        enc1 = f1.encrypt(plaintext.encode()).decode()
        enc2 = f2.encrypt(plaintext.encode()).decode()

        assert enc1 != enc2

    def test_wrong_key_raises(self):
        from cryptography.fernet import InvalidToken

        f_right = _make_fernet("right-key")
        f_wrong = _make_fernet("wrong-key")

        encrypted = f_right.encrypt(b"secret").decode()
        with pytest.raises(InvalidToken):
            f_wrong.decrypt(encrypted.encode())

    def test_service_encrypt_decrypt_round_trip(self):
        """Verify the service classmethods encrypt/decrypt using the configured key."""
        from app.features.crm.services.xero_oauth_service import XeroOAuthService

        plaintext = "access_token_xyz"
        encrypted = XeroOAuthService.encrypt(plaintext)
        decrypted = XeroOAuthService.decrypt(encrypted)

        assert decrypted == plaintext
        assert encrypted != plaintext

    def test_state_generation_is_unique(self):
        from app.features.crm.services.xero_oauth_service import XeroOAuthService

        states = {XeroOAuthService.generate_state() for _ in range(20)}
        assert len(states) == 20

    def test_state_min_length(self):
        from app.features.crm.services.xero_oauth_service import XeroOAuthService

        state = XeroOAuthService.generate_state()
        assert len(state) >= 32


# ─────────────────────────────────────────────
# Sync Service — field mapping helpers
# ─────────────────────────────────────────────


class TestContactRepository:
    """Integration tests for XeroContactRepository against the real DB."""

    def test_upsert_creates_contact(self, db, org):
        from app.features.crm.repositories.xero_contact_repo import XeroContactRepository

        repo = XeroContactRepository(db)
        xero_id = f"xero-{uuid4()}"

        repo.upsert(
            org_id=org.id, xero_contact_id=xero_id, xero_tenant_id="t1", name="Test Co", contact_status="ACTIVE"
        )
        db.commit()

        results, total = repo.list_paginated(org_id=org.id, search="Test Co")
        assert total >= 1
        assert any(r.xero_contact_id == xero_id for r in results)

    def test_upsert_updates_on_second_call(self, db, org):
        from app.features.crm.repositories.xero_contact_repo import XeroContactRepository

        repo = XeroContactRepository(db)
        xero_id = f"xero-{uuid4()}"

        repo.upsert(org_id=org.id, xero_contact_id=xero_id, xero_tenant_id="t1", name="Original Name")
        db.commit()
        repo.upsert(org_id=org.id, xero_contact_id=xero_id, xero_tenant_id="t1", name="Updated Name")
        db.commit()

        # Must still be exactly one record with this xero_id
        results, total = repo.list_paginated(org_id=org.id, search="Updated Name")
        assert total == 1
        assert results[0].name == "Updated Name"

    def test_list_paginated_search(self, db, org):
        from app.features.crm.repositories.xero_contact_repo import XeroContactRepository

        repo = XeroContactRepository(db)
        repo.upsert(org_id=org.id, xero_contact_id=f"xero-{uuid4()}", xero_tenant_id="t1", name="Unique Brewery Ltd")
        db.commit()

        results, total = repo.list_paginated(org_id=org.id, search="Unique Brewery")
        assert total >= 1
        assert all("Unique Brewery" in r.name for r in results)

    def test_org_isolation(self, db, org):
        from app.features.crm.repositories.xero_contact_repo import XeroContactRepository

        org_b = OrganisationRepository(db).create_org(f"Isolation Org {uuid4()}")
        db.commit()
        repo = XeroContactRepository(db)

        repo.upsert(org_id=org.id, xero_contact_id=f"xero-a-{uuid4()}", xero_tenant_id="t1", name="Org A Customer")
        db.commit()

        results_b, _ = repo.list_paginated(org_id=org_b.id)
        assert all(r.org_id == org_b.id for r in results_b)

        db.query(Organisation).filter(Organisation.id == org_b.id).delete(synchronize_session=False)
        db.commit()


# ─────────────────────────────────────────────
# CRM Service — Note CRUD
# ─────────────────────────────────────────────


class TestCRMNotes:
    def _make_contact(self, db, org_id):
        from app.features.crm.models.xero_contact import XeroContact

        c = XeroContact(
            org_id=org_id,
            xero_contact_id=f"fake-xero-{uuid4()}",
            xero_tenant_id="fake-tenant",
            name=f"Test Customer {uuid4()}",
            contact_status="ACTIVE",
        )
        db.add(c)
        db.commit()
        return c

    def test_create_and_retrieve_note(self, db, org, user):
        from app.features.crm.services.crm_service import CRMService

        contact = self._make_contact(db, org.id)
        svc = CRMService(db)

        note = svc.create_note(
            org_id=org.id,
            contact_id=contact.id,
            content="Test note content",
            user_id=user.id,
        )

        assert note["content"] == "Test note content"
        assert note["id"] is not None
        created_event = _latest_event(db, org.id, "crm_note.created")
        assert created_event is not None
        assert str(created_event.entity_id) == note["id"]
        assert created_event.payload["contact_id"] == str(contact.id)
        assert int(created_event.payload["content_length"]) == len("Test note content")

        # Retrieve via get_customer
        detail = svc.get_customer(contact_id=contact.id, org_id=org.id)
        note_ids = [n["id"] for n in detail["notes"]]
        assert note["id"] in note_ids

    def test_update_note(self, db, org, user):
        from app.features.crm.services.crm_service import CRMService

        contact = self._make_contact(db, org.id)
        svc = CRMService(db)
        note = svc.create_note(org.id, contact.id, "Original content", user.id)

        from uuid import UUID as _UUID

        updated = svc.update_note(note_id=_UUID(note["id"]), org_id=org.id, content="Updated content")
        assert updated["content"] == "Updated content"
        updated_event = _latest_event(db, org.id, "crm_note.updated")
        assert updated_event is not None
        assert str(updated_event.entity_id) == note["id"]
        assert int(updated_event.payload["content_length"]) == len("Updated content")
        assert updated_event.diff["content_length"]["after"] == len("Updated content")

    def test_delete_note(self, db, org, user):
        from app.features.crm.services.crm_service import CRMService

        contact = self._make_contact(db, org.id)
        svc = CRMService(db)
        note = svc.create_note(org.id, contact.id, "To be deleted", user.id)

        from uuid import UUID as _UUID

        svc.delete_note(note_id=_UUID(note["id"]), org_id=org.id)

        detail = svc.get_customer(contact_id=contact.id, org_id=org.id)
        note_ids = [n["id"] for n in detail["notes"]]
        assert note["id"] not in note_ids
        deleted_event = _latest_event(db, org.id, "crm_note.deleted")
        assert deleted_event is not None
        assert str(deleted_event.entity_id) == note["id"]
        assert deleted_event.payload["contact_id"] == str(contact.id)

    def test_note_org_isolation(self, db, org, user):
        """Notes for org A must not appear for org B."""
        from app.features.crm.services.crm_service import CRMService

        org_b = OrganisationRepository(db).create_org(f"Org B {uuid4()}")
        db.commit()

        contact_a = self._make_contact(db, org.id)
        contact_b = self._make_contact(db, org_b.id)

        svc = CRMService(db)
        note_a = svc.create_note(org.id, contact_a.id, "Org A note", user.id)

        detail_b = svc.get_customer(contact_id=contact_b.id, org_id=org_b.id)
        assert note_a["id"] not in [n["id"] for n in detail_b["notes"]]

        db.query(Organisation).filter(Organisation.id == org_b.id).delete(synchronize_session=False)
        db.commit()

    def test_create_note_rejects_other_org_contact(self, db, org, user):
        """A caller must not be able to attach a note to another org's contact by
        guessing/reusing its UUID — create_note has to validate contact ownership the
        same way create_task already does."""
        from app.features.crm.services.crm_service import CRMService

        org_b = OrganisationRepository(db).create_org(f"Org B {uuid4()}")
        db.commit()
        contact_b = self._make_contact(db, org_b.id)

        svc = CRMService(db)
        with pytest.raises(ValueError, match="not found"):
            svc.create_note(org.id, contact_b.id, "Attempted cross-tenant note", user.id)

        # No orphaned note should have been persisted against org A.
        detail = svc.get_customer(contact_id=contact_b.id, org_id=org_b.id)
        assert detail["notes"] == []

        db.query(Organisation).filter(Organisation.id == org_b.id).delete(synchronize_session=False)
        db.commit()


# ─────────────────────────────────────────────
# CRM Service — Task CRUD
# ─────────────────────────────────────────────


class TestCRMTasks:
    def test_create_task(self, db, org, user):
        from app.features.crm.services.crm_service import CRMService

        svc = CRMService(db)
        task = svc.create_task(
            org_id=org.id,
            data={"title": "Follow up call", "priority": "high"},
            user_id=user.id,
        )

        assert task["title"] == "Follow up call"
        assert task["priority"] == "high"
        assert task["status"] == "pending"
        created_event = _latest_event(db, org.id, "crm_task.created")
        assert created_event is not None
        assert str(created_event.entity_id) == task["id"]
        assert created_event.payload["title"] == "Follow up call"

    def test_update_task_status(self, db, org, user):
        from uuid import UUID as _UUID

        from app.features.crm.services.crm_service import CRMService

        svc = CRMService(db)
        task = svc.create_task(org.id, {"title": "Task to complete"}, user.id)
        updated = svc.update_task(task_id=_UUID(task["id"]), org_id=org.id, data={"status": "completed"})

        assert updated["status"] == "completed"
        assert updated["completed_at"] is not None
        updated_event = _latest_event(db, org.id, "crm_task.updated")
        assert updated_event is not None
        assert str(updated_event.entity_id) == task["id"]
        assert updated_event.diff["status"]["after"] == "completed"

    def test_delete_task(self, db, org, user):
        from uuid import UUID as _UUID

        from app.features.crm.services.crm_service import CRMService

        svc = CRMService(db)
        task = svc.create_task(org.id, {"title": "Task to delete"}, user.id)
        svc.delete_task(task_id=_UUID(task["id"]), org_id=org.id)

        tasks = svc.list_tasks(org.id, {})
        task_ids = [t["id"] for t in tasks["tasks"]]
        assert task["id"] not in task_ids
        deleted_event = _latest_event(db, org.id, "crm_task.deleted")
        assert deleted_event is not None
        assert str(deleted_event.entity_id) == task["id"]

    def test_list_tasks_org_isolation(self, db, org, user):
        from app.features.crm.services.crm_service import CRMService

        org_b = OrganisationRepository(db).create_org(f"Org B {uuid4()}")
        db.commit()

        svc = CRMService(db)
        task_a = svc.create_task(org.id, {"title": "Org A task"}, user.id)

        tasks_b = svc.list_tasks(org_b.id, {})
        assert task_a["id"] not in [t["id"] for t in tasks_b["tasks"]]

        db.query(Organisation).filter(Organisation.id == org_b.id).delete(synchronize_session=False)
        db.commit()


# ─────────────────────────────────────────────
# XeroSyncService — sync job bookkeeping
# ─────────────────────────────────────────────


class TestXeroSyncService:
    def _connect_tenant(self, db, org_id):
        from datetime import UTC, datetime, timedelta

        from app.features.crm.services.xero_oauth_service import XeroOAuthService

        oauth = XeroOAuthService(db)
        oauth.store_tokens(
            org_id,
            {"access_token": "fake-access", "refresh_token": "fake-refresh", "expires_in": 1800},
            {"tenantId": "fake-tenant-id", "tenantName": "Fake Tenant", "tenantType": "ORGANISATION"},
        )
        # store_tokens computes its own expiry from expires_in — push it comfortably
        # into the future so get_valid_token doesn't attempt a real refresh call.
        from app.features.crm.repositories.xero_token_repo import XeroTokenRepository

        token = XeroTokenRepository(db).get(org_id)
        token.expires_at = datetime.now(UTC) + timedelta(hours=1)
        db.commit()

    def test_incremental_sync_records_incremental_job_type(self, db, org, monkeypatch):
        """Regression test: incremental_sync used to hardcode its XeroSyncJob row's
        sync_type as "full", so the audit trail lied about what kind of sync ran."""
        from app.features.crm.models.xero_sync_job import XeroSyncJob
        from app.features.crm.services import xero_api_client as xero_api_client_module
        from app.features.crm.services.xero_sync_service import XeroSyncService

        self._connect_tenant(db, org.id)
        monkeypatch.setattr(xero_api_client_module.XeroAPIClient, "get_all_contacts", lambda self, **kw: [])
        monkeypatch.setattr(xero_api_client_module.XeroAPIClient, "get_all_invoices", lambda self, **kw: [])

        result = XeroSyncService(db).incremental_sync(org.id, triggered_by="test")
        assert result.success

        job = db.query(XeroSyncJob).filter(XeroSyncJob.org_id == org.id).order_by(XeroSyncJob.started_at.desc()).first()
        assert job is not None
        assert job.sync_type == "incremental"

    def test_full_sync_records_full_job_type(self, db, org, monkeypatch):
        """Sibling check so the two sync types can't silently collapse to the same
        (wrong) value again."""
        from app.features.crm.models.xero_sync_job import XeroSyncJob
        from app.features.crm.services import xero_api_client as xero_api_client_module
        from app.features.crm.services.xero_sync_service import XeroSyncService

        self._connect_tenant(db, org.id)
        monkeypatch.setattr(xero_api_client_module.XeroAPIClient, "get_all_contacts", lambda self, **kw: [])
        monkeypatch.setattr(xero_api_client_module.XeroAPIClient, "get_all_invoices", lambda self, **kw: [])

        result = XeroSyncService(db).full_sync(org.id, triggered_by="test")
        assert result.success

        job = db.query(XeroSyncJob).filter(XeroSyncJob.org_id == org.id).order_by(XeroSyncJob.started_at.desc()).first()
        assert job is not None
        assert job.sync_type == "full"


# ─────────────────────────────────────────────
# CRM Service — Invoice Creation
# ─────────────────────────────────────────────


class TestCRMInvoiceCreation:
    """POST /api/crm/customers/<contact_id>/invoices -- the "Customer / invoice CRUD"
    coverage gap named in .agents/reports/e2e/coverage-index.md: customers are Xero-sourced
    (read-only sync, no create endpoint -- see .agents/specs/crm.md), so the only real write
    path here is invoice creation. Stubs XeroAPIClient.create_invoice at the HTTP layer, per
    that report's explicit requirement that a test must never touch a real Xero tenant.
    """

    def _make_contact(self, db, org_id, *, xero_contact_id=None):
        from app.features.crm.models.xero_contact import XeroContact

        c = XeroContact(
            org_id=org_id,
            xero_contact_id=xero_contact_id if xero_contact_id is not None else f"fake-xero-{uuid4()}",
            xero_tenant_id="fake-tenant",
            name=f"Test Customer {uuid4()}",
            contact_status="ACTIVE",
        )
        db.add(c)
        db.commit()
        return c

    def _stub_create_invoice(self, monkeypatch, **overrides):
        from datetime import date as date_cls
        from types import SimpleNamespace

        from app.features.crm.services import xero_api_client as xero_api_client_module

        fields = {
            "invoice_id": f"xero-inv-{uuid4()}",
            "invoice_number": "INV-0001",
            "status": "DRAFT",
            "date": date_cls(2026, 8, 1),
            "due_date": date_cls(2026, 8, 15),
            "total": 150.0,
        }
        fields.update(overrides)
        created = SimpleNamespace(**fields)
        monkeypatch.setattr(xero_api_client_module.XeroAPIClient, "create_invoice", lambda self, **kw: created)
        # incremental_sync runs best-effort right after create (backend.py wraps it in a
        # bare try/except) -- stub it inert so the test doesn't depend on that side effect.
        monkeypatch.setattr(xero_api_client_module.XeroAPIClient, "get_all_contacts", lambda self, **kw: [])
        monkeypatch.setattr(xero_api_client_module.XeroAPIClient, "get_all_invoices", lambda self, **kw: [])
        return created

    def test_create_invoice_happy_path(self, db, org, monkeypatch):
        from app.features.crm.services.crm_service import CRMService

        contact = self._make_contact(db, org.id)
        created = self._stub_create_invoice(monkeypatch)

        svc = CRMService(db)
        result = svc.create_customer_invoice(
            contact.id,
            org.id,
            {
                "invoice_date": "2026-08-01",
                "line_items": [{"description": "Botanical gin, 700ml case", "quantity": 2, "unit_amount": 75.0}],
            },
        )

        assert result["xero_invoice_id"] == created.invoice_id
        assert result["status"] == "DRAFT"
        assert result["total"] == 150.0
        event = _latest_event(db, org.id, "crm_invoice.created")
        assert event is not None
        assert event.payload["contact_id"] == str(contact.id)

    def test_create_invoice_requires_line_items(self, db, org, monkeypatch):
        from app.features.crm.services.crm_service import CRMService

        contact = self._make_contact(db, org.id)
        self._stub_create_invoice(monkeypatch)

        svc = CRMService(db)
        with pytest.raises(ValueError, match="line item"):
            svc.create_customer_invoice(contact.id, org.id, {"invoice_date": "2026-08-01", "line_items": []})

    def test_create_invoice_rejects_contact_missing_xero_id(self, db, org, monkeypatch):
        """A contact that hasn't synced a real Xero id yet must not be invoiced --
        create_invoice would otherwise be called with a garbage contact_xero_id."""
        from app.features.crm.services.crm_service import CRMService

        contact = self._make_contact(db, org.id, xero_contact_id="")
        self._stub_create_invoice(monkeypatch)

        svc = CRMService(db)
        with pytest.raises(ValueError, match="Xero contact id"):
            svc.create_customer_invoice(
                contact.id,
                org.id,
                {"invoice_date": "2026-08-01", "line_items": [{"description": "x", "quantity": 1, "unit_amount": 1}]},
            )

    def test_org_b_cannot_create_invoice_for_org_a_customer(self, db, org, monkeypatch):
        """Highest-value case: org B must not be able to push a real Xero invoice against
        org A's customer by guessing/reusing its contact UUID."""
        from app.features.crm.services.crm_service import CRMService

        org_b = OrganisationRepository(db).create_org(f"Org B {uuid4()}")
        db.commit()
        contact_a = self._make_contact(db, org.id)
        self._stub_create_invoice(monkeypatch)

        svc = CRMService(db)
        with pytest.raises(ValueError, match="not found"):
            svc.create_customer_invoice(
                contact_a.id,
                org_b.id,
                {"invoice_date": "2026-08-01", "line_items": [{"description": "x", "quantity": 1, "unit_amount": 1}]},
            )

        # No invoice should have been recorded against org A's customer either -- a rejected
        # cross-tenant attempt must not leave a side effect on the org it targeted.
        from app.features.crm.repositories.xero_invoice_repo import XeroInvoiceRepository

        _, total = XeroInvoiceRepository(db).list_for_contact(contact_a.id, org.id)
        assert total == 0, "a rejected cross-org invoice attempt still created a row against org A"

        db.query(Organisation).filter(Organisation.id == org_b.id).delete(synchronize_session=False)
        db.commit()


# ─────────────────────────────────────────────
# CRM Service — Mapping + Traceability Events
# ─────────────────────────────────────────────


class TestCRMEvents:
    def test_traceability_config_update_emits_event(self, db, org):
        from app.features.crm.services.crm_service import CRMService

        svc = CRMService(db)
        updated = svc.update_traceability_config(
            org.id,
            {
                "matching_strategy": "hybrid",
                "manual_review_days": 14,
                "strict_mapping": False,
                "task_done_archive_days": 10,
            },
        )

        assert updated["matching_strategy"] == "hybrid"
        event = _latest_event(db, org.id, "crm_traceability_config.updated")
        assert event is not None
        assert event.payload["matching_strategy"] == "hybrid"
        assert event.diff["matching_strategy"]["after"] == "hybrid"

    def test_traceability_config_persists_sales_figure_obfuscation(self, db, org):
        from app.features.crm.services.crm_service import CRMService

        svc = CRMService(db)
        updated = svc.update_traceability_config(org.id, {"obfuscate_sales_figures": True})

        assert updated["obfuscate_sales_figures"] is True
        assert svc.get_traceability_config(org.id)["obfuscate_sales_figures"] is True

    def test_product_mapping_lifecycle_emits_events(self, db, org, user):
        from uuid import UUID as _UUID

        from app.features.crm.services.crm_service import CRMService

        svc = CRMService(db)
        mapping = svc.create_mapping(
            org.id,
            {
                "biz_e_product_name": f"Mapped Product {uuid4()}",
                "xero_description_pattern": f"Mapped Pattern {uuid4()}",
                "match_type": "contains",
            },
            user.id,
        )
        created = _latest_event(db, org.id, "crm_product_mapping.created")
        assert created is not None
        assert str(created.entity_id) == mapping["id"]

        updated = svc.update_mapping(
            _UUID(mapping["id"]),
            org.id,
            {"notes": "notes-updated", "is_active": False},
        )
        assert updated is not None
        updated_event = _latest_event(db, org.id, "crm_product_mapping.updated")
        assert updated_event is not None
        assert str(updated_event.entity_id) == mapping["id"]
        assert updated_event.diff["is_active"]["after"] is False

        ok = svc.delete_mapping(_UUID(mapping["id"]), org.id)
        assert ok is True
        deleted = _latest_event(db, org.id, "crm_product_mapping.deleted")
        assert deleted is not None
        assert str(deleted.entity_id) == mapping["id"]


# ─────────────────────────────────────────────
# API Endpoint Tests
# ─────────────────────────────────────────────


class TestCRMAPIAuth:
    def test_http_requests_redirect_to_https(self):
        from app.api.app_factory import create_app

        flask_app = create_app()
        flask_app.config["TESTING"] = True
        with flask_app.test_client() as client:
            resp = client.get("/api/crm/tasks", base_url="http://localhost")
        assert resp.status_code == 301
        assert resp.headers["Location"].startswith("https://")

    def test_tasks_endpoint_requires_auth(self):
        from app.api.app_factory import create_app

        flask_app = create_app()
        flask_app.config["TESTING"] = True
        with flask_app.test_client() as client:
            client.environ_base["wsgi.url_scheme"] = "https"
            client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
            resp = client.get("/api/crm/tasks")
        assert resp.status_code in (401, 302)

    def test_customers_endpoint_requires_auth(self):
        from app.api.app_factory import create_app

        flask_app = create_app()
        flask_app.config["TESTING"] = True
        with flask_app.test_client() as client:
            client.environ_base["wsgi.url_scheme"] = "https"
            client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
            resp = client.get("/api/crm/customers")
        assert resp.status_code in (401, 302)

    @pytest.mark.parametrize(
        "path", ["/api/crm/analytics/rankings", f"/api/crm/customers/{uuid4()}/analytics"], ids=["rankings", "customer"]
    )
    def test_analytics_endpoints_require_auth(self, path):
        from app.api.app_factory import create_app

        flask_app = create_app()
        flask_app.config["TESTING"] = True
        with flask_app.test_client() as client:
            client.environ_base["wsgi.url_scheme"] = "https"
            client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
            resp = client.get(path)
        assert resp.status_code in (401, 302)


class TestCRMTasksAPI:
    def test_list_tasks_empty(self, app_client):
        resp = app_client.get("/api/crm/tasks")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert "tasks" in data

    def test_create_task(self, app_client):
        resp = app_client.post(
            "/api/crm/tasks",
            json={"title": "API test task", "priority": "medium"},
            content_type="application/json",
        )
        assert resp.status_code in (200, 201)
        data = json.loads(resp.data)
        assert data["task"]["title"] == "API test task"

    def test_create_task_missing_title(self, app_client):
        resp = app_client.post(
            "/api/crm/tasks",
            json={"priority": "low"},
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_update_task(self, app_client):
        create_resp = app_client.post(
            "/api/crm/tasks",
            json={"title": "Task to update"},
            content_type="application/json",
        )
        task_id = json.loads(create_resp.data)["task"]["id"]

        update_resp = app_client.put(
            f"/api/crm/tasks/{task_id}",
            json={"status": "completed"},
            content_type="application/json",
        )
        assert update_resp.status_code == 200
        updated = json.loads(update_resp.data)["task"]
        assert updated["status"] == "completed"

    def test_delete_task(self, app_client):
        create_resp = app_client.post(
            "/api/crm/tasks",
            json={"title": "Task to delete"},
            content_type="application/json",
        )
        task_id = json.loads(create_resp.data)["task"]["id"]

        del_resp = app_client.delete(f"/api/crm/tasks/{task_id}")
        assert del_resp.status_code in (200, 204)

        list_resp = app_client.get("/api/crm/tasks")
        task_ids = [t["id"] for t in json.loads(list_resp.data)["tasks"]]
        assert task_id not in task_ids


class TestCRMAccessDeniedLogging:
    """Regression coverage for the observability gap this review closed: none of CRM's
    org-scoped "not found" paths used to leave any trace, unlike every other reviewed
    slice (see tests/test_activity_log.py::TestActivityAccessDeniedLogging,
    tests/test_traceability.py::TestTraceAccessDeniedLogging,
    tests/test_inventory.py::test_cross_tenant_reference_rejection_emits_access_denied).
    Mutation this catches: dropping a `_log_access_denied(...)` call and keeping only the
    404/None/False return."""

    def test_update_unknown_task_emits_access_denied(self, app_client, caplog):
        import logging

        with caplog.at_level(logging.WARNING):
            resp = app_client.put(
                f"/api/crm/tasks/{uuid4()}",
                json={"status": "completed"},
                content_type="application/json",
            )
        assert resp.status_code == 404
        denials = [r for r in caplog.records if "access_denied" in r.getMessage()]
        assert denials, f"unknown task update was not logged: {[r.getMessage() for r in caplog.records]}"
        assert "task_id" in denials[0].getMessage()

    def test_note_on_unknown_contact_emits_access_denied(self, app_client, caplog):
        import logging

        with caplog.at_level(logging.WARNING):
            resp = app_client.post(
                f"/api/crm/customers/{uuid4()}/notes",
                json={"content": "attempted note"},
                content_type="application/json",
            )
        assert resp.status_code == 400
        denials = [r for r in caplog.records if "access_denied" in r.getMessage()]
        assert denials, f"note against unknown contact was not logged: {[r.getMessage() for r in caplog.records]}"
        assert "contact_id" in denials[0].getMessage()

    def test_real_own_org_task_update_does_not_emit_access_denied(self, app_client, caplog):
        """The log must not fire on ordinary, legitimate traffic — only on a lookup that
        resolves to nothing."""
        import logging

        create_resp = app_client.post(
            "/api/crm/tasks",
            json={"title": "Real task for logging test"},
            content_type="application/json",
        )
        task_id = json.loads(create_resp.data)["task"]["id"]

        with caplog.at_level(logging.WARNING):
            resp = app_client.put(
                f"/api/crm/tasks/{task_id}",
                json={"status": "completed"},
                content_type="application/json",
            )
        assert resp.status_code == 200
        denials = [r for r in caplog.records if "access_denied" in r.getMessage()]
        assert not denials, f"a real, own-org update must not log access_denied: {[r.getMessage() for r in denials]}"


class TestCRMCustomersAPI:
    def test_list_customers_empty(self, app_client):
        resp = app_client.get("/api/crm/customers")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert "customers" in data
        assert "total" in data

    def test_list_customers_pagination_params(self, app_client):
        resp = app_client.get("/api/crm/customers?page=1&page_size=10")
        assert resp.status_code == 200

    def test_xero_status_endpoint(self, app_client):
        resp = app_client.get("/api/crm/xero/status")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert "is_connected" in data


class TestProductMappingAPI:
    def test_create_mapping(self, app_client):
        resp = app_client.post(
            "/api/crm/product-mappings",
            json={
                "biz_e_product_name": "Single Malt Whisky",
                "xero_description_pattern": "Single Malt",
                "match_type": "contains",
            },
            content_type="application/json",
        )
        assert resp.status_code in (200, 201)
        data = json.loads(resp.data)
        assert data["product_mapping"]["biz_e_product_name"] == "Single Malt Whisky"

    def test_create_mapping_missing_fields(self, app_client):
        resp = app_client.post(
            "/api/crm/product-mappings",
            json={"biz_e_product_name": "Only name, no pattern"},
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_create_duplicate_mapping_returns_409(self, app_client):
        payload = {
            "biz_e_product_name": f"Product {uuid4()}",
            "xero_description_pattern": "Pattern",
            "match_type": "exact",
        }
        r1 = app_client.post("/api/crm/product-mappings", json=payload, content_type="application/json")
        assert r1.status_code in (200, 201)
        r2 = app_client.post("/api/crm/product-mappings", json=payload, content_type="application/json")
        assert r2.status_code == 409

    def test_delete_mapping(self, app_client):
        create_resp = app_client.post(
            "/api/crm/product-mappings",
            json={
                "biz_e_product_name": f"Del Product {uuid4()}",
                "xero_description_pattern": "Del Pattern",
                "match_type": "exact",
            },
            content_type="application/json",
        )
        mapping_id = json.loads(create_resp.data)["product_mapping"]["id"]
        del_resp = app_client.delete(f"/api/crm/product-mappings/{mapping_id}")
        assert del_resp.status_code in (200, 204)


class TestCRMAnalyticsAPI:
    def test_monthly_sales_empty(self, app_client):
        resp = app_client.get("/api/crm/analytics/monthly-sales?months=3")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert "months" in data

    def test_customer_breakdown_empty(self, app_client):
        resp = app_client.get("/api/crm/analytics/customer-breakdown")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert "customers" in data

    def test_churn_risk_empty(self, app_client):
        resp = app_client.get("/api/crm/analytics/churn-risk")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert "customers" in data

    def _customer(self, db, org, name, **fields):
        from app.features.crm.models.xero_contact import XeroContact

        contact = XeroContact(
            org_id=org.id, xero_contact_id=f"contact-{uuid4()}", xero_tenant_id="contact-tenant", name=name, **fields
        )
        db.add(contact)
        db.flush()
        return contact

    def _sale(self, db, org, contact, days_ago, *, status="AUTHORISED", invoice_type="ACCREC", total=100):
        from app.features.crm.models.xero_invoice import XeroInvoice

        db.add(
            XeroInvoice(
                org_id=org.id,
                xero_invoice_id=f"contact-invoice-{uuid4()}",
                xero_tenant_id="contact-tenant",
                contact_id=contact.id,
                invoice_type=invoice_type,
                status=status,
                date=date.today() - timedelta(days=days_ago),
                total=total,
            )
        )

    def _task(self, db, org, contact, *, created_days_ago, completed_days_ago=None, status="pending"):
        from app.features.crm.models.crm_task import CRMTask

        now = datetime.now(UTC)
        db.add(
            CRMTask(
                org_id=org.id,
                contact_id=contact.id,
                title="Call",
                status=status,
                created_at=now - timedelta(days=created_days_ago),
                completed_at=None if completed_days_ago is None else now - timedelta(days=completed_days_ago),
            )
        )

    def test_customer_contact_takes_the_latest_sale_or_task(self, app_client, db, org):
        """AC: a customer's contact date is their most recent sale or task, whichever is later."""
        sale_led = self._customer(db, org, "Sale led")
        self._sale(db, org, sale_led, 5)
        self._task(db, org, sale_led, created_days_ago=40)
        task_led = self._customer(db, org, "Task led")
        self._sale(db, org, task_led, 200)
        self._task(db, org, task_led, created_days_ago=80, completed_days_ago=60, status="completed")
        quiet = self._customer(db, org, "Gone quiet")
        self._sale(db, org, quiet, 120)
        never = self._customer(db, org, "Never contacted")
        # None of these is contact: a draft, a supplier bill, a cancelled task and a future-dated sale.
        self._sale(db, org, never, 1, status="DRAFT")
        self._sale(db, org, never, 1, invoice_type="ACCPAY")
        self._sale(db, org, never, -10)
        self._task(db, org, never, created_days_ago=2, status="cancelled")
        self._customer(db, org, "Archived", contact_status="ARCHIVED")
        self._customer(db, org, "Supplier only", is_customer=False)
        db.commit()

        data = json.loads(app_client.get("/api/crm/analytics/customer-contact").data)
        rows = {row["contact_name"]: row for row in data["customers"]}
        assert set(rows) == {"Sale led", "Task led", "Gone quiet", "Never contacted"}
        assert (rows["Sale led"]["last_contact_source"], rows["Sale led"]["days_since_contact"]) == ("sale", 5)
        assert rows["Sale led"]["last_contact_date"] == (date.today() - timedelta(days=5)).isoformat()
        assert rows["Task led"]["last_contact_source"] == "task"
        assert rows["Task led"]["days_since_contact"] in (59, 60, 61)  # UTC completion vs local today
        assert rows["Gone quiet"]["days_since_contact"] == 120
        assert rows["Never contacted"] == {
            "contact_id": rows["Never contacted"]["contact_id"],
            "contact_name": "Never contacted",
            "last_contact_date": None,
            "last_contact_source": None,
            "days_since_contact": None,
        }
        # Longest silence first, with never-contacted customers ahead of everyone.
        assert [row["contact_name"] for row in data["customers"]] == [
            "Never contacted",
            "Gone quiet",
            "Task led",
            "Sale led",
        ]
        assert data["summary"] == {"total": 4, "recent": 1, "cooling": 1, "stale": 1, "never": 1}
        assert data["contact_completeness"]["total"] == 6

    def test_customer_list_and_detail_carry_the_contact_date(self, app_client, db, org):
        contact = self._customer(db, org, "Listed customer")
        self._sale(db, org, contact, 3)
        db.commit()
        expected = (date.today() - timedelta(days=3)).isoformat()

        listed = json.loads(app_client.get("/api/crm/customers").data)["customers"]
        assert [(c["name"], c["last_contact_date"], c["last_contact_source"]) for c in listed] == [
            ("Listed customer", expected, "sale")
        ]
        detail = json.loads(app_client.get(f"/api/crm/customers/{contact.id}").data)["customer"]
        assert (detail["last_contact_date"], detail["days_since_contact"]) == (expected, 3)

    def test_customer_contact_excludes_other_orgs(self, app_client, db, org):
        other = OrganisationRepository(db).create_org(f"CRM Other Org {uuid4()}")
        db.flush()
        theirs = self._customer(db, other, "Their customer")
        self._sale(db, other, theirs, 1)
        db.commit()
        try:
            data = json.loads(app_client.get("/api/crm/analytics/customer-contact").data)
            assert data["customers"] == []
            assert data["summary"]["total"] == 0
        finally:
            db.query(Organisation).filter(Organisation.id == other.id).delete(synchronize_session=False)
            db.commit()

    def test_analytics_rows_use_the_names_the_page_reads(self, app_client, db, org):
        """The Analytics tables were blank because the page read fields the API never sent."""
        contact = self._customer(db, org, "Named customer")
        self._sale(db, org, contact, 10, total=250)
        self._sale(db, org, contact, 40, total=250, status="PAID")
        db.commit()

        top = json.loads(app_client.get("/api/crm/analytics/customer-breakdown?top_n=50").data)["customers"]
        assert [(r["contact_name"], r["total"], r["invoice_count"]) for r in top] == [("Named customer", 500.0, 2)]
        churn = json.loads(app_client.get("/api/crm/analytics/churn-risk").data)["customers"]
        assert [(r["contact_name"], r["days_since_last_invoice"], r["avg_days_between_purchases"]) for r in churn] == [
            ("Named customer", 10, 30)
        ]
        page = (Path(__file__).parents[1] / "app/features/crm/frontend/templates/crm/analytics.html").read_text()
        for field in (
            "row.contact_name",
            "row.total)",
            "row.days_since_last_invoice",
            "row.avg_days_between_purchases",
        ):
            assert field in page
        for stale in ("row.name", "row.total_spend", "days_since_last_purchase", "avg_purchase_interval_days"):
            assert stale not in page

    # ── /api/crm/analytics/rankings and /api/crm/customers/<id>/analytics ──
    # Findings-Index: 45664d36 -- test-map row 19 listed both as uncovered.

    def _invoice(self, db, org, contact, on, lines, *, status="AUTHORISED", invoice_type="ACCREC"):
        """An invoice dated *on* carrying ``(description, quantity, amount)`` line items."""
        from app.features.crm.models.xero_invoice import XeroInvoice
        from app.features.crm.models.xero_invoice_line_item import XeroInvoiceLineItem

        invoice = XeroInvoice(
            org_id=org.id,
            xero_invoice_id=f"analytics-invoice-{uuid4()}",
            xero_tenant_id="analytics-tenant",
            contact_id=contact.id,
            invoice_type=invoice_type,
            status=status,
            date=on,
            total=sum((Decimal(str(amount)) for _, _, amount in lines), Decimal("0")),
        )
        db.add(invoice)
        db.flush()
        for description, quantity, amount in lines:
            db.add(
                XeroInvoiceLineItem(
                    org_id=org.id,
                    invoice_id=invoice.id,
                    description=description,
                    quantity=Decimal(str(quantity)),
                    line_amount=Decimal(str(amount)),
                )
            )
        return invoice

    def _rankings(self, app_client, **params):
        return app_client.get("/api/crm/analytics/rankings", query_string=params)

    def _customer_analytics(self, app_client, contact, **params):
        return app_client.get(f"/api/crm/customers/{contact.id}/analytics", query_string=params)

    @pytest.fixture()
    def other_org(self, db):
        """A second tenant, removed on its own connection: committing ``db`` here would expire the
        ``org`` fixture's instance just before ``app_client`` detaches it, breaking ``org``'s teardown."""
        from sqlalchemy import delete

        from app.core.db import engine

        org_b = OrganisationRepository(db).create_org(f"Analytics Org B {uuid4()}")
        db.commit()
        org_b_id = org_b.id
        yield org_b
        with engine.begin() as conn:
            conn.execute(delete(Organisation).where(Organisation.id == org_b_id))

    def test_rankings_order_customers_by_revenue_top_and_bottom(self, app_client, db, org):
        window = {"start_date": "2025-01-01", "end_date": "2025-12-31"}
        for name, amount in (("Alpha", 300), ("Bravo", 200), ("Charlie", 100)):
            self._invoice(db, org, self._customer(db, org, name), date(2025, 2, 10), [("Gin", 1, amount)])
        db.commit()

        default = json.loads(self._rankings(app_client, limit=2, **window).data)["rankings"]
        top = json.loads(self._rankings(app_client, entity="customers", direction="top", limit=2, **window).data)
        bottom = json.loads(self._rankings(app_client, entity="customers", direction="bottom", limit=2, **window).data)

        assert [r["contact_name"] for r in default] == ["Alpha", "Bravo"]
        assert [(r["contact_name"], r["total"], r["invoice_count"]) for r in top["rankings"]] == [
            ("Alpha", 300.0, 1),
            ("Bravo", 200.0, 1),
        ]
        assert [r["contact_name"] for r in bottom["rankings"]] == ["Charlie", "Bravo"]

    def test_rankings_limit_is_clamped_to_at_least_one(self, app_client, db, org):
        for name in ("Alpha", "Bravo"):
            self._invoice(db, org, self._customer(db, org, name), date(2025, 2, 10), [("Gin", 1, 100)])
        db.commit()

        rows = json.loads(self._rankings(app_client, limit=0, start_date="2025-01-01").data)["rankings"]

        assert len(rows) == 1

    def test_rankings_count_only_authorised_or_paid_sales(self, app_client, db, org):
        contact = self._customer(db, org, "Mixed")
        on = date(2025, 2, 10)
        self._invoice(db, org, contact, on, [("Gin", 1, 100)])
        self._invoice(db, org, contact, on, [("Gin", 1, 50)], status="PAID")
        self._invoice(db, org, contact, on, [("Gin", 1, 500)], status="DRAFT")
        self._invoice(db, org, contact, on, [("Gin", 1, 600)], status="VOIDED")
        self._invoice(db, org, contact, on, [("Gin", 1, 700)], invoice_type="ACCPAY")
        db.commit()

        rows = json.loads(self._rankings(app_client, start_date="2025-01-01", end_date="2025-12-31").data)["rankings"]

        assert [(r["contact_name"], r["total"], r["invoice_count"]) for r in rows] == [("Mixed", 150.0, 2)]

    def test_rankings_end_date_is_inclusive_and_the_window_excludes_the_rest(self, app_client, db, org):
        contact = self._customer(db, org, "Windowed")
        for on, amount in ((date(2024, 12, 31), 50), (date(2025, 3, 31), 100), (date(2025, 4, 1), 900)):
            self._invoice(db, org, contact, on, [("Gin", 1, amount)])
        db.commit()

        bounded = json.loads(self._rankings(app_client, start_date="2025-01-01", end_date="2025-03-31").data)
        open_ended = json.loads(self._rankings(app_client, start_date="2025-01-01").data)

        assert [(r["total"], r["invoice_count"]) for r in bounded["rankings"]] == [(100.0, 1)]
        assert [(r["total"], r["invoice_count"]) for r in open_ended["rankings"]] == [(1000.0, 2)]

    def test_rankings_relative_windows_keep_today_and_drop_old_sales(self, app_client, db, org):
        contact = self._customer(db, org, "Recent")
        self._invoice(db, org, contact, date.today(), [("Gin", 1, 50)])
        self._invoice(db, org, contact, date.today() - timedelta(days=400), [("Gin", 1, 900)])
        db.commit()

        for params in ({"months": 1}, {"period_n": 7, "period_unit": "days"}, {"period_n": 1, "period_unit": "weeks"}):
            rows = json.loads(self._rankings(app_client, **params).data)["rankings"]
            assert [(r["contact_name"], r["total"]) for r in rows] == [("Recent", 50.0)], params

    def test_rankings_customers_by_product_rank_each_customer_product_pair(self, app_client, db, org):
        alpha = self._customer(db, org, "Alpha")
        bravo = self._customer(db, org, "Bravo")
        on = date(2025, 2, 10)
        self._invoice(db, org, alpha, on, [("Gin", 2, 200), ("Tonic", 10, 100)])
        self._invoice(db, org, bravo, on, [("Gin", 1, 150)])
        db.commit()
        window = {"entity": "customers_by_product", "start_date": "2025-01-01", "end_date": "2025-12-31"}

        def pairs(**extra):
            rows = json.loads(self._rankings(app_client, **window, **extra).data)["rankings"]
            return [(r["contact_name"], r["description"], r["total_revenue"], r["total_qty"]) for r in rows]

        assert pairs() == [("Alpha", "Gin", 200.0, 2.0), ("Bravo", "Gin", 150.0, 1.0), ("Alpha", "Tonic", 100.0, 10.0)]
        assert pairs(direction="bottom", limit=1) == [("Alpha", "Tonic", 100.0, 10.0)]

    def test_rankings_products_group_xero_lines_under_the_mapped_product(self, app_client, db, org):
        created = app_client.post(
            "/api/crm/product-mappings",
            json={
                "biz_e_product_name": "Wildflower Gin",
                "xero_description_pattern": "Wildflower Gin 700ml",
                "match_type": "exact",
            },
            content_type="application/json",
        )
        assert created.status_code in (200, 201)
        on = date(2025, 2, 10)
        self._invoice(db, org, self._customer(db, org, "Alpha"), on, [("Wildflower Gin 700ml", 3, 300)])
        self._invoice(db, org, self._customer(db, org, "Bravo"), on, [("Wildflower Gin 700ml", 2, 200)])
        self._invoice(db, org, self._customer(db, org, "Charlie"), on, [("Unmapped merchandise", 1, 999)])
        db.commit()

        rows = json.loads(
            self._rankings(app_client, entity="products", start_date="2025-01-01", end_date="2025-12-31").data
        )["rankings"]

        assert [(r["description"], r["total_qty"], r["total_revenue"]) for r in rows] == [
            ("Wildflower Gin", 5.0, 500.0)
        ]

    @pytest.mark.parametrize(
        ("params", "named"),
        [
            ({"entity": "bogus"}, "entity"),
            ({"direction": "sideways"}, "direction"),
            ({"limit": "abc"}, "limit"),
            ({"period_n": "abc"}, "period_n"),
            ({"start_date": "nope"}, "start_date"),
            ({"start_date": "2025-01-01", "end_date": "nope"}, "end_date"),
            ({"months": "abc"}, "months"),
            ({"start_month": "2025-13"}, "start_month"),
            ({"start_month": "2025-01", "end_month": "nope"}, "end_month"),
        ],
    )
    def test_rankings_reject_bad_parameters_with_a_named_400(self, app_client, params, named):
        resp = self._rankings(app_client, **params)

        assert resp.status_code == 400
        assert named in json.loads(resp.data)["error"]

    @pytest.mark.parametrize(
        ("path", "param"),
        [
            ("/api/crm/analytics/monthly-sales", "months"),
            ("/api/crm/analytics/customer-breakdown", "top_n"),
        ],
    )
    def test_chart_endpoints_reject_a_non_integer_size_with_a_named_400(self, app_client, path, param):
        """A hand-typed ``?months=abc`` used to raise ValueError out of the view (a 500)."""
        resp = app_client.get(path, query_string={param: "abc"})

        assert resp.status_code == 400
        assert param in json.loads(resp.data)["error"]

    def test_monthly_sales_totals_receivables_per_month_newest_first(self, app_client, db, org, other_org):
        mine = self._customer(db, org, "Mine")
        theirs = self._customer(db, other_org, "Theirs")
        self._invoice(db, org, mine, date(2025, 1, 10), [("Gin", 1, 100)])
        self._invoice(db, org, mine, date(2025, 1, 20), [("Gin", 1, 50)])
        self._invoice(db, org, mine, date(2025, 2, 5), [("Gin", 1, 200)], status="PAID")
        self._invoice(db, org, mine, date(2025, 3, 15), [("Gin", 1, 300)])
        # None of these is a sale: a draft, a supplier bill, and another tenant's invoice.
        self._invoice(db, org, mine, date(2025, 3, 16), [("Gin", 1, 9000)], status="DRAFT")
        self._invoice(db, org, mine, date(2025, 3, 17), [("Gin", 1, 9000)], invoice_type="ACCPAY")
        self._invoice(db, other_org, theirs, date(2025, 3, 18), [("Secret Gin", 1, 7000)])
        db.commit()

        body = json.loads(app_client.get("/api/crm/analytics/monthly-sales?months=24").data)

        assert body["monthly_sales"] == [
            {"month": "2025-03", "total": 300.0, "invoice_count": 1},
            {"month": "2025-02", "total": 200.0, "invoice_count": 1},
            {"month": "2025-01", "total": 150.0, "invoice_count": 2},
        ]
        assert body["months"] == body["monthly_sales"]

    @pytest.mark.parametrize(
        ("requested", "expected"),
        [("2", 2), ("0", 1), ("-5", 1), ("999", 24), (None, 12)],
        ids=["two", "zero-floors-to-one", "negative-floors-to-one", "huge-caps-at-24", "default-is-12"],
    )
    def test_monthly_sales_clamps_the_months_window(self, app_client, db, org, requested, expected):
        mine = self._customer(db, org, "Mine")
        for index in range(26):  # 2023-01 .. 2025-02, so the 24-month cap is reachable
            self._invoice(db, org, mine, date(2023 + index // 12, index % 12 + 1, 10), [("Gin", 1, 100)])
        db.commit()

        query = {} if requested is None else {"months": requested}
        rows = json.loads(app_client.get("/api/crm/analytics/monthly-sales", query_string=query).data)["monthly_sales"]

        assert len(rows) == expected
        assert rows[0]["month"] == "2025-02"

    def test_customer_analytics_rejects_a_malformed_customer_id_with_400(self, app_client):
        resp = app_client.get("/api/crm/customers/not-a-uuid/analytics")

        assert resp.status_code == 400
        assert json.loads(resp.data)["error"] == "Invalid customer ID"

    def test_rankings_only_include_the_callers_own_org(self, app_client, db, org, other_org):
        # The caller maps "Gin" to a product, so the other org's "Gin" line would join the product
        # ranking if it leaked; the two orgs' lines alone would sum to 9100 rather than 100.
        created = app_client.post(
            "/api/crm/product-mappings",
            json={"biz_e_product_name": "Gin", "xero_description_pattern": "Gin", "match_type": "exact"},
            content_type="application/json",
        )
        assert created.status_code in (200, 201)
        mine = self._customer(db, org, "Mine")
        theirs = self._customer(db, other_org, "Theirs")
        on = date(2025, 2, 10)
        self._invoice(db, org, mine, on, [("Gin", 1, 100)])
        self._invoice(db, other_org, theirs, on, [("Gin", 1, 9000)])
        db.commit()

        for entity in ("customers", "customers_by_product"):
            rows = json.loads(
                self._rankings(app_client, entity=entity, start_date="2025-01-01", end_date="2025-12-31").data
            )["rankings"]
            assert [r["contact_name"] for r in rows] == ["Mine"], entity
        products = json.loads(
            self._rankings(app_client, entity="products", start_date="2025-01-01", end_date="2025-12-31").data
        )["rankings"]
        assert [(r["description"], r["total_qty"], r["total_revenue"]) for r in products] == [("Gin", 1.0, 100.0)]

    def test_customer_analytics_report_monthly_totals_and_top_products(self, app_client, db, org):
        contact = self._customer(db, org, "Analysed")
        self._invoice(db, org, contact, date(2025, 1, 15), [("Gin", 2, 200), ("Tonic", 10, 100)])
        self._invoice(db, org, contact, date(2025, 3, 10), [("Gin", 2, 200)], status="PAID")
        # None of these is a sale: a draft, and a bill the business owes.
        self._invoice(db, org, contact, date(2025, 3, 12), [("Gin", 99, 9999)], status="DRAFT")
        self._invoice(db, org, contact, date(2025, 2, 1), [("Gin", 1, 777)], invoice_type="ACCPAY")
        db.commit()

        resp = self._customer_analytics(app_client, contact)

        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["monthly_sales"] == [
            {"month": "2025-01", "total": 300.0, "invoice_count": 1},
            {"month": "2025-03", "total": 200.0, "invoice_count": 1},
        ]
        assert data["total_revenue"] == 500.0
        assert data["total_invoices"] == 2
        assert [(p["description"], p["total_qty"], p["total_revenue"]) for p in data["top_products"]] == [
            ("Gin", 4.0, 400.0),
            ("Tonic", 10.0, 100.0),
        ]

    def test_customer_analytics_end_date_is_inclusive(self, app_client, db, org):
        contact = self._customer(db, org, "Windowed")
        for on, amount in ((date(2025, 1, 15), 300), (date(2025, 3, 31), 200), (date(2025, 4, 1), 900)):
            self._invoice(db, org, contact, on, [("Gin", 1, amount)])
        db.commit()

        data = json.loads(
            self._customer_analytics(app_client, contact, start_date="2025-02-01", end_date="2025-03-31").data
        )

        assert data["monthly_sales"] == [{"month": "2025-03", "total": 200.0, "invoice_count": 1}]
        assert data["total_revenue"] == 200.0
        assert [p["total_revenue"] for p in data["top_products"]] == [200.0]

    @pytest.mark.parametrize(
        ("params", "named"),
        [({"start_date": "nope"}, "start_date"), ({"end_date": "2025-13-45"}, "end_date")],
    )
    def test_customer_analytics_reject_bad_dates_with_a_named_400(self, app_client, db, org, params, named):
        contact = self._customer(db, org, "Dated")
        db.commit()

        resp = self._customer_analytics(app_client, contact, **params)

        assert resp.status_code == 400
        assert named in json.loads(resp.data)["error"]

    def test_customer_analytics_never_expose_another_orgs_customer(self, app_client, db, org, other_org):
        mine = self._customer(db, org, "Mine")
        theirs = self._customer(db, other_org, "Theirs")
        self._invoice(db, org, mine, date(2025, 2, 10), [("Gin", 1, 100)])
        self._invoice(db, other_org, theirs, date(2025, 2, 10), [("Secret Gin", 1, 9000)])
        db.commit()

        own = json.loads(self._customer_analytics(app_client, mine).data)
        foreign = self._customer_analytics(app_client, theirs)

        assert own["total_revenue"] == 100.0  # the endpoint works for the caller's own customer
        assert foreign.status_code == 200
        assert json.loads(foreign.data) == {
            "monthly_sales": [],
            "top_products": [],
            "total_invoices": 0,
            "total_revenue": 0,
        }


# ─────────────────────────────────────────────
# Sync idempotency via repository
# ─────────────────────────────────────────────


class TestContactUpsertIdempotency:
    def test_upsert_contact_twice_no_duplicate(self, db, org):
        from app.features.crm.repositories.xero_contact_repo import XeroContactRepository

        repo = XeroContactRepository(db)
        xero_id = f"xero-{uuid4()}"

        repo.upsert(
            org_id=org.id,
            xero_contact_id=xero_id,
            xero_tenant_id="tenant-abc",
            name="Idempotent Customer",
            email_address="idem@example.com",
            contact_status="ACTIVE",
        )
        db.commit()
        repo.upsert(
            org_id=org.id,
            xero_contact_id=xero_id,
            xero_tenant_id="tenant-abc",
            name="Idempotent Customer Updated",
            email_address="idem@example.com",
            contact_status="ACTIVE",
        )
        db.commit()

        results, total = repo.list_paginated(org_id=org.id, search="Idempotent Customer Updated")
        assert total == 1
        assert results[0].name == "Idempotent Customer Updated"


# ─────────────────────────────────────────────
# XeroAPIClient — pure parsing/error-classification helpers
#
# These handle untrusted response bytes/exceptions from the real Xero API and had zero
# coverage — every branch here is reachable with no network/mocking needed, since none of
# them touch self/db/HTTP.
# ─────────────────────────────────────────────


class TestXeroAPIClientHelpers:
    def test_extract_status_code_from_plain_status_attribute(self):
        from app.features.crm.services.xero_api_client import _extract_status_code

        class FakeError(Exception):
            status = 429

        assert _extract_status_code(FakeError()) == 429

    def test_extract_status_code_from_string_digit_attribute(self):
        from app.features.crm.services.xero_api_client import _extract_status_code

        class FakeError(Exception):
            status_code = "503"

        assert _extract_status_code(FakeError()) == 503

    def test_extract_status_code_from_http_resp(self):
        from app.features.crm.services.xero_api_client import _extract_status_code

        class HttpResp:
            status = 401

        class FakeError(Exception):
            http_resp = HttpResp()

        assert _extract_status_code(FakeError()) == 401

    def test_extract_status_code_from_response_object(self):
        from app.features.crm.services.xero_api_client import _extract_status_code

        class Response:
            status_code = 500

        class FakeError(Exception):
            response = Response()

        assert _extract_status_code(FakeError()) == 500

    def test_extract_status_code_none_when_absent(self):
        from app.features.crm.services.xero_api_client import _extract_status_code

        assert _extract_status_code(Exception("plain error, no status anywhere")) is None

    def test_is_insufficient_scope_detects_message_text(self):
        from app.features.crm.services.xero_api_client import _is_insufficient_scope

        assert _is_insufficient_scope(Exception("Bearer error='insufficient_scope'")) is True

    def test_is_insufficient_scope_detects_www_authenticate_header(self):
        from app.features.crm.services.xero_api_client import _is_insufficient_scope

        class HttpResp:
            headers = {"WWW-Authenticate": 'Bearer error="insufficient_scope"'}

        class FakeError(Exception):
            http_resp = HttpResp()

        assert _is_insufficient_scope(FakeError()) is True

    def test_is_insufficient_scope_false_for_unrelated_error(self):
        from app.features.crm.services.xero_api_client import _is_insufficient_scope

        assert _is_insufficient_scope(Exception("connection reset")) is False

    def test_parse_pdf_bytes_or_none_finds_pdf_signature(self):
        from app.features.crm.services.xero_api_client import _parse_pdf_bytes_or_none

        raw = b"garbage-prefix%PDF-1.4 rest of pdf content"
        result = _parse_pdf_bytes_or_none(raw)
        assert result is not None
        assert result.startswith(b"%PDF")

    def test_parse_pdf_bytes_or_none_decompresses_gzip(self):
        import gzip

        from app.features.crm.services.xero_api_client import _parse_pdf_bytes_or_none

        raw = gzip.compress(b"%PDF-1.4 fake pdf body")
        result = _parse_pdf_bytes_or_none(raw)
        assert result is not None
        assert result.startswith(b"%PDF")

    def test_parse_pdf_bytes_or_none_returns_none_for_non_pdf(self):
        from app.features.crm.services.xero_api_client import _parse_pdf_bytes_or_none

        assert _parse_pdf_bytes_or_none(b'{"Message": "not a pdf"}') is None

    def test_string_to_bytes_decodes_base64(self):
        import base64

        from app.features.crm.services.xero_api_client import _string_to_bytes

        original = b"%PDF-1.4 pdf bytes here"
        encoded = base64.b64encode(original).decode()
        assert _string_to_bytes(encoded) == original

    def test_string_to_bytes_passes_through_json_looking_text(self):
        from app.features.crm.services.xero_api_client import _string_to_bytes

        text = '{"Message": "an error"}'
        assert _string_to_bytes(text) == text.encode("utf-8")

    def test_extract_json_error_message_reads_message_field(self):
        from app.features.crm.services.xero_api_client import _extract_json_error_message

        raw = b'{"Message": "Invoice not found", "StatusCode": 404}'
        assert _extract_json_error_message(raw) == "Invoice not found"

    def test_extract_json_error_message_reads_nested_validation_error(self):
        from app.features.crm.services.xero_api_client import _extract_json_error_message

        raw = b'{"Elements": [{"ValidationErrors": [{"Message": "Contact is required"}]}]}'
        assert _extract_json_error_message(raw) == "Contact is required"

    def test_extract_json_error_message_none_for_non_json(self):
        from app.features.crm.services.xero_api_client import _extract_json_error_message

        assert _extract_json_error_message(b"%PDF-1.4 binary content") is None

    def test_normalise_payment_terms_reads_sales_and_bills(self):
        from types import SimpleNamespace

        from app.features.crm.services.xero_api_client import _normalise_payment_terms

        raw = SimpleNamespace(
            sales=SimpleNamespace(day=20, month=None, type=SimpleNamespace(value="DAYSAFTERBILLMONTH")),
            bills=None,
        )
        result = _normalise_payment_terms(raw)
        assert result == {"sales": {"day": 20, "month": None, "type": "DAYSAFTERBILLMONTH"}, "bills": None}

    def test_normalise_payment_terms_none_when_both_empty(self):
        from types import SimpleNamespace

        from app.features.crm.services.xero_api_client import _normalise_payment_terms

        assert _normalise_payment_terms(SimpleNamespace(sales=None, bills=None)) is None
