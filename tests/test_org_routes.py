"""Tests for the organisation routes (/org/*): settings read/update and user membership.

These had no direct coverage. They are an auth-adjacent surface — settings changes and user
add/remove are ADMIN-only, and membership changes are exactly where a broken role check
would let a member escalate. The tests drive the real routes through authenticated Flask
test clients, one ADMIN and one MEMBER, so the role boundary is exercised, not assumed.
"""

from uuid import uuid4

import pytest

from app.core.db.models.entity_event import EntityEvent
from app.core.db.models.organisation import Organisation
from app.core.db.models.user import User, UserRole
from app.core.db.repositories.organisation_repo import OrganisationRepository
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


def test_delete_user_forbidden_for_member(org_world):
    resp = org_world["member_client"].delete(f"/org/users/{org_world['member_id']}")
    assert resp.status_code == 403


# --- Cross-tenant isolation (AC8): org A must not see/create/delete org B's users -----


@pytest.fixture
def two_org_world(db):
    """Two orgs, each with an authenticated ADMIN client — the shape AC8 needs to prove
    a query in one org's request can't reach another org's users."""
    org_a = OrganisationFactory()
    org_b = OrganisationFactory()
    db.commit()
    org_a_id, org_b_id = org_a.id, org_b.id

    repo = UserRepository(db)
    admin_a = repo.create_user(
        org_id=org_a_id,
        email=f"admin_a_{uuid4()}@test.com",
        password_hash=AuthService.hash_password(PASSWORD),
        role=UserRole.ADMIN,
        is_active=True,
    )
    admin_b = repo.create_user(
        org_id=org_b_id,
        email=f"admin_b_{uuid4()}@test.com",
        password_hash=AuthService.hash_password(PASSWORD),
        role=UserRole.ADMIN,
        is_active=True,
    )
    db.commit()
    admin_a_email, admin_b_email, admin_b_id = admin_a.email, admin_b.email, admin_b.id

    from app.api.app_factory import create_app

    flask_app = create_app()
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False

    def _client(email):
        c = flask_app.test_client()
        c.environ_base["wsgi.url_scheme"] = "https"
        c.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
        r = c.post("/auth/login", json={"email": email, "password": PASSWORD}, content_type="application/json")
        assert r.status_code in (200, 201), f"login failed: {r.data}"
        return c

    with flask_app.app_context():
        yield {
            "org_a_id": org_a_id,
            "org_b_id": org_b_id,
            "admin_a_client": _client(admin_a_email),
            "admin_b_client": _client(admin_b_email),
            "admin_b_id": admin_b_id,
        }

    # Deleting the orgs cascades users + audit_logs (ON DELETE CASCADE from organisations) —
    # deleting users directly here would violate the audit_logs FK for rows logged during
    # the test (e.g. create_user's log_action).
    db.rollback()
    db.query(Organisation).filter(Organisation.id.in_([org_a_id, org_b_id])).delete(synchronize_session=False)
    db.commit()


def test_list_users_excludes_other_org(two_org_world):
    resp = two_org_world["admin_a_client"].get("/org/users")
    assert resp.status_code == 200, resp.data
    ids = {u["id"] for u in resp.get_json()["users"]}
    assert str(two_org_world["admin_b_id"]) not in ids


def test_delete_user_in_other_org_is_404_not_deleted(two_org_world):
    resp = two_org_world["admin_a_client"].delete(f"/org/users/{two_org_world['admin_b_id']}")
    assert resp.status_code == 404, resp.data

    # The org B user must be unaffected by org A's attempt.
    listing = two_org_world["admin_b_client"].get("/org/users").get_json()["users"]
    target = next(u for u in listing if u["id"] == str(two_org_world["admin_b_id"]))
    assert target["is_active"] is True


def test_created_user_not_visible_to_other_org(two_org_world):
    new_email = f"new_{uuid4()}@test.com"
    create_resp = two_org_world["admin_a_client"].post("/org/users", json={"email": new_email, "password": PASSWORD})
    assert create_resp.status_code == 201, create_resp.data
    new_id = create_resp.get_json()["user"]["id"]

    listing = two_org_world["admin_b_client"].get("/org/users").get_json()["users"]
    assert new_id not in {u["id"] for u in listing}


def test_get_org_is_scoped_to_caller(two_org_world):
    # AC8 covers GET/POST /org/users and DELETE .../users/<id> above; GET /org and PATCH /org
    # take no org_id parameter (they resolve entirely through g.current_org_id from the
    # session), so the "cross-tenant" proof here is that each caller's own org is returned
    # and the two are never the same record.
    org_a_view = two_org_world["admin_a_client"].get("/org").get_json()["organisation"]
    org_b_view = two_org_world["admin_b_client"].get("/org").get_json()["organisation"]
    assert org_a_view["id"] == str(two_org_world["org_a_id"])
    assert org_b_view["id"] == str(two_org_world["org_b_id"])
    assert org_a_view["id"] != org_b_view["id"]


def test_patch_org_does_not_affect_other_org(two_org_world):
    org_b_before = two_org_world["admin_b_client"].get("/org").get_json()["organisation"]["name"]

    resp = two_org_world["admin_a_client"].patch("/org", json={"name": "Org A Renamed By Test"})
    assert resp.status_code == 200, resp.data

    org_b_after = two_org_world["admin_b_client"].get("/org").get_json()["organisation"]
    assert org_b_after["name"] == org_b_before
    assert org_b_after["name"] != "Org A Renamed By Test"


# --- AC3: invalid status is rejected before any write ----------------------------------


def test_patch_org_rejects_invalid_status(org_world):
    resp = org_world["admin_client"].patch("/org", json={"status": "not_a_real_status"})
    assert resp.status_code == 400

    # DB untouched: the org's status is still the factory default.
    after = org_world["admin_client"].get("/org").get_json()["organisation"]
    assert after["status"] == "active"


# --- AC2: PATCH /org logs and emits a diff-scoped audit event --------------------------


def test_patch_org_emits_diff_scoped_audit_event(org_world, db):
    resp = org_world["admin_client"].patch("/org", json={"name": "Audited Org Name"})
    assert resp.status_code == 200, resp.data

    event = (
        db.query(EntityEvent)
        .filter(
            EntityEvent.org_id == org_world["org_id"],
            EntityEvent.event_type == "org.settings_updated",
        )
        .order_by(EntityEvent.created_at.desc())
        .first()
    )
    assert event is not None, "expected an org.settings_updated event to be emitted"
    assert event.diff["name"]["after"] == "Audited Org Name"
    # Only the field that actually changed (name) appears in the diff — status was
    # untouched by this request and must not show up as a spurious change.
    assert "status" not in event.diff


# --- AC5: invalid role is rejected, and the stored password is hashed -------------------


def test_create_user_rejects_invalid_role(org_world):
    resp = org_world["admin_client"].post(
        "/org/users", json={"email": f"badrole_{uuid4()}@test.com", "password": PASSWORD, "role": "superuser"}
    )
    assert resp.status_code == 400


def test_create_user_hashes_password_before_storage(org_world, db):
    new_email = f"hashed_{uuid4()}@test.com"
    resp = org_world["admin_client"].post("/org/users", json={"email": new_email, "password": PASSWORD})
    assert resp.status_code == 201, resp.data

    stored = db.query(User).filter(User.email == new_email).first()
    assert stored is not None
    assert stored.password_hash != PASSWORD
    assert AuthService.verify_password(PASSWORD, stored.password_hash)


# --- AC6: malformed user_id is a 400, not a 500/404 -------------------------------------


def test_delete_user_invalid_uuid_is_400(org_world):
    resp = org_world["admin_client"].delete("/org/users/not-a-uuid")
    assert resp.status_code == 400


# --- AC4: the listing includes inactive (soft-deleted) users, not just active ones -----


def test_list_users_includes_inactive_users(org_world):
    del_resp = org_world["admin_client"].delete(f"/org/users/{org_world['member_id']}")
    assert del_resp.status_code == 200, del_resp.data

    users = org_world["admin_client"].get("/org/users").get_json()["users"]
    target = next(u for u in users if u["id"] == str(org_world["member_id"]))
    assert target["is_active"] is False


# --- Regression: 500 responses must never leak exception text (security-audit F1) ------
#
# security-audit patched update_org/list_users/delete_user to return a fixed generic
# message on unexpected errors instead of str(e). These tests force that path via
# monkeypatch and prove the raw exception text never reaches the client — reverting the
# patch (re-introducing f"...{str(e)}") makes each of these fail.

_LEAK_MARKER = "no-such-column-xyz-should-never-reach-the-client"


def test_update_org_failure_returns_generic_error(org_world, monkeypatch):
    def _boom(self, *args, **kwargs):
        raise RuntimeError(_LEAK_MARKER)

    monkeypatch.setattr(OrganisationRepository, "update_org", _boom)

    resp = org_world["admin_client"].patch("/org", json={"name": "Whatever"})
    assert resp.status_code == 500
    body = resp.get_data(as_text=True)
    assert _LEAK_MARKER not in body
    assert resp.get_json()["error"] == "Failed to update organisation"


def test_list_users_failure_returns_generic_error(org_world, monkeypatch):
    def _boom(self, *args, **kwargs):
        raise RuntimeError(_LEAK_MARKER)

    monkeypatch.setattr(UserRepository, "list_users_for_org", _boom)

    resp = org_world["admin_client"].get("/org/users")
    assert resp.status_code == 500
    body = resp.get_data(as_text=True)
    assert _LEAK_MARKER not in body
    assert resp.get_json()["error"] == "Failed to list users"


def test_delete_user_failure_returns_generic_error(org_world, monkeypatch):
    def _boom(self, *args, **kwargs):
        raise RuntimeError(_LEAK_MARKER)

    monkeypatch.setattr(UserRepository, "delete_user", _boom)

    resp = org_world["admin_client"].delete(f"/org/users/{org_world['member_id']}")
    assert resp.status_code == 500
    body = resp.get_data(as_text=True)
    assert _LEAK_MARKER not in body
    assert resp.get_json()["error"] == "Failed to delete user"


def test_forbidden_role_check_logs_access_denied(org_world, monkeypatch):
    """observability: @requires_role must log an access_denied warning, not fail silently."""
    from app.core.security import permissions

    calls = []
    monkeypatch.setattr(permissions.logger, "warning", lambda event, **kw: calls.append((event, kw)))

    resp = org_world["member_client"].post("/org/users", json={"email": "x@test.com", "password": PASSWORD})
    assert resp.status_code == 403

    assert len(calls) == 1
    event, kw = calls[0]
    assert event == "access_denied"
    assert kw["reason"] == "role_not_allowed"
    assert kw["path"] == "/org/users"
    assert kw["user_role"] == "member"
