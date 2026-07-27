"""Security-audit regression tests for /auth/login and AuthService.authenticate().

Covers a timing-based user/org enumeration side-channel found during the auth security
audit (.agents/reports/auth/security-audit.md, F1): a nonexistent email, a real email
paired with the wrong org_id, and a locked account all used to short-circuit *before* any
bcrypt comparison, while a real account with a wrong password paid bcrypt's cost handling
the compare. The response body/status code were identical across all cases (as AC4
requires), but the wall-clock cost was not — letting an attacker distinguish the cases by
latency alone. AuthService.authenticate() now always performs one bcrypt comparison
(real hash or a fixed dummy hash), and the login route now calls authenticate() before
branching on lockout state, so every code path pays the same bcrypt cost exactly once.

Also covers a session-rotation drift found in the same audit (F2): change-password had
its own hand-rolled session.clear() + key-by-key restore instead of calling the shared
rotate_session() helper, silently losing session.permanent=True (a plain session.clear()
wipes the `_permanent` key along with everything else). change-password now calls
rotate_session() like every other auth transition, so the persistent-session cookie
survives a password change.
"""

from unittest.mock import patch
from uuid import uuid4

import pytest

from app.core.db.models.organisation import Organisation
from app.core.db.repositories.user_repo import UserRepository
from app.core.security.auth_service import AuthService
from tests.factories import DEFAULT_TEST_PASSWORD, OrganisationFactory

PASSWORD = DEFAULT_TEST_PASSWORD


@pytest.fixture
def account(db):
    """One org+user, an authenticated client, and a helper to mint fresh clients.

    Mirrors the `account` fixture in tests/test_auth_password_session.py.
    """
    org = OrganisationFactory()
    db.commit()
    org_id = org.id

    email = f"acct_{uuid4()}@test.com"
    user = UserRepository(db).create_user(
        org_id=org_id,
        email=email,
        password_hash=AuthService.hash_password(PASSWORD),
        is_active=True,
    )
    db.commit()
    user_id = user.id

    from app.api.app_factory import create_app

    flask_app = create_app()
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False

    def make_client():
        c = flask_app.test_client()
        c.environ_base["wsgi.url_scheme"] = "https"
        c.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
        return c

    with flask_app.app_context():
        yield {"email": email, "org_id": org_id, "user_id": user_id, "make_client": make_client}

    db.rollback()
    db.query(Organisation).filter(Organisation.id == org_id).delete(synchronize_session=False)
    db.commit()


GENERIC_LOGIN_ERROR = "Cannot complete request. Check credentials or contact support."


# --- timing/enumeration parity in AuthService.authenticate() --------------------------


def test_authenticate_invokes_bcrypt_for_nonexistent_email(db):
    """A nonexistent email must still pay one bcrypt comparison (dummy hash), not an
    instant return, so it cannot be timing-distinguished from a real wrong-password check.
    """
    auth_service = AuthService(db)
    with patch("app.core.security.auth_service.bcrypt.checkpw", wraps=__import__("bcrypt").checkpw) as spy:
        result = auth_service.authenticate(f"nobody-{uuid4()}@test.com", "whatever-password")
    assert result is None
    assert spy.call_count == 1


def test_authenticate_invokes_bcrypt_for_wrong_org_id(account, db):
    """A real email paired with the wrong org_id must cost the same as a wrong password:
    one bcrypt comparison, not an instant "not found" return. Without this, supplying a
    guessed org_id is a timing oracle for "does this email belong to org X".
    """
    auth_service = AuthService(db)
    with patch("app.core.security.auth_service.bcrypt.checkpw", wraps=__import__("bcrypt").checkpw) as spy:
        result = auth_service.authenticate(account["email"], PASSWORD, org_id=uuid4())
    assert result is None
    assert spy.call_count == 1


def test_authenticate_invokes_bcrypt_exactly_once_for_wrong_password(account, db):
    """Baseline: the real-account/wrong-password path also pays exactly one bcrypt call —
    proving the nonexistent-email and wrong-org-id cases above are now at parity with it,
    not merely "also nonzero".
    """
    auth_service = AuthService(db)
    with patch("app.core.security.auth_service.bcrypt.checkpw", wraps=__import__("bcrypt").checkpw) as spy:
        result = auth_service.authenticate(account["email"], "definitely-wrong-password")
    assert result is None
    assert spy.call_count == 1


def test_authenticate_succeeds_with_correct_password(account, db):
    """Sanity check: the timing-parity change doesn't break real authentication."""
    auth_service = AuthService(db)
    user = auth_service.authenticate(account["email"], PASSWORD)
    assert user is not None
    assert user.email == account["email"]


def test_authenticate_invokes_bcrypt_for_inactive_user(account, db):
    """An inactive (deactivated) account must pay the same dummy-hash bcrypt cost as a
    wrong password, not an instant `not user.is_active` return -- the same timing oracle
    that applied to nonexistent emails and wrong org_ids applies here too.
    """
    UserRepository(db).update_user(user_id=account["user_id"], org_id=account["org_id"], is_active=False)
    db.commit()

    auth_service = AuthService(db)
    with patch("app.core.security.auth_service.bcrypt.checkpw", wraps=__import__("bcrypt").checkpw) as spy:
        result = auth_service.authenticate(account["email"], PASSWORD)
    assert result is None
    assert spy.call_count == 1


# --- /auth/login timing parity at the route level (catches reverting the reordering,
# not just the response body) ------------------------------------------------------------


def test_login_locked_account_still_invokes_bcrypt(account, db):
    """F1 regression, route level: a locked account must still cost one bcrypt comparison.

    The response-identity tests above (and test_auth_gap_coverage's
    test_login_generic_401_for_nonexistent_wrong_password_and_locked_account) prove the
    *body* is identical across nonexistent/wrong-password/locked-account, but a body-only
    assertion can't catch a timing regression: if `login()`'s call to `authenticate()` were
    moved back to *after* the lockout early-return (reverting the route-level half of F1
    while leaving AuthService's dummy-hash fix untouched), the locked-account path would
    short-circuit before ever calling `authenticate()` -- zero bcrypt calls instead of one --
    and this test would catch that even though the JSON response wouldn't change at all.
    """
    UserRepository(db).lock_account(account["user_id"], lockout_duration_minutes=5)
    db.commit()

    client = account["make_client"]()
    with patch("app.core.security.auth_service.bcrypt.checkpw", wraps=__import__("bcrypt").checkpw) as spy:
        resp = client.post("/auth/login", json={"email": account["email"], "password": PASSWORD})

    assert resp.status_code == 401, resp.data
    assert spy.call_count == 1


# --- /auth/login response parity (status + body) ---------------------------------------


def test_login_nonexistent_and_wrong_password_return_identical_response(account):
    """AC4: nonexistent email and wrong password for a real email must return the exact
    same status code and error body — no enumeration via response content.
    """
    client = account["make_client"]()
    nonexistent = client.post("/auth/login", json={"email": f"nobody-{uuid4()}@test.com", "password": "whatever"})
    wrong_password = account["make_client"]().post(
        "/auth/login", json={"email": account["email"], "password": "definitely-wrong"}
    )
    assert nonexistent.status_code == wrong_password.status_code == 401
    assert nonexistent.get_json()["error"] == wrong_password.get_json()["error"] == GENERIC_LOGIN_ERROR


def test_login_ignores_client_supplied_org_id(account):
    """`org_id` in the login body must be ignored outright, not honoured.

    It used to scope the user lookup, which made it an org-membership oracle: pair a known
    email with a guessed org_id and the response told you whether that pairing was real.
    Because `users.email` is globally unique, the parameter could never select a different
    account anyway, so it was removed rather than merely timing-equalised.

    The proof that it is *ignored* (not just uniformly rejected) is that a deliberately
    bogus org_id alongside valid credentials still logs in. If the parameter were still
    being applied as a filter, this would 401.
    """
    resp = account["make_client"]().post(
        "/auth/login",
        json={"email": account["email"], "password": PASSWORD, "org_id": str(uuid4())},
    )
    assert resp.status_code == 200, resp.data

    # And a real org_id is equally inert — same outcome, so the field carries no signal
    # either way and cannot be used to probe membership.
    same = account["make_client"]().post(
        "/auth/login",
        json={"email": account["email"], "password": PASSWORD, "org_id": str(account["org_id"])},
    )
    assert same.status_code == 200, same.data


def test_login_malformed_org_id_is_not_a_500(account):
    """A non-UUID org_id used to reach UUID(org_id) and raise. Now that the field is
    ignored, garbage in it must be inert — not a 400, and certainly not an unhandled 500.
    """
    resp = account["make_client"]().post(
        "/auth/login",
        json={"email": account["email"], "password": PASSWORD, "org_id": "not-a-uuid-at-all"},
    )
    assert resp.status_code == 200, resp.data


# --- change-password session rotation ---------------------------------------------------


def test_change_password_keeps_session_permanent(account):
    """F2 regression: change-password must rotate the session via the shared
    rotate_session() helper (same as login/signup/verify-2fa) so `session.permanent`
    survives. A bare session.clear() + manual key restore drops `_permanent`, silently
    downgrading the persistent 30-day session cookie to a browser-session-only cookie.

    Detected via the Set-Cookie response header: a permanent session carries an explicit
    Expires attribute (tied to PERMANENT_SESSION_LIFETIME); a non-permanent one does not
    (it becomes a browser-session-only cookie with no Expires/Max-Age at all).
    """
    client = account["make_client"]()
    login_resp = client.post("/auth/login", json={"email": account["email"], "password": PASSWORD})
    assert login_resp.status_code == 200, login_resp.data
    login_cookies = login_resp.headers.getlist("Set-Cookie")
    assert any("Expires=" in c for c in login_cookies if "session" in c.lower()), (
        f"expected a persistent (Expires=) session cookie after login, got: {login_cookies}"
    )

    new_password = "NewStr0ng-Pass!9"
    change_resp = client.post(
        "/auth/change-password",
        json={"current_password": PASSWORD, "new_password": new_password, "new_password_confirm": new_password},
    )
    assert change_resp.status_code == 200, change_resp.data
    change_cookies = change_resp.headers.getlist("Set-Cookie")
    assert any("Expires=" in c for c in change_cookies if "session" in c.lower()), (
        "change-password dropped the persistent session cookie (session.permanent lost) — "
        f"Set-Cookie headers were: {change_cookies}"
    )
