"""Gap-fill coverage for auth spec ACs not exercised by the existing suite.

`.agents/specs/auth.md` has 21 ACs. `test_auth_password_session.py` covers change-password,
session-timeout, and password-policy-check. `test_2fa_totp_optimized.py` and
`test_login_2fa_flow.py` cover most of the rest of 2FA/login end to end, but both are
entirely `pytest.mark.live_server` (they drive a real server over HTTPS with `requests`)
and skip whenever no dev server is listening -- which is most of the time in CI/local runs
without `uv run workflow start`. Every route these tests exercise is plain Flask view logic
with no outbound network calls (TOTP is local pyotp math, no external IdP), so they can be
exercised in-process via the Flask test client, the same pattern
`test_auth_password_session.py` already uses. No live server is required for any test here.

Covers:
- AC3:  signup returns the identical generic 400 for duplicate org name vs duplicate email
- AC4:  login returns the identical generic 401 for nonexistent user, wrong password, and a
        locked account
- AC8:  trusted-device cookie + fingerprint mismatch falls through to requiring 2FA (the
        unhappy paths; the matching happy path is also included for contrast)
- AC9:  logout does NOT clear the trusted_device_token cookie
- AC13: a backup code used for 2FA verification cannot also set a trusted-device cookie,
        even when remember_device=true is passed (contrasted against TOTP, which can)
- AC17: /auth/2fa/cancel clears the whole session and reports had_pending correctly whether
        or not a pending 2FA challenge existed
- AC20: change-password invalidates trusted devices but leaves the requester's own session
        valid (not logged out)
"""

from uuid import uuid4

import pyotp
import pytest

from app.core.db.models.audit_log import AuditLog
from app.core.db.models.organisation import Organisation
from app.core.db.models.trusted_device import TrustedDevice
from app.core.db.models.user import User
from app.core.db.repositories.trusted_device_repo import TrustedDeviceRepository
from app.core.db.repositories.user_repo import UserRepository
from app.core.security.auth_service import AuthService
from tests.factories import OrganisationFactory

PASSWORD = "TestPass123!"
GENERIC_LOGIN_ERROR = "Cannot complete request. Check credentials or contact support."
GENERIC_SIGNUP_ERROR = "Cannot complete request. Check credentials or contact support."


def _two_totp_tokens(secret: str) -> tuple[str, str]:
    """Two distinct valid TOTP tokens without waiting out a 30s window (existing pattern)."""
    totp = pyotp.TOTP(secret)
    import time

    now = int(time.time())
    token1 = totp.at(now)
    token2 = totp.at(now + 30)
    if token1 == token2:
        token2 = totp.at(now + 60)
    return token1, token2


@pytest.fixture
def app_and_org(db):
    """A fresh Flask app + one org, torn down after the test."""
    org = OrganisationFactory()
    db.commit()
    org_id = org.id

    from app.api.app_factory import create_app

    flask_app = create_app()
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False

    yield flask_app, org_id

    db.rollback()
    user_ids = [u.id for u in db.query(User.id).filter(User.org_id == org_id).all()]
    if user_ids:
        db.query(TrustedDevice).filter(TrustedDevice.user_id.in_(user_ids)).delete(synchronize_session=False)
    db.query(AuditLog).filter(AuditLog.org_id == org_id).delete(synchronize_session=False)
    db.query(User).filter(User.org_id == org_id).delete(synchronize_session=False)
    db.query(Organisation).filter(Organisation.id == org_id).delete(synchronize_session=False)
    db.commit()


def _client(flask_app):
    c = flask_app.test_client()
    c.environ_base["wsgi.url_scheme"] = "https"
    c.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
    return c


def _create_user(db, org_id, email=None, password=PASSWORD):
    email = email or f"user_{uuid4()}@test.com"
    UserRepository(db).create_user(
        org_id=org_id,
        email=email,
        password_hash=AuthService.hash_password(password),
        is_active=True,
    )
    db.commit()
    return email


# --- AC3: signup enumeration prevention -------------------------------------------------


def test_signup_duplicate_org_name_and_duplicate_email_return_identical_generic_error(app_and_org, db):
    flask_app, org_id = app_and_org
    org = db.query(Organisation).filter(Organisation.id == org_id).one()
    org_name = org.name
    existing_email = _create_user(db, org_id)

    c1 = _client(flask_app)
    dup_org_resp = c1.post(
        "/auth/signup",
        json={
            "org_name": org_name,  # duplicate org name
            "email": f"new_{uuid4()}@test.com",
            "password": PASSWORD,
            "password_confirm": PASSWORD,
        },
    )

    c2 = _client(flask_app)
    dup_email_resp = c2.post(
        "/auth/signup",
        json={
            "org_name": f"NewOrg_{uuid4()}",
            "email": existing_email,  # duplicate email
            "password": PASSWORD,
            "password_confirm": PASSWORD,
        },
    )

    assert dup_org_resp.status_code == 400, dup_org_resp.data
    assert dup_email_resp.status_code == 400, dup_email_resp.data
    assert dup_org_resp.get_json()["error"] == GENERIC_SIGNUP_ERROR
    assert dup_email_resp.get_json()["error"] == GENERIC_SIGNUP_ERROR
    # Not just similar -- byte-identical, so no enumeration signal leaks via message content.
    assert dup_org_resp.get_json() == dup_email_resp.get_json()


# --- AC4: login enumeration prevention ---------------------------------------------------


def test_login_generic_401_for_nonexistent_wrong_password_and_locked_account(app_and_org, db):
    flask_app, org_id = app_and_org
    email = _create_user(db, org_id)

    # 1. Nonexistent user.
    nonexistent_resp = _client(flask_app).post(
        "/auth/login", json={"email": f"ghost_{uuid4()}@test.com", "password": "whatever123!"}
    )

    # 2. Wrong password for a real user.
    wrong_password_resp = _client(flask_app).post("/auth/login", json={"email": email, "password": "WrongPass!1"})

    # 3. Locked account -- lock directly via the repo (avoids tripping the login rate
    #    limiter with 5 real failed attempts, which is AC5's mechanism, not this AC).
    user = UserRepository(db).get_user_by_email(email, org_id=org_id)
    UserRepository(db).lock_account(user.id, lockout_duration_minutes=5)
    db.commit()
    locked_resp = _client(flask_app).post("/auth/login", json={"email": email, "password": PASSWORD})

    for resp in (nonexistent_resp, wrong_password_resp, locked_resp):
        assert resp.status_code == 401, resp.data
        assert resp.get_json()["error"] == GENERIC_LOGIN_ERROR

    # Byte-identical bodies across all three failure modes -- no enumeration via status
    # code or message content.
    assert nonexistent_resp.get_json() == wrong_password_resp.get_json() == locked_resp.get_json()


# --- AC8: trusted-device cookie + fingerprint verification -------------------------------


def _enable_2fa(client) -> tuple[str, list[str]]:
    enroll_resp = client.post("/auth/2fa/enroll")
    assert enroll_resp.status_code == 200, enroll_resp.data
    secret = enroll_resp.get_json()["secret"]
    token1, token2 = _two_totp_tokens(secret)
    enable_resp = client.post("/auth/2fa/enable", json={"token1": token1, "token2": token2})
    assert enable_resp.status_code == 200, enable_resp.data
    return secret, enable_resp.get_json()["backup_codes"]


FINGERPRINT_DATA = {
    "userAgent": "pytest-agent",
    "language": "en-US",
    "platform": "pytest",
    "screenResolution": "1920x1080",
    "timezone": "UTC",
}
OTHER_FINGERPRINT_DATA = {
    "userAgent": "some-other-browser",
    "language": "fr-FR",
    "platform": "other-platform",
    "screenResolution": "800x600",
    "timezone": "Pacific/Auckland",
}


def test_trusted_device_matching_cookie_and_fingerprint_skips_2fa(app_and_org, db):
    flask_app, org_id = app_and_org
    email = _create_user(db, org_id)
    client = _client(flask_app)
    login = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200
    _enable_2fa(client)

    login2 = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert login2.status_code == 200
    assert login2.get_json()["requires_2fa"] is True

    user = UserRepository(db).get_user_by_email(email, org_id=org_id)
    verify_resp = client.post(
        "/auth/verify-2fa",
        json={
            "token": pyotp.TOTP(user.totp_secret).now(),
            "remember_device": True,
            "device_fingerprint": FINGERPRINT_DATA,
        },
    )
    assert verify_resp.status_code == 200, verify_resp.data
    device_token = client.get_cookie("trusted_device_token")
    assert device_token is not None, "expected a trusted_device_token cookie after remember_device=True"

    # Fresh client carrying only the trusted-device cookie, matching fingerprint: login
    # should skip 2FA entirely.
    fresh = _client(flask_app)
    fresh.set_cookie("trusted_device_token", device_token.value, domain="localhost")
    happy_login = fresh.post(
        "/auth/login",
        json={"email": email, "password": PASSWORD, "device_fingerprint": FINGERPRINT_DATA},
    )
    assert happy_login.status_code == 200, happy_login.data
    assert "requires_2fa" not in happy_login.get_json()
    assert happy_login.get_json()["message"] == "Login successful"


def test_trusted_device_fingerprint_mismatch_falls_through_to_2fa(app_and_org, db):
    """AC8 unhappy path: a valid cookie but a DIFFERENT fingerprint must not skip 2FA."""
    flask_app, org_id = app_and_org
    email = _create_user(db, org_id)
    client = _client(flask_app)
    client.post("/auth/login", json={"email": email, "password": PASSWORD})
    _enable_2fa(client)

    client.post("/auth/login", json={"email": email, "password": PASSWORD})
    user = UserRepository(db).get_user_by_email(email, org_id=org_id)
    verify_resp = client.post(
        "/auth/verify-2fa",
        json={
            "token": pyotp.TOTP(user.totp_secret).now(),
            "remember_device": True,
            "device_fingerprint": FINGERPRINT_DATA,
        },
    )
    assert verify_resp.status_code == 200, verify_resp.data
    device_token = client.get_cookie("trusted_device_token")
    assert device_token is not None

    fresh = _client(flask_app)
    fresh.set_cookie("trusted_device_token", device_token.value, domain="localhost")
    mismatched_login = fresh.post(
        "/auth/login",
        json={"email": email, "password": PASSWORD, "device_fingerprint": OTHER_FINGERPRINT_DATA},
    )
    assert mismatched_login.status_code == 200, mismatched_login.data
    assert mismatched_login.get_json()["requires_2fa"] is True, (
        "a fingerprint mismatch must fall through to the 2FA challenge, not skip it"
    )


def test_trusted_device_unknown_token_falls_through_to_2fa(app_and_org, db):
    """AC8 unhappy path: a cookie that matches no stored device also falls through."""
    flask_app, org_id = app_and_org
    email = _create_user(db, org_id)
    client = _client(flask_app)
    client.post("/auth/login", json={"email": email, "password": PASSWORD})
    _enable_2fa(client)

    fresh = _client(flask_app)
    fresh.set_cookie("trusted_device_token", "not-a-real-token", domain="localhost")
    resp = fresh.post(
        "/auth/login",
        json={"email": email, "password": PASSWORD, "device_fingerprint": FINGERPRINT_DATA},
    )
    assert resp.status_code == 200, resp.data
    assert resp.get_json()["requires_2fa"] is True


# --- AC9: logout leaves the trusted-device cookie intact ---------------------------------


def test_logout_does_not_clear_trusted_device_cookie(app_and_org, db):
    flask_app, org_id = app_and_org
    email = _create_user(db, org_id)
    client = _client(flask_app)
    client.post("/auth/login", json={"email": email, "password": PASSWORD})

    client.set_cookie("trusted_device_token", "some-persisted-token", domain="localhost")
    assert client.get_cookie("trusted_device_token") is not None

    logout_resp = client.post("/auth/logout")
    assert logout_resp.status_code == 200

    # No Set-Cookie in the logout response should touch trusted_device_token at all.
    set_cookie_headers = logout_resp.headers.getlist("Set-Cookie")
    assert not any("trusted_device_token" in h for h in set_cookie_headers), set_cookie_headers

    # And the client's cookie jar still carries it after logout -- proves it survives.
    surviving_cookie = client.get_cookie("trusted_device_token")
    assert surviving_cookie is not None
    assert surviving_cookie.value == "some-persisted-token"

    # Meanwhile the actual auth session IS gone.
    me_resp = client.get("/auth/me")
    assert me_resp.get_json()["user"] is None


# --- AC13: backup codes cannot mint a trusted-device cookie -------------------------------


def test_verify_2fa_totp_with_remember_device_sets_cookie_control(app_and_org, db):
    """Control case for AC13's contrast: TOTP + remember_device DOES set the cookie."""
    flask_app, org_id = app_and_org
    email = _create_user(db, org_id)
    client = _client(flask_app)
    client.post("/auth/login", json={"email": email, "password": PASSWORD})
    _enable_2fa(client)

    client.post("/auth/login", json={"email": email, "password": PASSWORD})
    user = UserRepository(db).get_user_by_email(email, org_id=org_id)
    verify_resp = client.post(
        "/auth/verify-2fa",
        json={
            "token": pyotp.TOTP(user.totp_secret).now(),
            "remember_device": True,
            "device_fingerprint": FINGERPRINT_DATA,
        },
    )
    assert verify_resp.status_code == 200
    assert client.get_cookie("trusted_device_token") is not None


def test_verify_2fa_backup_code_ignores_remember_device_flag(app_and_org, db):
    flask_app, org_id = app_and_org
    email = _create_user(db, org_id)
    client = _client(flask_app)
    client.post("/auth/login", json={"email": email, "password": PASSWORD})
    _secret, backup_codes = _enable_2fa(client)

    client.post("/auth/login", json={"email": email, "password": PASSWORD})
    verify_resp = client.post(
        "/auth/verify-2fa",
        json={
            "token": backup_codes[0],
            "remember_device": True,
            "device_fingerprint": FINGERPRINT_DATA,
        },
    )
    assert verify_resp.status_code == 200, verify_resp.data
    assert verify_resp.get_json()["message"] == "Login successful"

    set_cookie_headers = verify_resp.headers.getlist("Set-Cookie")
    assert not any("trusted_device_token" in h for h in set_cookie_headers), (
        f"backup-code verification must never set a trusted-device cookie, even with "
        f"remember_device=true; got Set-Cookie headers: {set_cookie_headers}"
    )
    assert client.get_cookie("trusted_device_token") is None

    user = UserRepository(db).get_user_by_email(email, org_id=org_id)
    assert TrustedDeviceRepository(db).get_trusted_device_by_fingerprint(user.id, "irrelevant") is None
    # No trusted device row exists for this user at all.
    from sqlalchemy import select

    rows = db.execute(select(TrustedDevice).where(TrustedDevice.user_id == user.id)).scalars().all()
    assert rows == []


# --- AC17: /auth/2fa/cancel session clearing + had_pending -------------------------------


def test_cancel_2fa_with_no_pending_state_reports_had_pending_false(app_and_org, db):
    flask_app, _org_id = app_and_org
    client = _client(flask_app)
    resp = client.post("/auth/2fa/cancel")
    assert resp.status_code == 200
    assert resp.get_json() == {"cancelled": True, "had_pending": False}


def test_cancel_2fa_with_pending_state_reports_had_pending_true_and_clears_it(app_and_org, db):
    flask_app, org_id = app_and_org
    email = _create_user(db, org_id)
    client = _client(flask_app)
    client.post("/auth/login", json={"email": email, "password": PASSWORD})
    _enable_2fa(client)

    login_resp = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert login_resp.get_json()["requires_2fa"] is True  # pending_2fa_user_id now set

    cancel_resp = client.post("/auth/2fa/cancel")
    assert cancel_resp.status_code == 200
    assert cancel_resp.get_json() == {"cancelled": True, "had_pending": True}

    # Pending state is really gone: verify-2fa now needs a fresh login.
    verify_resp = client.post("/auth/verify-2fa", json={"token": "123456"})
    assert verify_resp.status_code == 401
    assert "No pending 2FA session" in verify_resp.get_json()["error"]


def test_cancel_2fa_clears_a_full_authenticated_session_not_just_pending_keys(app_and_org, db):
    """AC17: cancel clears the WHOLE session -- proven here on a fully logged-in session
    that never had a pending 2FA challenge at all."""
    flask_app, org_id = app_and_org
    email = _create_user(db, org_id)
    client = _client(flask_app)
    login_resp = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert login_resp.status_code == 200
    assert client.get("/auth/me").get_json()["user"] is not None  # fully logged in, no 2FA

    cancel_resp = client.post("/auth/2fa/cancel")
    assert cancel_resp.status_code == 200
    assert cancel_resp.get_json() == {"cancelled": True, "had_pending": False}

    # The full session -- not just pending-2FA keys -- was cleared.
    assert client.get("/auth/me").get_json()["user"] is None


# --- AC20: change-password invalidates trusted devices, keeps requester logged in ---------


def test_change_password_invalidates_trusted_devices_but_keeps_own_session(app_and_org, db):
    flask_app, org_id = app_and_org
    email = _create_user(db, org_id)
    user = UserRepository(db).get_user_by_email(email, org_id=org_id)

    trusted_repo = TrustedDeviceRepository(db)
    raw_token = trusted_repo.generate_device_token()
    trusted_repo.create_trusted_device(
        user.id,
        trusted_repo.hash_device_token(raw_token),
        "some-fingerprint",
        TrustedDevice.get_expiration_date(),
    )
    db.commit()
    assert trusted_repo.get_trusted_device_by_token(raw_token) is not None

    client = _client(flask_app)
    login_resp = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert login_resp.status_code == 200

    new_password = "NewStr0ng-Pass!9"
    change_resp = client.post(
        "/auth/change-password",
        json={"current_password": PASSWORD, "new_password": new_password, "new_password_confirm": new_password},
    )
    assert change_resp.status_code == 200, change_resp.data

    # Requester's own session is still valid -- not logged out by the password change.
    me_resp = client.get("/auth/me")
    assert me_resp.status_code == 200
    assert me_resp.get_json()["user"] is not None
    assert me_resp.get_json()["user"]["email"] == email

    # But the trusted device is gone -- forcing 2FA/re-trust elsewhere.
    assert trusted_repo.get_trusted_device_by_token(raw_token) is None


# --- security-audit F3: disabling 2FA invalidates trusted devices too --------------------
#
# Found during the auth security audit: disable_2fa() deleted backup codes but left
# trusted-device rows untouched. Those tokens exist purely to bypass 2FA and are tied to
# the enrollment that minted them; if a user disables 2FA and later re-enrolls (new TOTP
# secret, new backup codes), a device_token+fingerprint pair from the *old* enrollment
# would still satisfy login()'s trusted-device check and skip 2FA under the new
# enrollment entirely -- silently defeating the point of re-enrolling. Fixed by deleting
# all trusted devices in the same transaction as the backup-code cleanup, mirroring what
# change-password already does (test above).


def test_disable_2fa_invalidates_trusted_devices(app_and_org, db):
    flask_app, org_id = app_and_org
    email = _create_user(db, org_id)
    client = _client(flask_app)
    client.post("/auth/login", json={"email": email, "password": PASSWORD})
    _enable_2fa(client)

    client.post("/auth/login", json={"email": email, "password": PASSWORD})
    user = UserRepository(db).get_user_by_email(email, org_id=org_id)
    verify_resp = client.post(
        "/auth/verify-2fa",
        json={
            "token": pyotp.TOTP(user.totp_secret).now(),
            "remember_device": True,
            "device_fingerprint": FINGERPRINT_DATA,
        },
    )
    assert verify_resp.status_code == 200, verify_resp.data
    device_token = client.get_cookie("trusted_device_token")
    assert device_token is not None, "expected a trusted_device_token cookie after remember_device=True"
    assert TrustedDeviceRepository(db).get_trusted_device_by_token(device_token.value) is not None

    disable_resp = client.post("/auth/2fa/disable")
    assert disable_resp.status_code == 200, disable_resp.data
    assert disable_resp.get_json()["disabled"] is True

    # The trusted device minted under the now-disabled enrollment must be gone.
    assert TrustedDeviceRepository(db).get_trusted_device_by_token(device_token.value) is None

    # Re-enroll from scratch: a fresh client presenting the OLD (now-deleted) device
    # token + matching fingerprint must NOT skip 2FA under the new enrollment.
    _enable_2fa(client)
    fresh = _client(flask_app)
    fresh.set_cookie("trusted_device_token", device_token.value, domain="localhost")
    login_resp = fresh.post(
        "/auth/login",
        json={"email": email, "password": PASSWORD, "device_fingerprint": FINGERPRINT_DATA},
    )
    assert login_resp.status_code == 200, login_resp.data
    assert login_resp.get_json()["requires_2fa"] is True, (
        "a trusted-device token from a disabled/re-enrolled 2FA setup must not skip 2FA"
    )
