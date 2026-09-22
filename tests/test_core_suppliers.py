"""Core suppliers: audited address book, org isolation and the inventory import."""

from uuid import UUID, uuid4

import pytest

from app.core.backend.suppliers import (
    SupplierError,
    create_supplier,
    delete_supplier,
    import_from_inventory,
    list_suppliers,
    update_supplier,
)
from app.core.db.models.audit_log import AuditLog
from app.core.db.models.entity_event import EntityEvent
from app.core.db.models.inventory_item import InventoryItem
from app.core.db.models.organisation import Organisation
from app.core.db.models.user import User
from tests.factories import InventoryItemFactory, OrganisationFactory, UserFactory


@pytest.fixture
def flask_app():
    from app.api.app_factory import create_app

    app = create_app()
    app.config.update(TESTING=True)
    with app.app_context():
        yield app


@pytest.fixture
def world(db, flask_app):
    org_a, org_b = OrganisationFactory(), OrganisationFactory()
    suffix = uuid4().hex
    user = UserFactory(org_id=org_a.id, email=f"supplier-a-{suffix}@example.test")
    db.commit()
    yield {"a": org_a, "b": org_b, "user": user}
    db.query(InventoryItem).filter(InventoryItem.org_id.in_([org_a.id, org_b.id])).delete(synchronize_session=False)
    db.query(AuditLog).filter(AuditLog.org_id.in_([org_a.id, org_b.id])).delete(synchronize_session=False)
    db.query(User).filter(User.org_id.in_([org_a.id, org_b.id])).delete(synchronize_session=False)
    db.query(Organisation).filter(Organisation.id.in_([org_a.id, org_b.id])).delete(synchronize_session=False)
    db.commit()


def _events(db, org_id, supplier_id):
    return (
        db.query(EntityEvent)
        .filter(EntityEvent.org_id == org_id, EntityEvent.entity_id == supplier_id)
        .order_by(EntityEvent.seq)
        .all()
    )


def test_create_edit_delete_are_each_audited_with_what_changed(world, db):
    org, user = world["a"], world["user"]
    created = create_supplier(db, org.id, user.id, {"name": " Davis Trading ", "phone": "04 568 5599", "notes": ""})
    supplier_id = created["id"]
    assert (created["name"], created["phone"], created["notes"]) == ("Davis Trading", "04 568 5599", None)

    updated = update_supplier(db, org.id, user.id, UUID(supplier_id), {"phone": "04 000", "notes": "Bulk botanicals"})
    assert updated["phone"] == "04 000"
    assert delete_supplier(db, org.id, user.id, UUID(supplier_id)) is True

    events = _events(db, org.id, UUID(supplier_id))
    assert [event.event_type for event in events] == ["supplier.created", "supplier.updated", "supplier.deleted"]
    assert events[1].diff == {
        "phone": {"before": "04 568 5599", "after": "04 000"},
        "notes": {"before": None, "after": "Bulk botanicals"},
    }
    assert events[2].payload["name"] == "Davis Trading"  # the deleted supplier's details are kept in the log
    actions = [
        row.action for row in db.query(AuditLog).filter(AuditLog.org_id == org.id, AuditLog.entity == "supplier")
    ]
    assert sorted(actions) == ["create", "delete", "update"]


def test_a_no_op_edit_is_not_logged_and_names_stay_unique_per_org(world, db):
    org, other, user = world["a"], world["b"], world["user"]
    first = create_supplier(db, org.id, user.id, {"name": "Alembics"})
    update_supplier(db, org.id, user.id, UUID(first["id"]), {"name": "Alembics"})
    assert [event.event_type for event in _events(db, org.id, UUID(first["id"]))] == ["supplier.created"]

    with pytest.raises(SupplierError, match="already exists"):
        create_supplier(db, org.id, user.id, {"name": "ALEMBICS"})
    with pytest.raises(SupplierError, match="name is required"):
        create_supplier(db, org.id, user.id, {"name": "  "})
    with pytest.raises(SupplierError, match="valid address"):
        create_supplier(db, org.id, user.id, {"name": "Bad", "email": "not-an-email"})

    create_supplier(db, other.id, None, {"name": "Alembics"})  # another org may use the same name
    assert update_supplier(db, other.id, None, UUID(first["id"]), {"name": "x"}) is None  # and cannot touch ours
    assert [row["name"] for row in list_suppliers(db, other.id)] == ["Alembics"]


def test_import_from_inventory_adds_each_named_supplier_once(world, db):
    org, user = world["a"], world["user"]
    for name in ("Alembics", "Alembics", "Davis Trading", None):
        InventoryItemFactory(org_id=org.id, name=f"Item {uuid4().hex[:6]}", supplier=name)
    db.commit()
    create_supplier(db, org.id, user.id, {"name": "davis trading", "phone": "04 1"})

    result = import_from_inventory(db, org.id, user.id)

    assert result["created"] == ["Alembics"]  # Davis Trading already exists, whatever its capitalisation
    assert sorted(row["name"] for row in result["suppliers"]) == ["Alembics", "davis trading"]
    assert import_from_inventory(db, org.id, user.id)["created"] == []
    imported = next(row for row in result["suppliers"] if row["name"] == "Alembics")
    created_event = _events(db, org.id, UUID(imported["id"]))[0]
    assert (created_event.payload["source"], created_event.payload["inventory_items"]) == ("inventory", 2)


def test_supplier_routes_require_login_and_round_trip_json(db, flask_app):
    from app.core.db.models.user import UserRole
    from app.core.db.repositories.user_repo import UserRepository
    from app.core.security.auth_service import AuthService
    from tests.factories import DEFAULT_TEST_PASSWORD

    flask_app.config.update(WTF_CSRF_ENABLED=False)
    org = OrganisationFactory()
    email = f"supplier-route-{uuid4().hex}@example.test"
    UserRepository(db).create_user(
        org_id=org.id,
        email=email,
        password_hash=AuthService.hash_password(DEFAULT_TEST_PASSWORD),
        role=UserRole.ADMIN,
        is_active=True,
    )
    db.commit()
    client = flask_app.test_client()
    client.environ_base["wsgi.url_scheme"] = "https"
    client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
    try:
        assert client.get("/api/core/suppliers").status_code in (401, 403)
        assert client.post("/auth/login", json={"email": email, "password": DEFAULT_TEST_PASSWORD}).status_code == 200

        made = client.post("/api/core/suppliers", json={"name": "Alembics", "email": "a@b.nz", "address": "Waiheke"})
        assert made.status_code == 201
        supplier_id = made.get_json()["supplier"]["id"]
        assert client.post("/api/core/suppliers", json={"name": "alembics"}).status_code == 400
        edited = client.put(f"/api/core/suppliers/{supplier_id}", json={"contact_name": "Sam"})
        assert edited.get_json()["supplier"]["contact_name"] == "Sam"
        assert [row["name"] for row in client.get("/api/core/suppliers").get_json()["suppliers"]] == ["Alembics"]
        assert client.put(f"/api/core/suppliers/{uuid4()}", json={"name": "x"}).status_code == 404
        assert client.put("/api/core/suppliers/not-a-uuid", json={"name": "x"}).status_code == 400
        assert client.post("/api/core/suppliers/import-from-inventory").get_json()["created"] == []
        assert client.delete(f"/api/core/suppliers/{supplier_id}").status_code == 200
        assert client.delete(f"/api/core/suppliers/{supplier_id}").status_code == 404
        page = client.get("/core")
        assert page.status_code == 200 and b"data-supplier-add" in page.data and b"core-suppliers.js" in page.data
        assert b'href="/core/suppliers"' in page.data  # "View suppliers" is a link to the page, not a modal
        register = client.get("/core/suppliers")
        assert register.status_code == 200
        assert b"data-suppliers-page" in register.data and b"core-suppliers-page.js" in register.data
    finally:
        db.rollback()
        db.query(AuditLog).filter(AuditLog.org_id == org.id).delete(synchronize_session=False)
        db.query(User).filter(User.org_id == org.id).delete(synchronize_session=False)
        db.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
        db.commit()
