"""Tests for the organisation routes (/org/*): settings read/update and user membership.

These had no direct coverage. They are an auth-adjacent surface — settings changes and user
add/remove are ADMIN-only, and membership changes are exactly where a broken role check
would let a member escalate. The tests drive the real routes through authenticated Flask
test clients, one ADMIN and one MEMBER, so the role boundary is exercised, not assumed.
"""

from uuid import uuid4

import pytest

from app.core.db.models.organisation import Organisation
from app.core.db.models.user import UserRole
from app.core.db.repositories.user_repo import UserRepository
from app.core.security.auth_service import AuthService
from tests.factories import OrganisationFactory

PASSWORD = "TestPass123!"


@pytest.fixture
def org_world(db):
    """One org with an ADMIN and a MEMBER, plus an authenticated client logged in as each."""
    org = OrganisationFactory()
    db.commit()
    org_id = org.id  # captured before test-client requests detach the ORM instance

    repo = UserRepository(db)
    admin = repo.create_user(
        org_id=org_id,
        email=f"admin_{uuid4()}@test.com",
        password_hash=AuthService.hash_password(PASSWORD),
        role=UserRole.ADMIN,
        is_active=True,
    )
    member = repo.create_user(
        org_id=org_id,
        email=f"member_{uuid4()}@test.com",
        password_hash=AuthService.hash_password(PASSWORD),
        role=UserRole.MEMBER,
        is_active=True,
    )
    db.commit()
    admin_email, member_email, member_id = admin.email, member.email, member.id

    from app.api.app_factory import create_app

    flask_app = create_app()
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False

    def _client(email=None):
        c = flask_app.test_client()
        c.environ_base["wsgi.url_scheme"] = "https"
        c.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
        if email is not None:
            r = c.post("/auth/login", json={"email": email, "password": PASSWORD}, content_type="application/json")
            assert r.status_code in (200, 201), f"login failed: {r.data}"
        return c

    with flask_app.app_context():
        yield {
            "org_id": org_id,
            "org_name": org.name,
            "admin_client": _client(admin_email),
            "member_client": _client(member_email),
            "anon_client": _client(None),
            "member_id": member_id,
        }

    # Deleting the org cascades users + audit_logs (ON DELETE CASCADE from organisations).
    db.rollback()
    db.query(Organisation).filter(Organisation.id == org_id).delete(synchronize_session=False)
    db.commit()


# --- Read -----------------------------------------------------------------------------


def test_get_org_returns_current_org(org_world):
    resp = org_world["admin_client"].get("/org")
    assert resp.status_code == 200, resp.data
    assert resp.get_json()["organisation"]["name"] == org_world["org_name"]


def test_get_org_unauthenticated_redirects_to_login(org_world):
    # /org is an HTML route: the global 401 handler redirects unauthenticated browser GETs
    # to the login page (/) rather than returning JSON 401 (that is the /api/* contract).
    resp = org_world["anon_client"].get("/org")
    assert resp.status_code == 302
    assert resp.headers["Location"] in ("/", "http://localhost/")


# --- Settings update (admin only) -----------------------------------------------------


def test_patch_org_updates_name_as_admin(org_world):
    resp = org_world["admin_client"].patch("/org", json={"name": "Renamed Org"})
    assert resp.status_code == 200, resp.data
    assert resp.get_json()["organisation"]["name"] == "Renamed Org"
    # And the change is visible on a subsequent read.
    assert org_world["admin_client"].get("/org").get_json()["organisation"]["name"] == "Renamed Org"


def test_patch_org_forbidden_for_member(org_world):
    resp = org_world["member_client"].patch("/org", json={"name": "Member Rename"})
    assert resp.status_code == 403


# --- Membership -----------------------------------------------------------------------


def test_list_users_includes_org_members(org_world):
    resp = org_world["admin_client"].get("/org/users")
    assert resp.status_code == 200, resp.data
    roles = {u["role"] for u in resp.get_json()["users"]}
    assert "admin" in roles and "member" in roles


def test_create_user_as_admin(org_world):
    new_email = f"new_{uuid4()}@test.com"
    resp = org_world["admin_client"].post("/org/users", json={"email": new_email, "password": PASSWORD})
    assert resp.status_code == 201, resp.data
    assert resp.get_json()["user"]["email"] == new_email


def test_create_user_forbidden_for_member(org_world):
    resp = org_world["member_client"].post("/org/users", json={"email": f"x_{uuid4()}@test.com", "password": PASSWORD})
    assert resp.status_code == 403


def test_create_user_duplicate_email_is_rejected(org_world):
    email = f"dup_{uuid4()}@test.com"
    first = org_world["admin_client"].post("/org/users", json={"email": email, "password": PASSWORD})
    assert first.status_code == 201, first.data
    second = org_world["admin_client"].post("/org/users", json={"email": email, "password": PASSWORD})
    assert second.status_code == 400


def test_delete_user_as_admin(org_world):
    resp = org_world["admin_client"].delete(f"/org/users/{org_world['member_id']}")
    assert resp.status_code == 200, resp.data


def test_delete_own_account_is_rejected(org_world):
    # The admin's own id: read it back from the user list, then try to delete self.
    users = org_world["admin_client"].get("/org/users").get_json()["users"]
    admin_id = next(u["id"] for u in users if u["role"] == "admin")
    resp = org_world["admin_client"].delete(f"/org/users/{admin_id}")
    assert resp.status_code == 400


def test_delete_unknown_user_is_404(org_world):
    resp = org_world["admin_client"].delete(f"/org/users/{uuid4()}")
    assert resp.status_code == 404
