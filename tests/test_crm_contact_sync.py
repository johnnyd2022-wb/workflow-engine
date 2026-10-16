"""Sales contacts created in Biz-E and sent to Xero (app/features/crm/services/contact_service.py).

Xero itself is faked at the XeroAPIClient boundary: `FakeXero` records every create and update
and can be told to fail, so each test says exactly what Biz-E sent and what it did with the
answer. The database is real.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.db.models.entity_event import EntityEvent
from app.core.db.models.user import UserRole
from app.core.db.repositories.user_repo import UserRepository
from app.core.security.auth_service import AuthService
from app.features.crm.models.xero_contact import XeroContact
from app.features.crm.services import xero_api_client as xero_api_client_module
from app.features.crm.services.contact_service import ContactNotFoundError, ContactSyncService
from tests import test_crm as crm_fixtures

# The CRM suite's fixtures: a real session, a throwaway org, its user, and a signed-in client.
app_client = crm_fixtures.app_client
db = crm_fixtures.db
org = crm_fixtures.org
user = crm_fixtures.user


class FakeXero:
    """Stands in for Xero's contacts API."""

    def __init__(self):
        self.created: list[tuple[dict, str | None]] = []
        self.updated: list[tuple[str, dict]] = []
        self.fail_with: Exception | None = None

    def install(self, monkeypatch):
        fake = self

        def create_contact(_client, fields, *, idempotency_key=None):
            if fake.fail_with:
                raise fake.fail_with
            fake.created.append((dict(fields), idempotency_key))
            return SimpleNamespace(contact_id=f"xero-{uuid4()}", updated_date_utc=datetime.now(UTC))

        def update_contact(_client, contact_xero_id, fields):
            if fake.fail_with:
                raise fake.fail_with
            fake.updated.append((contact_xero_id, dict(fields)))
            return SimpleNamespace(contact_id=contact_xero_id, updated_date_utc=datetime.now(UTC))

        monkeypatch.setattr(xero_api_client_module.XeroAPIClient, "create_contact", create_contact)
        monkeypatch.setattr(xero_api_client_module.XeroAPIClient, "update_contact", update_contact)
        return self


@pytest.fixture()
def xero(monkeypatch):
    return FakeXero().install(monkeypatch)


def _connect(db, org_id, scopes="openid accounting.contacts accounting.invoices offline_access"):
    from app.features.crm.repositories.xero_token_repo import XeroTokenRepository
    from app.features.crm.services.xero_oauth_service import XeroOAuthService

    XeroOAuthService(db).store_tokens(
        org_id,
        {"access_token": "fake-access", "refresh_token": "fake-refresh", "expires_in": 1800, "scope": scopes},
        {"tenantId": "fake-tenant-id", "tenantName": "Fake Tenant", "tenantType": "ORGANISATION"},
    )
    token = XeroTokenRepository(db).get(org_id)
    token.expires_at = datetime.now(UTC) + timedelta(hours=1)
    db.commit()


def _xero_contact(db, org_id, name="Harbour Spirits Co.", **fields):
    contact = XeroContact(
        org_id=org_id,
        xero_contact_id=f"xero-{uuid4()}",
        xero_tenant_id="fake-tenant-id",
        name=name,
        phone_number="04 555 0100",
        email_address="orders@harbour.example",
        **fields,
    )
    db.add(contact)
    db.commit()
    return contact


def _events(db, org_id, event_type):
    return db.query(EntityEvent).filter(EntityEvent.org_id == org_id, EntityEvent.event_type == event_type).all()


# ─── Creating in Biz-E ──────────────────────────────────────────────────────


def test_a_contact_created_in_bize_stays_local_while_sync_is_off(db, org, xero):
    _connect(db, org.id)
    contact, state = ContactSyncService(db).create_contact(
        org.id, {"name": "Kererū Botanicals", "email_address": "hello@kereru.example"}
    )
    assert (contact.source, contact.xero_contact_id) == ("bize", None)
    assert state["in_xero"] is False and state["syncs"] is False and state["follows_default"] is True
    assert xero.created == []
    assert len(_events(db, org.id, "crm_contact.created")) == 1


def test_turning_a_contacts_own_sync_on_sends_it_to_xero_once(db, org, xero):
    _connect(db, org.id)
    service = ContactSyncService(db)
    contact, _ = service.create_contact(org.id, {"name": "Kererū Botanicals", "phone_number": "021 555 0199"})
    contact, state = service.set_contact_sync(org.id, contact.id, True)

    assert len(xero.created) == 1
    sent, key = xero.created[0]
    assert sent["name"] == "Kererū Botanicals" and sent["phone_number"] == "021 555 0199"
    assert key == f"bize-contact-{contact.id}"  # a retried create cannot make a second contact
    assert contact.xero_contact_id and contact.xero_tenant_id == "fake-tenant-id"
    assert state["push_status"] == "synced" and state["in_xero"] is True
    assert len(_events(db, org.id, "crm_contact.sent_to_xero")) == 1


def test_the_sales_default_sends_new_contacts_and_waiting_ones_but_not_opted_out(db, org, xero):
    _connect(db, org.id)
    service = ContactSyncService(db)
    waiting, _ = service.create_contact(org.id, {"name": "Waiting Ltd"})
    opted_out, _ = service.create_contact(org.id, {"name": "Private Ltd", "sync_to_xero": False})
    assert xero.created == []

    result = service.set_sync_default(org.id, True)
    assert (result["sent"], result["failed"], result["sync_contacts_to_xero"]) == (1, 0, True)
    assert [fields["name"] for fields, _ in xero.created] == ["Waiting Ltd"]
    db.refresh(opted_out)
    assert opted_out.xero_contact_id is None

    created_after, state = service.create_contact(org.id, {"name": "Newcomer Ltd"})
    assert state["syncs"] is True and created_after.xero_contact_id
    assert [fields["name"] for fields, _ in xero.created][-1] == "Newcomer Ltd"


# ─── Editing ────────────────────────────────────────────────────────────────


def test_editing_a_xero_contact_sends_only_the_changed_details_back(db, org, xero):
    _connect(db, org.id)
    contact = _xero_contact(db, org.id)
    contact, state, changed = ContactSyncService(db).update_contact(
        org.id, contact.id, {"phone_number": "04 555 0222", "email_address": "orders@harbour.example"}
    )
    assert changed == {"phone_number": "04 555 0222"}  # the email did not change, so it is not sent
    assert xero.updated == [(contact.xero_contact_id, {"phone_number": "04 555 0222", "name": "Harbour Spirits Co."})]
    assert state["push_status"] == "synced"
    event = _events(db, org.id, "crm_contact.updated")[0]
    assert event.diff == {"phone_number": {"before": "04 555 0100", "after": "04 555 0222"}}


def test_editing_a_local_contact_with_sync_off_never_calls_xero(db, org, xero):
    _connect(db, org.id)
    service = ContactSyncService(db)
    contact, _ = service.create_contact(org.id, {"name": "Local Only", "sync_to_xero": False})
    service.update_contact(org.id, contact.id, {"phone_number": "09 555 0300"})
    assert xero.created == [] and xero.updated == []
    db.refresh(contact)
    assert contact.phone_number == "09 555 0300"


def test_a_failed_send_keeps_the_edit_the_pull_leaves_it_alone_and_retry_sends_it(db, org, xero, monkeypatch):
    from app.features.crm.services.xero_sync_service import XeroSyncService

    _connect(db, org.id)
    contact = _xero_contact(db, org.id)
    service = ContactSyncService(db)
    xero.fail_with = RuntimeError("connection reset")
    contact, state, _ = service.update_contact(org.id, contact.id, {"phone_number": "04 555 0999"})
    assert state["push_status"] == "failed" and state["push_error"]
    db.refresh(contact)
    assert contact.phone_number == "04 555 0999"

    # Xero still has the old number; a pull must not undo the edit Xero has not seen.
    stale = SimpleNamespace(
        contact_id=contact.xero_contact_id,
        name="Harbour Spirits Co.",
        first_name=None,
        last_name=None,
        email_address="orders@harbour.example",
        phones=[SimpleNamespace(phone_type="DEFAULT", phone_number="04 555 0100")],
        addresses=[],
        payment_terms=None,
        tax_number=None,
        account_number="HS-1",
        contact_status="ACTIVE",
        is_customer=True,
        is_supplier=False,
        updated_date_utc=datetime.now(UTC),
    )
    monkeypatch.setattr(xero_api_client_module.XeroAPIClient, "get_all_contacts", lambda self, **kw: [stale])
    monkeypatch.setattr(xero_api_client_module.XeroAPIClient, "get_all_invoices", lambda self, **kw: [])
    assert XeroSyncService(db).full_sync(org.id, triggered_by="test").success
    db.refresh(contact)
    assert contact.phone_number == "04 555 0999"
    assert contact.account_number == "HS-1"  # fields Biz-E does not edit still follow Xero

    xero.fail_with = None
    contact, state = service.retry(org.id, contact.id)
    assert state["push_status"] == "synced"
    assert xero.updated[-1][1]["phone_number"] == "04 555 0999"


def test_the_pull_links_a_contact_also_made_in_xero_instead_of_duplicating_it(db, org, xero, monkeypatch):
    from app.features.crm.services.xero_sync_service import XeroSyncService

    _connect(db, org.id)
    contact, _ = ContactSyncService(db).create_contact(org.id, {"name": "Southern Cross Liqueurs"})
    made_in_xero = SimpleNamespace(
        contact_id="xero-made-by-hand",
        name="southern cross liqueurs",
        first_name=None,
        last_name=None,
        email_address="sales@southerncross.example",
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
    monkeypatch.setattr(xero_api_client_module.XeroAPIClient, "get_all_contacts", lambda self, **kw: [made_in_xero])
    monkeypatch.setattr(xero_api_client_module.XeroAPIClient, "get_all_invoices", lambda self, **kw: [])
    assert XeroSyncService(db).full_sync(org.id, triggered_by="test").success

    rows = db.query(XeroContact).filter(XeroContact.org_id == org.id).all()
    assert len(rows) == 1
    db.refresh(contact)
    assert contact.xero_contact_id == "xero-made-by-hand"
    assert contact.email_address == "sales@southerncross.example"


# ─── When Xero cannot take it ───────────────────────────────────────────────


def test_without_a_xero_connection_the_contact_is_saved_and_the_reason_recorded(db, org, xero):
    contact, state = ContactSyncService(db).create_contact(org.id, {"name": "Offline Ltd", "sync_to_xero": True})
    assert contact.id and contact.xero_contact_id is None
    assert state["push_status"] == "failed" and "not connected" in state["push_error"]
    assert xero.created == []


def test_a_read_only_xero_connection_asks_for_a_reconnect_without_calling_xero(db, org, xero):
    _connect(db, org.id, scopes="openid accounting.contacts.read accounting.invoices offline_access")
    _, state = ContactSyncService(db).create_contact(org.id, {"name": "Read Only Ltd", "sync_to_xero": True})
    assert state["push_status"] == "failed" and "Reconnect Xero" in state["push_error"]
    assert xero.created == []
    assert ContactSyncService(db).connection(org.id)["can_write_contacts"] is False


def test_xero_refusing_the_contact_is_reported_in_its_own_words(db, org, xero):
    _connect(db, org.id)
    xero.fail_with = ValueError("The contact name Harbour Spirits Co. is already assigned to another contact.")
    _, state = ContactSyncService(db).create_contact(org.id, {"name": "Harbour", "sync_to_xero": True})
    assert state["push_error"] == (
        "Xero refused the contact: The contact name Harbour Spirits Co. is already assigned to another contact."
    )


# ─── Validation and tenancy ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "data, message",
    [
        ({}, "needs a name"),
        ({"name": "   "}, "needs a name"),
        ({"name": "Ok", "email_address": "not-an-email"}, "email address"),
        ({"name": "Ok", "website": "x"}, "Unknown field"),
        ({"name": "x" * 256}, "at most 255"),
        ({"name": "Ok", "sync_to_xero": "yes"}, "true, false or null"),
    ],
)
def test_invalid_contacts_are_refused_and_nothing_is_saved(db, org, data, message):
    with pytest.raises(ValueError, match=message):
        ContactSyncService(db).create_contact(org.id, data)
    db.rollback()
    assert db.query(XeroContact).filter(XeroContact.org_id == org.id).count() == 0


def test_a_second_contact_with_the_same_name_is_refused(db, org):
    _xero_contact(db, org.id, name="Harbour Spirits Co.")
    with pytest.raises(ValueError, match="already exists"):
        ContactSyncService(db).create_contact(org.id, {"name": "harbour spirits co."})


def test_another_organisations_contact_cannot_be_edited(db, org):
    from app.core.db.repositories.organisation_repo import OrganisationRepository

    other = OrganisationRepository(db).create_org(f"Other CRM Org {uuid4()}")
    db.commit()
    try:
        theirs = _xero_contact(db, other.id)
        with pytest.raises(ContactNotFoundError):
            ContactSyncService(db).update_contact(org.id, theirs.id, {"phone_number": "1"})
        db.refresh(theirs)
        assert theirs.phone_number == "04 555 0100"
    finally:
        db.rollback()
        db.query(XeroContact).filter(XeroContact.org_id == other.id).delete()
        db.query(type(other)).filter(type(other).id == other.id).delete()
        db.commit()


# ─── HTTP ───────────────────────────────────────────────────────────────────


def test_http_create_edit_and_toggle(app_client, db, org, xero):
    _connect(db, org.id)
    created = app_client.post("/api/crm/customers", json={"name": "Bottle-O Greytown", "phone_number": "06 555 0101"})
    assert created.status_code == 201, created.data
    body = json.loads(created.data)
    contact_id = body["customer"]["id"]
    assert body["customer"]["source"] == "bize" and body["xero_sync"]["in_xero"] is False

    toggled = app_client.put(f"/api/crm/customers/{contact_id}/xero-sync", json={"sync_to_xero": True})
    assert toggled.status_code == 200 and json.loads(toggled.data)["xero_sync"]["push_status"] == "synced"

    edited = app_client.patch(f"/api/crm/customers/{contact_id}", json={"phone_number": "06 555 0202"})
    assert edited.status_code == 200
    assert json.loads(edited.data)["changed"] == ["phone_number"]
    assert xero.updated[-1][1]["phone_number"] == "06 555 0202"

    detail = json.loads(app_client.get(f"/api/crm/customers/{contact_id}").data)
    assert detail["xero_sync"]["syncs"] is True and detail["xero_connection"]["can_write_contacts"] is True


def test_http_refuses_bad_input_and_unknown_contacts(app_client):
    assert app_client.post("/api/crm/customers", json={"name": ""}).status_code == 400
    assert app_client.patch(f"/api/crm/customers/{uuid4()}", json={"name": "x"}).status_code == 404
    assert app_client.patch("/api/crm/customers/not-a-uuid", json={"name": "x"}).status_code == 400
    assert app_client.put(f"/api/crm/customers/{uuid4()}/xero-sync", json={}).status_code == 400
    assert app_client.put("/api/crm/contact-sync-settings", json={"sync_contacts_to_xero": "on"}).status_code == 400


def test_the_sales_default_needs_sales_manage_but_adding_a_customer_does_not(db, org):
    from app.api.app_factory import create_app

    email = f"crm_sales_{uuid4()}@test.com"
    UserRepository(db).create_user(
        org_id=org.id, email=email, password_hash=AuthService.hash_password("TestPass123!"), role=UserRole.SALES
    )
    db.commit()
    flask_app = create_app()
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    with flask_app.test_client() as client:
        client.environ_base["wsgi.url_scheme"] = "https"
        client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
        with flask_app.app_context():
            assert client.post("/auth/login", json={"email": email, "password": "TestPass123!"}).status_code in (
                200,
                201,
            )
            assert client.get("/api/crm/contact-sync-settings").status_code == 200
            assert client.put("/api/crm/contact-sync-settings", json={"sync_contacts_to_xero": True}).status_code == 403
            assert client.post("/api/crm/customers", json={"name": "Sales Made Ltd"}).status_code == 201
