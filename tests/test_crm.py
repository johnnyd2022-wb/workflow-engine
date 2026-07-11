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
from uuid import uuid4

import pytest

from app.core.db import db_session
from app.core.db.models.entity_event import EntityEvent
from app.core.db.models.organisation import Organisation
from app.core.db.repositories.organisation_repo import OrganisationRepository
from app.core.db.repositories.user_repo import UserRepository
from app.core.security.auth_service import AuthService

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

        repo.upsert(org_id=org.id, xero_contact_id=xero_id, xero_tenant_id="t1", name="Test Co", contact_status="ACTIVE")
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
