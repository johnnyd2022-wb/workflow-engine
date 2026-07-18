"""Tests for wastage recording and its idempotency (Batch 3).

Wastage disposal is a dual-write: it deducts inventory_items.quantity and appends the
wastage/movement audit rows in one transaction. On a client retry that must not double-apply
— the route accepts an optional idempotency_key and stores the response so a repeat with the
same key + same payload replays the stored result instead of disposing twice. A duplicated
disposal silently corrupts stock and audit numbers, and none of this was tested.

Idempotency is enforced in the route handler (POST /api/core/inventory/wastage), so those
tests drive it through an authenticated Flask test client. Wastage org-scoping is a
repository property, tested directly — this also completes the wastage isolation deferred
from Batch 2.
"""

from decimal import Decimal
from uuid import uuid4

import pytest

from app.core.db import db_session
from app.core.db.models.api_idempotency_key import ApiIdempotencyKey
from app.core.db.models.inventory_item import InventoryItem
from app.core.db.models.inventory_movement import InventoryMovement
from app.core.db.models.inventory_wastage import InventoryWastage
from app.core.db.models.organisation import Organisation
from app.core.db.repositories.wastage_repo import WastageRepository
from app.core.security.auth_service import AuthService
from tests.factories import InventoryItemFactory, OrganisationFactory, WastageFactory


@pytest.fixture
def org(db):
    organisation = OrganisationFactory()
    db.commit()
    # Capture the id as a plain value: the Flask test client's request teardown calls
    # db_session.remove(), which detaches `organisation`, so reading organisation.id in the
    # fixture teardown below would raise DetachedInstanceError. The UUID does not.
    org_id = organisation.id
    yield organisation
    db.rollback()
    # These org children have ON DELETE NO ACTION, so they must be removed before the org.
    # Deleting the org then cascades users + audit_logs + entity_events (all ON DELETE
    # CASCADE from organisations) — deleting the user directly would instead FK-fail on the
    # audit rows login created (users <- audit_logs is NO ACTION).
    for model in (InventoryMovement, InventoryWastage, ApiIdempotencyKey, InventoryItem):
        db.query(model).filter(model.org_id == org_id).delete(synchronize_session=False)
    db.query(Organisation).filter(Organisation.id == org_id).delete(synchronize_session=False)
    db.commit()


@pytest.fixture
def user(db, org):
    from app.core.db.repositories.user_repo import UserRepository

    u = UserRepository(db).create_user(
        org_id=org.id,
        email=f"wastage_{uuid4()}@test.com",
        password_hash=AuthService.hash_password("TestPass123!"),
    )
    db.commit()
    yield u


@pytest.fixture
def app_client(db, org, user):
    """Authenticated Flask test client scoped to `org`."""
    from app.api.app_factory import create_app

    flask_app = create_app()
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False

    with flask_app.test_client() as client:
        client.environ_base["wsgi.url_scheme"] = "https"
        client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
        with flask_app.app_context():
            resp = client.post(
                "/auth/login",
                json={"email": user.email, "password": "TestPass123!"},
                content_type="application/json",
            )
            assert resp.status_code in (200, 201), f"Login failed: {resp.data}"
            yield client


def _quantity_of(item_id):
    return db_session().get(InventoryItem, item_id).quantity


def test_wastage_records_and_deducts_quantity(db, app_client, org):
    item = InventoryItemFactory(org_id=org.id, quantity="10", unit="kg")

    resp = app_client.post(
        "/api/core/inventory/wastage",
        json={"entries": [{"inventory_item_id": str(item.id), "quantity_wasted": "3", "reason": "spillage"}]},
    )

    assert resp.status_code == 201, resp.data
    assert resp.get_json()["success"] is True
    db.expire_all()
    assert _quantity_of(item.id) == Decimal("7")
    assert db.query(InventoryWastage).filter(InventoryWastage.inventory_item_id == item.id).count() == 1


def test_wastage_idempotent_replay_does_not_double_deduct(db, app_client, org):
    item = InventoryItemFactory(org_id=org.id, quantity="10", unit="kg")
    payload = {
        "entries": [{"inventory_item_id": str(item.id), "quantity_wasted": "3", "reason": "spillage"}],
        "idempotency_key": f"key-{uuid4()}",
    }

    first = app_client.post("/api/core/inventory/wastage", json=payload)
    assert first.status_code == 201, first.data
    assert not first.get_json().get("idempotent_replay", False)

    second = app_client.post("/api/core/inventory/wastage", json=payload)

    # Same key + same payload: the stored response is replayed, flagged, and nothing disposes again.
    assert second.status_code == 201, second.data
    assert second.get_json().get("idempotent_replay") is True
    db.expire_all()
    assert _quantity_of(item.id) == Decimal("7")  # deducted once, not twice
    assert db.query(InventoryWastage).filter(InventoryWastage.inventory_item_id == item.id).count() == 1


def test_wastage_key_reuse_with_different_payload_is_rejected(db, app_client, org):
    item = InventoryItemFactory(org_id=org.id, quantity="10", unit="kg")
    key = f"key-{uuid4()}"

    first = app_client.post(
        "/api/core/inventory/wastage",
        json={
            "entries": [{"inventory_item_id": str(item.id), "quantity_wasted": "3", "reason": "spillage"}],
            "idempotency_key": key,
        },
    )
    assert first.status_code == 201, first.data

    # Same key, different quantity → the request is refused rather than silently applied or replayed.
    conflict = app_client.post(
        "/api/core/inventory/wastage",
        json={
            "entries": [{"inventory_item_id": str(item.id), "quantity_wasted": "5", "reason": "spillage"}],
            "idempotency_key": key,
        },
    )
    assert conflict.status_code == 409, conflict.data
    assert conflict.get_json()["error_code"] == "IDEMPOTENCY_PAYLOAD_MISMATCH"
    db.expire_all()
    assert _quantity_of(item.id) == Decimal("7")  # only the first disposal applied


def test_wastage_records_are_org_scoped(db, two_org_two_user):
    org_a = two_org_two_user["org_a"]
    org_b = two_org_two_user["org_b"]
    item_a = InventoryItemFactory(org_id=org_a.id)
    item_b = InventoryItemFactory(org_id=org_b.id)
    WastageFactory(org_id=org_a.id, inventory_item_id=item_a.id)
    WastageFactory(org_id=org_b.id, inventory_item_id=item_b.id)
    db.commit()

    try:
        repo = WastageRepository(db)
        a_records = repo.list_wastage_records(org_a.id)
        a_item_ids = {r.inventory_item_id for r in a_records}
        assert item_a.id in a_item_ids
        assert item_b.id not in a_item_ids
    finally:
        for org_id in (org_a.id, org_b.id):
            db.query(InventoryWastage).filter(InventoryWastage.org_id == org_id).delete(synchronize_session=False)
            db.query(InventoryItem).filter(InventoryItem.org_id == org_id).delete(synchronize_session=False)
        db.commit()
