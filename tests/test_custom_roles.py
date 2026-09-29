"""Plan item 0.4c: custom roles, cloned from a built-in role with permissions ticked."""

from uuid import uuid4

import pytest

from app.core.db.models.org_role import OrgRole
from app.core.db.models.organisation import Organisation
from app.core.db.models.user import User, UserRole
from app.core.security.access_policy import GRANTABLE, ROLE_PERMISSIONS, allows, permissions_for
from app.core.security.people import PeopleError, validate_custom_role
from tests.dag_traversal_helpers import clear_org_synthetic_data
from tests.factories import DEFAULT_TEST_PASSWORD
from tests.test_compliant_routes import _admin_client, flask_app  # noqa: F401 -- fixture re-export


def test_validation():
    made = validate_custom_role({"name": "  Cellar   door ", "base_role": "sales"}, set())
    assert made["name"] == "Cellar door" and made["permissions"] == sorted(ROLE_PERMISSIONS[UserRole.SALES])
    for bad, message in (
        ({"name": "x", "base_role": "admin"}, "Admin"),
        ({"name": "x", "base_role": "member", "permissions": ["users.manage"]}, "Only admins"),
        ({"name": "x", "base_role": "member", "permissions": ["nope"]}, "Unknown permission"),
        ({"name": "x", "base_role": "member", "permissions": []}, "at least one"),
        ({"name": "Production", "base_role": "member"}, "already"),
        ({"name": "", "base_role": "member"}, "name"),
    ):
        with pytest.raises(PeopleError, match=message):
            validate_custom_role(bad, set())
    with pytest.raises(PeopleError, match="already"):
        validate_custom_role({"name": "cellar door", "base_role": "sales"}, {"cellar door"})
    assert "compliance.manage" not in GRANTABLE and "production.design" in GRANTABLE


def _login(flask_app, email):  # noqa: F811
    client = flask_app.test_client()
    client.environ_base["wsgi.url_scheme"] = "https"
    client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
    assert client.post("/auth/login", json={"email": email, "password": DEFAULT_TEST_PASSWORD}).status_code == 200
    return client


@pytest.fixture
def org(db, flask_app):  # noqa: F811
    org, client = _admin_client(db, flask_app)
    yield org, client
    db.rollback()
    db.query(User).filter(User.org_id == org.id).update({User.custom_role_id: None}, synchronize_session=False)
    db.query(OrgRole).filter(OrgRole.org_id == org.id).delete(synchronize_session=False)
    db.commit()
    clear_org_synthetic_data(db, org.id)
    db.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
    db.commit()


def test_a_custom_role_governs_what_its_people_can_do(org, db, flask_app):  # noqa: F811
    o, admin = org
    body = admin.get("/org/roles").get_json()
    assert not any(b["can_clone"] for b in body["built_in"] if b["value"] == "admin")
    made = admin.post(
        "/org/roles",
        json={
            "name": "Cellar door",
            "base_role": "sales",
            "permissions": ["sales.view", "sales.record", "inventory.view"],
        },
    )
    assert made.status_code == 201, made.get_json()
    role = made.get_json()["custom_roles"][0]
    assert role["holders"] == 0 and role["value"] == f"custom:{role['id']}"
    assert admin.post("/org/roles", json={"name": "cellar DOOR", "base_role": "sales"}).status_code == 400

    email = f"cellar-{uuid4()}@test.com"
    created = admin.post("/org/users", json={"email": email, "password": DEFAULT_TEST_PASSWORD, "role": role["value"]})
    assert created.status_code == 201, created.get_json()
    person = created.get_json()["user"]
    assert person["role"] == role["value"] and person["role_label"] == "Cellar door"
    user = db.query(User).filter(User.email == email).one()
    assert user.role == UserRole.SALES and str(user.custom_role_id) == role["id"]

    staff = _login(flask_app, email)
    me = staff.get("/auth/me").get_json()["user"]
    assert me["role_label"] == "Cellar door" and me["permissions"] == ["inventory.view", "sales.record", "sales.view"]
    assert allows(user, "crm.crm_api.create_note", "POST")  # any crm write needs sales.record
    assert staff.get("/org/roles").status_code == 403

    # Untick sales.record: everyone with the role loses it at once.
    changed = admin.patch(f"/org/roles/{role['id']}", json={"permissions": ["sales.view", "inventory.view"]})
    assert changed.status_code == 200 and changed.get_json()["custom_roles"][0]["holders"] == 1
    db.expire_all()
    user = db.query(User).filter(User.email == email).one()
    assert permissions_for(user) == frozenset({"sales.view", "inventory.view"})
    assert not allows(user, "crm.crm_api.create_note", "POST")
    assert staff.get("/auth/me").get_json()["user"]["permissions"] == ["inventory.view", "sales.view"]

    assert admin.delete(f"/org/roles/{role['id']}").status_code == 409  # still held
    moved = admin.patch(f"/org/users/{user.id}", json={"role": "sales"})
    assert moved.status_code == 200 and moved.get_json()["user"]["role"] == "sales"
    assert admin.delete(f"/org/roles/{role['id']}").status_code == 200
    db.expire_all()
    assert db.query(User).filter(User.email == email).one().custom_role_id is None


def test_roles_are_org_scoped_and_admins_cant_change_their_own(org, db, flask_app):  # noqa: F811
    o, admin = org
    other_org, other_admin = _admin_client(db, flask_app)
    try:
        theirs = other_admin.post("/org/roles", json={"name": "Theirs", "base_role": "production"}).get_json()
        their_value = theirs["custom_roles"][0]["value"]
        bad = admin.post("/org/users", json={"email": f"x-{uuid4()}@test.com", "role": their_value})
        assert bad.status_code == 400
        assert admin.patch(f"/org/roles/{theirs['custom_roles'][0]['id']}", json={"name": "Mine"}).status_code == 404

        mine = admin.post("/org/roles", json={"name": "Floor", "base_role": "production"}).get_json()["custom_roles"][0]
        me = admin.get("/auth/me").get_json()["user"]
        own = admin.patch(f"/org/users/{me['id']}", json={"role": mine["value"]})
        assert own.status_code == 400 and "own role" in own.get_json()["error"]

        auditor = admin.post("/org/roles", json={"name": "Verifier", "base_role": "auditor"}).get_json()
        verifier = next(r for r in auditor["custom_roles"] if r["name"] == "Verifier")
        no_end = admin.post("/org/users", json={"email": f"v-{uuid4()}@test.com", "role": verifier["value"]})
        assert no_end.status_code == 400  # auditor-based roles need an end date
        options = admin.get("/org/users").get_json()["roles"]
        assert next(r for r in options if r["value"] == verifier["value"])["needs_expiry"] is True
    finally:
        db.query(OrgRole).filter(OrgRole.org_id == other_org.id).delete(synchronize_session=False)
        db.commit()
        clear_org_synthetic_data(db, other_org.id)
        db.query(Organisation).filter(Organisation.id == other_org.id).delete(synchronize_session=False)
        db.commit()


def test_a_role_from_another_org_grants_nothing(org, db):
    o, _admin = org
    stranger_role = OrgRole(id=uuid4(), org_id=uuid4(), name="x", base_role="member", permissions=["sales.view"])
    user = db.query(User).filter(User.org_id == o.id).first()
    user.custom_role_id = stranger_role.id  # not flushed: the lookup finds nothing for this org
    assert permissions_for(user) == frozenset()
    db.rollback()
