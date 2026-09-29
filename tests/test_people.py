"""Plan item 0.4: managing people (invites, roles, last-admin and self-edit guards)."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.core.db.models.organisation import Organisation
from app.core.db.models.user import User, UserRole
from app.core.db.repositories.user_repo import UserRepository
from app.core.security.auth_service import AuthService
from app.core.security.people import PeopleError, parse_access_expiry
from tests.factories import DEFAULT_TEST_PASSWORD, OrganisationFactory

PASSWORD = DEFAULT_TEST_PASSWORD


@pytest.fixture
def world(db):
    org = OrganisationFactory()
    db.commit()
    org_id = org.id
    email = f"admin_{uuid4()}@test.com"
    admin = UserRepository(db).create_user(
        org_id=org_id, email=email, password_hash=AuthService.hash_password(PASSWORD), role=UserRole.ADMIN
    )
    db.commit()

    from app.api.app_factory import create_app

    flask_app = create_app()
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False

    def client(login_email=None, password=PASSWORD):
        c = flask_app.test_client()
        c.environ_base["wsgi.url_scheme"] = "https"
        c.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
        if login_email:
            resp = c.post("/auth/login", json={"email": login_email, "password": password})
            assert resp.status_code == 200, resp.get_json()
        return c

    with flask_app.app_context():
        yield {"admin_email": email, "admin_id": admin.id, "client": client, "org_id": org_id}

    db.rollback()
    db.query(Organisation).filter(Organisation.id == org_id).delete(synchronize_session=False)
    db.commit()


def test_invite_link_flow(world, db):
    admin = world["client"](world["admin_email"])
    email = f"new_{uuid4()}@example.test"
    resp = admin.post("/org/users", json={"email": email, "role": "production", "first_name": "Nik"})
    assert resp.status_code == 201, resp.get_json()
    body = resp.get_json()
    assert body["user"]["status"] == "invited"
    assert "/invite/" in body["invite_url"]
    token = body["invite_url"].rsplit("/", 1)[1]

    # Only a hash is stored, and the invited account can't sign in yet.
    user = db.query(User).filter(User.email == email).one()
    assert user.invite_token_hash and token not in user.invite_token_hash
    anon = world["client"]()
    assert anon.post("/auth/login", json={"email": email, "password": "whatever-123"}).status_code == 401

    page = anon.get(f"/invite/{token}")
    assert page.status_code == 200
    assert email in page.get_data(as_text=True)

    short = anon.post("/auth/accept-invite", json={"token": token, "password": "short", "password_confirm": "short"})
    assert short.status_code == 400
    ok = anon.post(
        "/auth/accept-invite", json={"token": token, "password": "Str0ng!pass", "password_confirm": "Str0ng!pass"}
    )
    assert ok.status_code == 200, ok.get_json()

    # One-time: the link is dead now, and the new password works.
    assert anon.get(f"/invite/{token}").status_code == 404
    again = anon.post(
        "/auth/accept-invite", json={"token": token, "password": "Str0ng!pass", "password_confirm": "Str0ng!pass"}
    )
    assert again.status_code == 400
    new_user = world["client"](email, "Str0ng!pass")
    me = new_user.get("/auth/me").get_json()["user"]
    assert me["role"] == "production"


def test_expired_and_reissued_invites(world, db):
    admin = world["client"](world["admin_email"])
    body = admin.post("/org/users", json={"email": f"late_{uuid4()}@example.test", "role": "sales"}).get_json()
    old_token = body["invite_url"].rsplit("/", 1)[1]
    user = db.get(User, __import__("uuid").UUID(body["user"]["id"]))

    user.invite_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    anon = world["client"]()
    assert anon.get(f"/invite/{old_token}").status_code == 404

    reissued = admin.post(f"/org/users/{body['user']['id']}/invite").get_json()
    new_token = reissued["invite_url"].rsplit("/", 1)[1]
    assert new_token != old_token
    assert anon.get(f"/invite/{new_token}").status_code == 200


def test_last_admin_and_self_edit_guards(world, db):
    admin = world["client"](world["admin_email"])
    me = str(world["admin_id"])
    own_role = admin.patch(f"/org/users/{me}", json={"role": "member"})
    assert own_role.status_code == 400
    assert "own role" in own_role.get_json()["error"]
    assert admin.patch(f"/org/users/{me}", json={"is_active": False}).status_code == 400

    # A second admin can't demote the only other admin once they're the last one.
    second_email = f"admin2_{uuid4()}@example.test"
    second = admin.post(
        "/org/users", json={"email": second_email, "role": "admin", "password": "Str0ng!pass"}
    ).get_json()
    second_client = world["client"](second_email, "Str0ng!pass")
    assert second_client.patch(f"/org/users/{me}", json={"role": "member"}).status_code == 200
    # Now `second` is the only admin: nobody (not even themselves) can remove that.
    back = admin  # demoted to member: can't manage people any more
    assert back.patch(f"/org/users/{second['user']['id']}", json={"role": "member"}).status_code == 403
    last = second_client.delete(f"/org/users/{me}")
    assert last.status_code == 200  # deactivating a member is fine


def test_auditor_needs_an_end_date_within_90_days(world):
    admin = world["client"](world["admin_email"])
    no_date = admin.post("/org/users", json={"email": f"aud_{uuid4()}@example.test", "role": "auditor"})
    assert no_date.status_code == 400
    too_long = (datetime.now(UTC) + timedelta(days=120)).date().isoformat()
    long_resp = admin.post(
        "/org/users", json={"email": f"aud_{uuid4()}@example.test", "role": "auditor", "access_expires_at": too_long}
    )
    assert long_resp.status_code == 400
    good = (datetime.now(UTC) + timedelta(days=14)).date().isoformat()
    ok = admin.post(
        "/org/users", json={"email": f"aud_{uuid4()}@example.test", "role": "auditor", "access_expires_at": good}
    )
    assert ok.status_code == 201
    assert ok.get_json()["user"]["access_expires_at"].startswith(good)


def test_bare_date_means_end_of_that_day_in_new_zealand():
    now = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
    ends = parse_access_expiry("2026-10-10", UserRole.AUDITOR, now=now)
    assert ends.isoformat().startswith("2026-10-10T23:59:59")
    with pytest.raises(PeopleError):
        parse_access_expiry("2026-09-01", UserRole.AUDITOR, now=now)
    assert parse_access_expiry(None, UserRole.MEMBER, now=now) is None


def test_non_admins_can_list_people_but_not_change_them(world):
    admin = world["client"](world["admin_email"])
    email = f"staff_{uuid4()}@example.test"
    admin.post("/org/users", json={"email": email, "role": "member", "password": "Str0ng!pass"})
    staff = world["client"](email, "Str0ng!pass")
    listing = staff.get("/org/users")
    assert listing.status_code == 200  # assignee pickers
    assert {"value", "label", "description"} <= set(listing.get_json()["roles"][0])
    assert staff.post("/org/users", json={"email": f"x_{uuid4()}@example.test"}).status_code == 403
    assert staff.get("/core/people", headers={"Accept": "text/html"}).status_code == 302


def test_last_active_admin_cannot_be_demoted_or_deactivated():
    """Through the API the self-edit rule usually fires first, so test the rule directly."""
    from types import SimpleNamespace

    from app.core.security.people import check_change

    def person(role, active=True):
        return SimpleNamespace(id=uuid4(), role=role, is_active=active, access_expires_at=None)

    actor = person(UserRole.ADMIN)
    only_admin = person(UserRole.ADMIN)
    retired_admin = person(UserRole.ADMIN, active=False)
    staff = person(UserRole.MEMBER)
    # actor's own account has lapsed (e.g. access ended), leaving one active admin.
    actor.access_expires_at = datetime.now(UTC) - timedelta(days=1)
    org = [actor, only_admin, retired_admin, staff]

    with pytest.raises(PeopleError, match="only admin"):
        check_change(actor, only_admin, org, role=UserRole.MEMBER, is_active=None)
    with pytest.raises(PeopleError, match="only admin"):
        check_change(actor, only_admin, org, role=None, is_active=False)
    check_change(actor, staff, org, role=UserRole.SALES, is_active=None)  # fine
