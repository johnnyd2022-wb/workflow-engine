"""Tests for password-policy, change-password, and session-timeout (Batch 7, rows 4/5).

These auth-account routes had no server-side coverage. change-password guards the current
password, confirmation match, and same-as-current; session-timeout PUT enforces the
min/max bounds; password-policy-check is the public strength helper. Each is exercised
through the real routes.
"""

from uuid import uuid4

import pytest

from app.api.middleware.session_security import (
    MAX_SESSION_TIMEOUT_MINUTES,
    MIN_SESSION_TIMEOUT_MINUTES,
)
from app.core.db.models.organisation import Organisation
from app.core.db.repositories.user_repo import UserRepository
from app.core.security.auth_service import AuthService
from tests.factories import OrganisationFactory

PASSWORD = "TestPass123!"


@pytest.fixture
def account(db):
    """One org+user, an authenticated client, and a helper to mint fresh clients."""
    org = OrganisationFactory()
    db.commit()
    org_id = org.id  # capture before test-client requests detach the instance

    email = f"acct_{uuid4()}@test.com"
    UserRepository(db).create_user(
        org_id=org_id,
        email=email,
        password_hash=AuthService.hash_password(PASSWORD),
        is_active=True,
    )
    db.commit()

    from app.api.app_factory import create_app

    flask_app = create_app()
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False

    def make_client(login_password=None):
        c = flask_app.test_client()
        c.environ_base["wsgi.url_scheme"] = "https"
        c.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
        if login_password is not None:
            r = c.post(
                "/auth/login", json={"email": email, "password": login_password}, content_type="application/json"
            )
            assert r.status_code in (200, 201), f"login failed: {r.data}"
        return c

    with flask_app.app_context():
        yield {"email": email, "client": make_client(PASSWORD), "make_client": make_client}

    db.rollback()
    db.query(Organisation).filter(Organisation.id == org_id).delete(synchronize_session=False)
    db.commit()


# --- password policy (public helper) --------------------------------------------------


def test_password_policy_flags_weak_password(account):
    resp = account["make_client"]().post("/auth/password-policy-check", json={"password": "weak"})
    assert resp.status_code == 200, resp.data
    body = resp.get_json()
    assert body["is_valid"] is False
    assert body["warnings"]  # non-empty


def test_password_policy_accepts_strong_password(account):
    resp = account["make_client"]().post("/auth/password-policy-check", json={"password": "Str0ng-Pass!"})
    assert resp.status_code == 200, resp.data
    body = resp.get_json()
    assert body["is_valid"] is True
    assert body["warnings"] == []


# --- change password ------------------------------------------------------------------


def test_change_password_success_new_password_can_log_in(account):
    new_password = "NewStr0ng-Pass!9"
    resp = account["client"].post(
        "/auth/change-password",
        json={"current_password": PASSWORD, "new_password": new_password, "new_password_confirm": new_password},
    )
    assert resp.status_code == 200, resp.data
    # The change actually took effect: a fresh login with the new password succeeds...
    account["make_client"](login_password=new_password)
    # ...and the old password no longer works.
    stale = account["make_client"]()
    old = stale.post("/auth/login", json={"email": account["email"], "password": PASSWORD})
    assert old.status_code not in (200, 201)


def test_change_password_wrong_current_is_rejected(account):
    resp = account["client"].post(
        "/auth/change-password",
        json={
            "current_password": "WrongCurrent!1",
            "new_password": "NewStr0ng-Pass!9",
            "new_password_confirm": "NewStr0ng-Pass!9",
        },
    )
    assert resp.status_code == 400


def test_change_password_confirm_mismatch_is_rejected(account):
    resp = account["client"].post(
        "/auth/change-password",
        json={"current_password": PASSWORD, "new_password": "NewStr0ng-Pass!9", "new_password_confirm": "Different!9"},
    )
    assert resp.status_code == 400


def test_change_password_same_as_current_is_rejected(account):
    resp = account["client"].post(
        "/auth/change-password",
        json={"current_password": PASSWORD, "new_password": PASSWORD, "new_password_confirm": PASSWORD},
    )
    assert resp.status_code == 400


# --- session timeout ------------------------------------------------------------------


def test_get_session_timeout_returns_bounds(account):
    resp = account["client"].get("/auth/session-timeout")
    assert resp.status_code == 200, resp.data
    body = resp.get_json()
    assert body["min_session_timeout_minutes"] == MIN_SESSION_TIMEOUT_MINUTES
    assert body["max_session_timeout_minutes"] == MAX_SESSION_TIMEOUT_MINUTES


def test_put_session_timeout_valid_value_is_accepted(account):
    resp = account["client"].put("/auth/session-timeout", json={"session_timeout_minutes": 90})
    assert resp.status_code == 200, resp.data
    assert resp.get_json()["session_timeout_minutes"] == 90


def test_put_session_timeout_below_minimum_is_rejected(account):
    resp = account["client"].put(
        "/auth/session-timeout", json={"session_timeout_minutes": MIN_SESSION_TIMEOUT_MINUTES - 1}
    )
    assert resp.status_code == 400


def test_put_session_timeout_missing_value_is_rejected(account):
    resp = account["client"].put("/auth/session-timeout", json={})
    assert resp.status_code == 400
