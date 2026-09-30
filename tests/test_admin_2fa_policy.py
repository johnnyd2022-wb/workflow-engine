"""Plan item 0.2: owners and admins must use two-factor authentication.

Also covers F6 in .agents/reports/auth/security-audit.md: /auth/verify-2fa had no cap on
wrong codes, so anyone holding a password could guess codes without limit.
"""

from uuid import uuid4

import pyotp
import pytest

from app.core.db.models.organisation import Organisation
from app.core.db.models.user import User, UserRole
from app.core.db.repositories.user_repo import UserRepository
from app.core.security.auth_service import AuthService
from app.core.security.two_factor_policy import (
    ENROLLMENT_PAGE,
    ENROLLMENT_REQUIRED_CODE,
    resolve_require_admin_2fa,
)
from tests.factories import DEFAULT_TEST_PASSWORD, OrganisationFactory

PASSWORD = DEFAULT_TEST_PASSWORD


@pytest.fixture
def org_world(db):
    """One org with an admin and a member (neither enrolled), and the policy switched on."""
    org = OrganisationFactory()
    db.commit()
    org_id = org.id
    repo = UserRepository(db)
    users = {}
    for key, role in (("admin", UserRole.ADMIN), ("member", UserRole.MEMBER)):
        email = f"{key}_{uuid4()}@test.com"
        user = repo.create_user(
            org_id=org_id, email=email, password_hash=AuthService.hash_password(PASSWORD), role=role
        )
        db.commit()
        users[key] = {"email": email, "id": user.id}

    from app.api.app_factory import create_app

    flask_app = create_app()
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False
    # local.ini switches the policy off for scripted logins; these tests are about it being on.
    flask_app.config["REQUIRE_ADMIN_2FA"] = True

    def make_client():
        c = flask_app.test_client()
        c.environ_base["wsgi.url_scheme"] = "https"
        c.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
        return c

    def login(key):
        c = make_client()
        resp = c.post("/auth/login", json={"email": users[key]["email"], "password": PASSWORD})
        return c, resp

    with flask_app.app_context():
        yield {"app": flask_app, "users": users, "login": login, "org_id": org_id}

    db.rollback()
    db.query(Organisation).filter(Organisation.id == org_id).delete(synchronize_session=False)
    db.commit()


def _enable_2fa(db, user_id) -> str:
    secret = pyotp.random_base32()
    user = db.get(User, user_id)
    user.totp_secret = secret
    user.two_factor_enabled = True
    db.commit()
    return secret


def test_admin_without_2fa_is_told_to_enrol_at_login(org_world):
    _, resp = org_world["login"]("admin")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["requires_2fa_enrollment"] is True
    assert body["action"] == ENROLLMENT_PAGE


def test_admin_without_2fa_is_blocked_everywhere_except_enrolment(org_world):
    client, _ = org_world["login"]("admin")

    api = client.get("/api/core/processes")
    assert api.status_code == 403
    assert api.get_json()["code"] == ENROLLMENT_REQUIRED_CODE

    page = client.get("/core/dashboard", headers={"Accept": "text/html"})
    assert page.status_code == 302
    assert page.headers["Location"].endswith(ENROLLMENT_PAGE)

    htmx = client.get("/core/dashboard", headers={"HX-Request": "true"})
    assert htmx.headers.get("HX-Redirect") == ENROLLMENT_PAGE

    # The enrolment flow and what the Settings page reads stay reachable.
    me = client.get("/auth/me").get_json()["user"]
    assert me["two_factor_required"] is True
    assert me["two_factor_enrollment_required"] is True
    assert client.get("/core/settings").status_code == 200
    assert client.post("/auth/2fa/enroll").status_code == 200


def test_member_is_not_affected(org_world):
    client, resp = org_world["login"]("member")
    assert "requires_2fa_enrollment" not in resp.get_json()
    assert client.get("/api/core/processes").status_code == 200
    me = client.get("/auth/me").get_json()["user"]
    assert me["two_factor_required"] is False


def test_existing_admin_session_is_blocked_without_a_new_login(org_world, db):
    """The check reads the live user row, so promoting someone mid-session applies at once."""
    client, _ = org_world["login"]("member")
    assert client.get("/api/core/processes").status_code == 200

    db.get(User, org_world["users"]["member"]["id"]).role = UserRole.ADMIN
    db.commit()

    assert client.get("/api/core/processes").status_code == 403


def test_enrolled_admin_passes_and_cannot_disable_2fa(org_world, db):
    secret = _enable_2fa(db, org_world["users"]["admin"]["id"])
    client, resp = org_world["login"]("admin")
    assert resp.get_json() == {"requires_2fa": True}
    verified = client.post("/auth/verify-2fa", json={"token": pyotp.TOTP(secret).now()})
    assert verified.status_code == 200

    assert client.get("/api/core/processes").status_code == 200
    disable = client.post("/auth/2fa/disable", json={"password": PASSWORD})
    assert disable.status_code == 403
    assert disable.get_json()["code"] == "two_factor_required"


def test_policy_off_leaves_admins_alone(org_world):
    org_world["app"].config["REQUIRE_ADMIN_2FA"] = False
    client, resp = org_world["login"]("admin")
    assert "requires_2fa_enrollment" not in resp.get_json()
    assert client.get("/api/core/processes").status_code == 200


@pytest.mark.parametrize(
    ("environment", "configured", "expected"),
    [
        ("production", False, True),  # can't be switched off in production
        ("prod", False, True),
        ("", False, True),  # unset or unknown environments fail closed
        ("staging", False, True),
        ("local", False, False),
        ("test", False, False),
        ("local", True, True),
    ],
)
def test_policy_can_only_be_switched_off_in_local_and_test(environment, configured, expected):
    assert resolve_require_admin_2fa(environment, configured) is expected


def test_wrong_2fa_codes_end_the_pending_session_after_five(org_world, db):
    """F6: five wrong codes and the password must be entered again."""
    secret = _enable_2fa(db, org_world["users"]["admin"]["id"])
    client, _ = org_world["login"]("admin")
    right = pyotp.TOTP(secret).now()
    wrong = "000000" if right != "000000" else "111111"

    for _ in range(4):
        resp = client.post("/auth/verify-2fa", json={"token": wrong})
        assert resp.status_code == 401
        assert resp.get_json()["error"] == "Invalid 2FA token or backup code"

    fifth = client.post("/auth/verify-2fa", json={"token": wrong})
    assert fifth.status_code == 401
    assert fifth.get_json()["error"] == "Too many incorrect codes. Please sign in again."

    # Even the right code is refused now: the pending session is gone.
    after = client.post("/auth/verify-2fa", json={"token": right})
    assert after.status_code == 401
    assert "login again" in after.get_json()["error"].lower()


def test_verify_2fa_rate_limit_is_keyed_on_the_account_not_the_ip(org_world):
    """The account key bounds total guesses even when the attacker re-enters the password
    (which resets the login failure counter) or rotates IPs."""
    from flask import session

    from app.api.routes.auth_routes import _pending_2fa_rate_limit_key

    user_id = str(org_world["users"]["admin"]["id"])
    with org_world["app"].test_request_context("/auth/verify-2fa", environ_base={"REMOTE_ADDR": "203.0.113.9"}):
        session["pending_2fa_user_id"] = user_id
        assert _pending_2fa_rate_limit_key() == f"2fa:{user_id}"
    with org_world["app"].test_request_context("/auth/verify-2fa", environ_base={"REMOTE_ADDR": "198.51.100.7"}):
        session["pending_2fa_user_id"] = user_id
        assert _pending_2fa_rate_limit_key() == f"2fa:{user_id}"


def test_verify_2fa_route_carries_a_limit_keyed_on_the_account():
    """F6: the two tests above prove the failure counter and the key function, but neither
    notices if the `@limiter.limit` decorator itself is dropped from the view -- the key
    function would still exist and the counter would still cap a single pending session,
    while the account-wide 5/minute;20/hour bound (the part that survives a fresh login)
    silently vanished. This asserts the route really is limited, and by the account key.
    It does not assert the limit *string*: that is relaxed to 1000/minute under CI."""
    from app.api.routes import auth_routes

    manager = auth_routes.limiter.limit_manager
    # `_decorated_limits` is flask-limiter's private registry (3.5.0): the public
    # `decorated_limits(name)` needs the internal "<module>.<func>.<func>" key, so the
    # name is found by suffix. If a flask-limiter upgrade breaks this lookup, fix the
    # lookup -- do not delete the test.
    registered = [name for name in manager._decorated_limits if name.endswith(".verify_two_factor")]
    assert len(registered) == 1, f"verify_two_factor has no @limiter.limit registered: {registered}"

    limits = manager.decorated_limits(registered[0])
    assert limits
    assert {limit.key_func for limit in limits} == {auth_routes._pending_2fa_rate_limit_key}
