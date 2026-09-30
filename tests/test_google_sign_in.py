"""Google sign-in security boundaries, using a real disposable PostgreSQL database."""

import time
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pyotp
import pytest
from authlib.integrations.flask_client import OAuth
from joserfc import jwt
from joserfc.jwk import RSAKey
from sqlalchemy.exc import IntegrityError

from app.core.db.models.audit_log import AuditLog
from app.core.db.models.entity_event import EntityEvent
from app.core.db.models.organisation import Organisation, OrganisationStatus
from app.core.db.models.user import User, UserRole
from app.core.db.models.user_identity import UserIdentity
from app.core.security.auth_service import AuthService
from app.core.security.people import issue_invite
from app.features.google_sign_in import oidc, routes
from app.features.google_sign_in.service import GoogleSignInError, authoritative_email, validate_verified_claims
from tests.factories import DEFAULT_TEST_PASSWORD, OrganisationFactory, UserFactory

CLIENT_ID = "google-test.apps.googleusercontent.com"


def _claims(address, **changes):
    claims = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "iat": int(time.time()),
        "exp": int(time.time()) + 300,
        "sub": uuid4().hex,
        "email": address,
        "email_verified": True,
        "nonce": "test-nonce",
    }
    claims.update(changes)
    return claims


@pytest.fixture
def world(db):
    from app.api.app_factory import create_app

    orgs = [OrganisationFactory(), OrganisationFactory()]
    users = [UserFactory(org_id=o.id, email=f"{uuid4().hex}@gmail.com") for o in orgs]
    db.commit()
    app = create_app()
    # These tests are not about rate limits, but they make more than 10 sign-in starts a minute and the
    # limiter's counters outlive each per-test app: start every test with empty counters. Reset the limiter
    # the routes were decorated with too (test_auth_rate_limit_gating reloads auth_routes, so it can differ).
    for limiter in {id(item): item for item in (app.limiter, routes.limiter)}.values():
        limiter.storage.reset()
    app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        REQUIRE_ADMIN_2FA=False,
        GOOGLE_SIGN_IN_ENABLED=True,
        GOOGLE_CLIENT_ID=CLIENT_ID,
        GOOGLE_REDIRECT_URI="https://test.biz-e.app/auth/google/callback",
    )
    oauth = OAuth(app)
    client = oauth.register(
        name="google",
        client_id=CLIENT_ID,
        client_secret="test-only-secret",
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        access_token_url="https://oauth2.googleapis.com/token",
        client_kwargs={"scope": "openid email", "code_challenge_method": "S256"},
        issuer="https://accounts.google.com",
        id_token_signing_alg_values_supported=["RS256"],
    )
    app.extensions["google_oidc_client"] = client
    browser = app.test_client()
    browser.environ_base.update(HTTP_X_FORWARDED_PROTO="https", **{"wsgi.url_scheme": "https"})
    yield app, browser, users, db
    db.rollback()
    ids = [o.id for o in orgs]
    db.query(UserIdentity).filter(UserIdentity.org_id.in_(ids)).delete(synchronize_session=False)
    db.query(AuditLog).filter(AuditLog.org_id.in_(ids)).delete(synchronize_session=False)
    db.query(EntityEvent).filter(EntityEvent.org_id.in_(ids)).delete(synchronize_session=False)
    db.query(User).filter(User.org_id.in_(ids)).delete(synchronize_session=False)
    db.query(Organisation).filter(Organisation.id.in_(ids)).delete(synchronize_session=False)
    db.commit()


def _sign_in(browser, claims, monkeypatch, endpoint="start", data=None):
    response = browser.post(f"/auth/google/{endpoint}", data=data or {})
    assert response.status_code == 302
    params = parse_qs(urlsplit(response.location).query)
    claims = dict(claims, nonce=params["nonce"][0])
    monkeypatch.setattr(
        routes, "exchange_verified_identity", lambda nonce: validate_verified_claims(claims, CLIENT_ID, nonce)
    )
    return browser.get("/auth/google/callback", query_string={"state": params["state"][0], "code": "mock-code"})


def _authenticate(browser, user):
    with browser.session_transaction() as s:
        s.update(user_id=str(user.id), org_id=str(user.org_id), user_email=user.email)


@pytest.mark.parametrize(
    "email,hd,expected",
    [
        ("a@gmail.com", None, True),
        ("a@workspace.test", "workspace.test", True),
        ("a@workspace.test", "other.test", False),
        ("a@personal.test", None, False),
        ("a@gmail.com.attacker.test", None, False),
        ("a@workspace.test", "sub.workspace.test", False),
    ],
)
def test_google_is_authoritative_only_for_gmail_or_matching_hd(email, hd, expected):
    assert authoritative_email(_claims(email, hd=hd)) is expected


@pytest.mark.parametrize(
    "changes",
    [
        {"iss": "https://attacker.test"},
        {"aud": "another-client"},
        {"exp": int(time.time()) - 1},
        {"email_verified": False},
        {"email_verified": "true"},
        {"nonce": "wrong"},
        {"nonce": None, "nonce_supported": False},
        {"aud": [CLIENT_ID, "other"]},
        {"azp": "other"},
        {"sub": ""},
        {"email": "a@gmail.com "},
    ],
)
def test_strict_claim_validation(changes):
    with pytest.raises(GoogleSignInError):
        validate_verified_claims(_claims("a@gmail.com", **changes), CLIENT_ID, "test-nonce")


def test_start_uses_code_pkce_state_nonce(world):
    _, browser, _, _ = world
    response = browser.post("/auth/google/start")
    q = parse_qs(urlsplit(response.location).query)
    assert q["response_type"] == ["code"]
    assert q["code_challenge_method"] == ["S256"]
    assert q["state"][0] and q["nonce"][0] and q["code_challenge"][0]
    assert q["scope"] == ["openid email"]
    with browser.session_transaction() as s:
        saved = s[f"_state_google_{q['state'][0]}"]["data"]
        assert saved["code_verifier"] and saved["nonce"] == q["nonce"][0]
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("state,age", [("wrong", 0), ("", 0), (None, 601)])
def test_wrong_missing_or_expired_state_never_reaches_provider(world, monkeypatch, state, age):
    _, browser, _, _ = world
    response = browser.post("/auth/google/start")
    q = parse_qs(urlsplit(response.location).query)
    with browser.session_transaction() as s:
        flow = dict(s["google_flow"])
        flow["created_at"] -= age
        s["google_flow"] = flow

    def forbidden(nonce):
        pytest.fail("Invalid state reached provider verification")

    monkeypatch.setattr(routes, "exchange_verified_identity", forbidden)
    response = browser.get(
        "/auth/google/callback", query_string={"state": q["state"][0] if state is None else state, "code": "x"}
    )
    assert response.status_code == 400
    with browser.session_transaction() as s:
        assert "user_id" not in s


@pytest.mark.parametrize("workspace", [False, True])
def test_authoritative_email_links_same_existing_account(world, monkeypatch, workspace):
    _, browser, users, db = world
    user = users[0]
    hd = None
    if workspace:
        user.email = f"{uuid4().hex}@workspace.test"
        hd = "workspace.test"
        db.commit()
    response = _sign_in(browser, _claims(user.email, hd=hd), monkeypatch)
    assert response.location == "/dashboard"
    with browser.session_transaction() as s:
        assert s["user_id"] == str(user.id) and s["org_id"] == str(user.org_id)
        assert s["auth_method"] == "google"
    identity = db.query(UserIdentity).filter_by(user_id=user.id).one()
    assert identity.email_at_link == user.email
    assert db.query(AuditLog).filter_by(org_id=user.org_id, action="login_google").count() == 1


def test_non_authoritative_personal_domain_requires_explicit_link(world, monkeypatch):
    _, browser, users, db = world
    user = users[0]
    user.email = f"{uuid4().hex}@personal.test"
    db.commit()
    claims = _claims(user.email)
    assert _sign_in(browser, claims, monkeypatch).status_code == 400
    assert db.query(UserIdentity).filter_by(user_id=user.id).count() == 0
    _authenticate(browser, user)
    assert (
        _sign_in(browser, claims, monkeypatch, "link", {"password": DEFAULT_TEST_PASSWORD}).location
        == "/core/settings?google=linked"
    )
    browser.post("/auth/logout")
    assert _sign_in(browser, claims, monkeypatch).location == "/dashboard"


def test_subject_match_survives_email_change_and_does_not_hijack_other_user(world, monkeypatch):
    _, browser, users, db = world
    user, neighbor = users
    claims = _claims(user.email)
    assert _sign_in(browser, claims, monkeypatch).status_code == 302
    browser.post("/auth/logout")
    user = db.query(User).filter_by(id=user.id).one()
    user.email = f"{uuid4().hex}@new.test"
    db.commit()
    assert _sign_in(browser, dict(claims, email=neighbor.email), monkeypatch).location == "/dashboard"
    with browser.session_transaction() as s:
        assert s["user_id"] == str(user.id) and s["org_id"] == str(user.org_id)
    assert db.query(UserIdentity).filter_by(user_id=neighbor.id).count() == 0


def test_unlinked_subject_cannot_replace_existing_link(world, monkeypatch):
    _, browser, users, db = world
    user = users[0]
    _sign_in(browser, _claims(user.email), monkeypatch)
    browser.post("/auth/logout")
    assert _sign_in(browser, _claims(user.email), monkeypatch).status_code == 400
    assert db.query(UserIdentity).filter_by(user_id=user.id).count() == 1


def test_unknown_google_address_creates_no_users_or_orgs(world, monkeypatch):
    _, browser, _, db = world
    before = (db.query(User).count(), db.query(Organisation).count())
    assert _sign_in(browser, _claims(f"{uuid4().hex}@gmail.com"), monkeypatch).status_code == 400
    assert (db.query(User).count(), db.query(Organisation).count()) == before


@pytest.mark.parametrize("bad_state", ["inactive", "locked", "expired", "suspended"])
def test_existing_account_rules_apply_to_google(world, monkeypatch, bad_state):
    _, browser, users, db = world
    user = users[0]
    if bad_state == "inactive":
        user.is_active = False
    if bad_state == "locked":
        user.account_locked_until = datetime.now(UTC) + timedelta(minutes=1)
    if bad_state == "expired":
        user.access_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    if bad_state == "suspended":
        db.query(Organisation).filter_by(id=user.org_id).one().status = OrganisationStatus.SUSPENDED
    db.commit()
    assert _sign_in(browser, _claims(user.email), monkeypatch).status_code == 400
    assert db.query(UserIdentity).filter_by(user_id=user.id).count() == 0


def test_signed_in_session_cannot_switch_to_neighbor_google_account(world, monkeypatch):
    _, browser, users, db = world
    user, neighbor = users
    _authenticate(browser, user)
    assert _sign_in(browser, _claims(neighbor.email), monkeypatch).status_code == 400
    with browser.session_transaction() as s:
        assert s["user_id"] == str(user.id)
    assert db.query(UserIdentity).filter_by(user_id=neighbor.id).count() == 0


def test_explicit_link_cannot_steal_another_tenant_subject(world, monkeypatch):
    _, browser, users, db = world
    user, neighbor = users
    claims = _claims(user.email)
    _sign_in(browser, claims, monkeypatch)
    browser.post("/auth/logout")
    _authenticate(browser, neighbor)
    assert _sign_in(browser, claims, monkeypatch, "link", {"password": DEFAULT_TEST_PASSWORD}).status_code == 400
    assert db.query(UserIdentity).filter_by(user_id=neighbor.id).count() == 0


def test_link_requires_correct_password(world):
    _, browser, users, _ = world
    _authenticate(browser, users[0])
    assert browser.post("/auth/google/link", data={"password": "wrong"}).status_code == 401


@pytest.mark.parametrize("change", ["password", "account"])
def test_link_aborts_if_account_or_password_changes(world, monkeypatch, change):
    _, browser, users, db = world
    user, neighbor = users
    _authenticate(browser, user)
    response = browser.post("/auth/google/link", data={"password": DEFAULT_TEST_PASSWORD})
    q = parse_qs(urlsplit(response.location).query)
    if change == "password":
        user = db.query(User).filter_by(id=user.id).one()
        user.password_hash = AuthService.hash_password("Changed-Passw0rd!")
        db.commit()
    else:
        _authenticate(browser, neighbor)
    monkeypatch.setattr(routes, "exchange_verified_identity", lambda nonce: _claims(user.email, nonce=nonce))
    assert browser.get("/auth/google/callback", query_string={"state": q["state"][0], "code": "x"}).status_code == 400
    assert db.query(UserIdentity).filter_by(user_id=user.id).count() == 0


def test_google_totp_still_required_and_records_method_only_after_completion(world, monkeypatch):
    _, browser, users, db = world
    user = users[0]
    user.two_factor_enabled = True
    user.totp_secret = pyotp.random_base32()
    db.commit()
    assert _sign_in(browser, _claims(user.email), monkeypatch).location == "/auth/google/challenge"
    with browser.session_transaction() as s:
        assert "user_id" not in s and s["pending_2fa_user_id"] == str(user.id)
    assert db.query(AuditLog).filter_by(org_id=user.org_id, action="login_google").count() == 0
    response = browser.post("/auth/verify-2fa", json={"token": pyotp.TOTP(user.totp_secret).now()})
    assert response.status_code == 200
    with browser.session_transaction() as s:
        assert s["user_id"] == str(user.id) and s["auth_method"] == "google"
    assert db.query(AuditLog).filter_by(org_id=user.org_id, action="login_google").count() == 1


@pytest.mark.parametrize("revoke", ["inactive", "expired", "locked", "identity"])
def test_pending_google_totp_cannot_outlive_revocation(world, monkeypatch, revoke):
    _, browser, users, db = world
    user = users[0]
    user.two_factor_enabled = True
    user.totp_secret = pyotp.random_base32()
    db.commit()
    _sign_in(browser, _claims(user.email), monkeypatch)
    user = db.query(User).filter_by(id=user.id).one()
    if revoke == "inactive":
        user.is_active = False
    if revoke == "expired":
        user.access_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    if revoke == "locked":
        user.account_locked_until = datetime.now(UTC) + timedelta(minutes=1)
    if revoke == "identity":
        db.query(UserIdentity).filter_by(user_id=user.id).delete()
    db.commit()
    assert browser.post("/auth/verify-2fa", json={"token": pyotp.TOTP(user.totp_secret).now()}).status_code == 401
    with browser.session_transaction() as s:
        assert "user_id" not in s


def test_admin_google_login_without_totp_still_requires_enrollment(world, monkeypatch):
    app, browser, users, db = world
    app.config["REQUIRE_ADMIN_2FA"] = True
    users[0].role = UserRole.ADMIN
    db.commit()
    assert _sign_in(browser, _claims(users[0].email), monkeypatch).location == "/core/settings?enroll2fa=1"
    assert browser.get("/auth/google/methods").status_code == 403


@pytest.mark.parametrize("mismatch", [None, "email", "non-authoritative", "expired", "already-linked"])
def test_google_accepts_only_the_address_and_account_of_pending_invite(world, monkeypatch, mismatch):
    _, browser, users, db = world
    user, neighbor = users
    user.is_active = False
    token = issue_invite(user)
    claims = _claims(user.email)
    if mismatch == "email":
        claims["email"] = neighbor.email
    if mismatch == "non-authoritative":
        user.email = f"{uuid4().hex}@personal.test"
        claims["email"] = user.email
    if mismatch == "expired":
        user.invite_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    if mismatch == "already-linked":
        db.add(
            UserIdentity(
                org_id=neighbor.org_id,
                user_id=neighbor.id,
                provider="google",
                subject=claims["sub"],
                email_at_link=neighbor.email,
            )
        )
    db.commit()
    before = db.query(User).count()
    if mismatch == "expired":
        assert browser.post("/auth/google/invite", data={"token": token}).status_code == 400
    else:
        response = _sign_in(browser, claims, monkeypatch, "invite", {"token": token})
        assert response.status_code == (302 if mismatch is None else 400)
    db.expire_all()
    assert db.query(User).count() == before
    invited = db.query(User).filter_by(id=user.id).one()
    if mismatch is None:
        assert invited.is_active and not invited.invite_token_hash and not invited.password_hash
        assert browser.post("/auth/google/invite", data={"token": token}).status_code == 400
    else:
        assert not invited.is_active and invited.invite_token_hash


def test_unlink_requires_password_and_keeps_password_login_available(world, monkeypatch):
    _, browser, users, db = world
    user = users[0]
    _sign_in(browser, _claims(user.email), monkeypatch)
    assert browser.post("/auth/google/unlink", data={"password": "wrong"}).status_code == 401
    assert db.query(UserIdentity).filter_by(user_id=user.id).count() == 1
    assert browser.post("/auth/google/unlink", data={"password": DEFAULT_TEST_PASSWORD}).status_code == 302
    assert db.query(UserIdentity).filter_by(user_id=user.id).count() == 0
    browser.post("/auth/logout")
    assert browser.post("/auth/login", json={"email": user.email, "password": DEFAULT_TEST_PASSWORD}).status_code == 200


def test_google_only_invite_can_add_password_but_cannot_unlink_without_one(world, monkeypatch):
    _, browser, users, db = world
    user = users[0]
    user.is_active = False
    token = issue_invite(user)
    db.commit()
    _sign_in(browser, _claims(user.email), monkeypatch, "invite", {"token": token})
    assert browser.post("/auth/google/unlink", data={"password": DEFAULT_TEST_PASSWORD}).status_code == 401
    assert (
        browser.post(
            "/auth/google/password", data={"password": DEFAULT_TEST_PASSWORD, "password_confirm": DEFAULT_TEST_PASSWORD}
        ).status_code
        == 302
    )
    assert browser.post("/auth/google/unlink", data={"password": DEFAULT_TEST_PASSWORD}).status_code == 302


def test_identity_cannot_reference_user_in_another_tenant(world):
    _, _, users, db = world
    user, neighbor = users
    db.add(
        UserIdentity(
            org_id=neighbor.org_id, user_id=user.id, provider="google", subject=uuid4().hex, email_at_link=user.email
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_google_posts_are_not_exempt_from_csrf(world):
    app, browser, _, _ = world
    app.config["WTF_CSRF_ENABLED"] = True
    assert browser.post("/auth/google/start").status_code == 400


def test_authlib_verifies_real_signed_token_and_rejects_hostile_tokens(world, monkeypatch):
    app, _, _, _ = world
    client = app.extensions["google_oidc_client"]
    key = RSAKey.generate_key(2048, parameters={"kid": "test-key"})
    public = key.as_dict(private=False)
    client.server_metadata["jwks"] = {"keys": [public]}
    claims = _claims("a@gmail.com")
    token = jwt.encode({"alg": "RS256", "kid": "test-key"}, claims, key)
    with app.test_request_context("/auth/google/callback"):
        parsed = client.parse_id_token({"id_token": token}, nonce="test-nonce", leeway=0)
        assert validate_verified_claims(parsed, CLIENT_ID, "test-nonce")["email"] == "a@gmail.com"
        for changes in (
            {"iss": "https://attacker.test"},
            {"aud": "wrong"},
            {"nonce": "wrong"},
            {"exp": int(time.time()) - 1},
        ):
            bad = jwt.encode({"alg": "RS256", "kid": "test-key"}, dict(claims, **changes), key)
            with pytest.raises(Exception):
                client.parse_id_token({"id_token": bad}, nonce="test-nonce", leeway=0)
        attacker_key = RSAKey.generate_key(2048, parameters={"kid": "test-key"})
        bad = jwt.encode({"alg": "RS256", "kid": "test-key"}, claims, attacker_key)
        with pytest.raises(Exception):
            client.parse_id_token({"id_token": bad}, nonce="test-nonce", leeway=0)


def test_callback_cannot_be_replayed_with_the_updated_browser_session(world, monkeypatch):
    _, browser, users, _ = world
    _sign_in(browser, _claims(users[0].email), monkeypatch)
    response = browser.get("/auth/google/callback", query_string={"state": "previous", "code": "used"})
    assert response.status_code == 400


def test_provider_verification_failure_never_links_or_logs_in(world, monkeypatch):
    _, browser, users, db = world
    response = browser.post("/auth/google/start")
    q = parse_qs(urlsplit(response.location).query)

    def invalid_token(nonce):
        raise GoogleSignInError("test token rejected")

    monkeypatch.setattr(routes, "exchange_verified_identity", invalid_token)
    response = browser.get("/auth/google/callback", query_string={"state": q["state"][0], "code": "bad"})
    assert response.status_code == 400
    assert db.query(UserIdentity).filter_by(user_id=users[0].id).count() == 0
    with browser.session_transaction() as s:
        assert "user_id" not in s


def test_authlib_code_exchange_consumes_state_and_sends_the_saved_pkce_verifier(world, monkeypatch):
    app, browser, users, _ = world
    client = app.extensions["google_oidc_client"]
    key = RSAKey.generate_key(2048, parameters={"kid": "exchange-key"})
    client.server_metadata["jwks"] = {"keys": [key.as_dict(private=False)]}
    start = browser.post("/auth/google/start")
    q = parse_qs(urlsplit(start.location).query)
    with browser.session_transaction() as s:
        verifier = s[f"_state_google_{q['state'][0]}"]["data"]["code_verifier"]
    claims = _claims(users[0].email, nonce=q["nonce"][0])
    id_token = jwt.encode({"alg": "RS256", "kid": "exchange-key"}, claims, key)

    def fetch(**params):
        assert params["code"] == "one-time-code"
        assert params["code_verifier"] == verifier
        assert params["redirect_uri"] == app.config["GOOGLE_REDIRECT_URI"]
        return {"id_token": id_token, "access_token": "unused-test-access-token", "token_type": "Bearer"}

    monkeypatch.setattr(client, "fetch_access_token", fetch)
    response = browser.get("/auth/google/callback", query_string={"state": q["state"][0], "code": "one-time-code"})
    assert response.location == "/dashboard"
    with browser.session_transaction() as s:
        assert s["user_id"] == str(users[0].id)
        assert all(not key.startswith("_state_google_") for key in s)
        assert "id_token" not in s and "access_token" not in s


def test_settings_lists_only_current_tenant_identity_and_escapes_link_email(world, monkeypatch):
    app, browser, users, db = world
    user, neighbor = users
    _sign_in(browser, _claims(user.email), monkeypatch)
    db.add(
        UserIdentity(
            org_id=neighbor.org_id,
            user_id=neighbor.id,
            provider="google",
            subject=uuid4().hex,
            email_at_link="neighbor-secret@gmail.com",
        )
    )
    identity = db.query(UserIdentity).filter_by(user_id=user.id).one()
    identity.email_at_link = "<img src=x onerror=alert(1)>@gmail.com"
    db.commit()
    with app.test_request_context():
        from flask import g, render_template

        g.current_user = db.query(User).filter_by(id=user.id).one()
        html = render_template("google_account_settings.html")
    assert "neighbor-secret" not in html
    assert "<img src=x" not in html and "&lt;img" in html
    response = browser.get("/auth/google/methods")
    assert len(response.json["identities"]) == 1


@pytest.mark.parametrize("age", [601, 3600])
def test_adding_google_only_password_requires_fresh_google_authentication(world, monkeypatch, age):
    _, browser, users, db = world
    user = users[0]
    user.is_active = False
    token = issue_invite(user)
    db.commit()
    _sign_in(browser, _claims(user.email), monkeypatch, "invite", {"token": token})
    with browser.session_transaction() as s:
        s["google_authenticated_at"] -= age
    response = browser.post(
        "/auth/google/password", data={"password": DEFAULT_TEST_PASSWORD, "password_confirm": DEFAULT_TEST_PASSWORD}
    )
    assert response.status_code == 401
    assert not db.query(User).filter_by(id=user.id).one().password_hash


@pytest.mark.parametrize("missing", ["client_id", "client_secret", "redirect_uri", "insecure_cookie"])
def test_enabled_oidc_fails_closed_without_secure_configuration(missing):
    from types import SimpleNamespace

    from flask import Flask

    config = SimpleNamespace(
        getboolean=lambda *args: True,
        google_client_id=CLIENT_ID,
        google_client_secret="test-only-secret",
        google_redirect_uri="https://test.biz-e.app/auth/google/callback",
    )
    app = Flask(__name__)
    app.config.update(SESSION_COOKIE_SECURE=True, SESSION_COOKIE_HTTPONLY=True)
    if missing == "insecure_cookie":
        app.config["SESSION_COOKIE_SECURE"] = False
    else:
        setattr(config, "google_" + missing, "")
    with pytest.raises(RuntimeError):
        oidc.setup_google_oidc(app, config)


@pytest.mark.parametrize(
    "fields",
    [{"password": 5}, {"password": DEFAULT_TEST_PASSWORD}, {"password": "a" * 73, "password_confirm": "a" * 73}],
)
def test_google_only_password_input_is_validated_without_mutation(world, monkeypatch, fields):
    _, browser, users, db = world
    user = users[0]
    user.is_active = False
    token = issue_invite(user)
    db.commit()
    _sign_in(browser, _claims(user.email), monkeypatch, "invite", {"token": token})
    assert browser.post("/auth/google/password", json=fields).status_code == 400
    assert not db.query(User).filter_by(id=user.id).one().password_hash


def test_google_challenge_page_reuses_the_existing_totp_verifier(world, monkeypatch):
    _, browser, users, db = world
    user = users[0]
    user.two_factor_enabled = True
    user.totp_secret = pyotp.random_base32()
    db.commit()
    _sign_in(browser, _claims(user.email), monkeypatch)
    response = browser.get("/auth/google/challenge")
    assert response.status_code == 200
    assert b"/auth/verify-2fa" in response.data
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Referrer-Policy"] == "no-referrer"


def test_oidc_setup_enabled_and_disabled_uses_no_network(monkeypatch):
    from types import SimpleNamespace

    from flask import Flask

    app = Flask(__name__)
    app.config.update(SESSION_COOKIE_SECURE=True, SESSION_COOKIE_HTTPONLY=True)
    config = SimpleNamespace(
        getboolean=lambda *args: True,
        google_client_id=CLIENT_ID,
        google_client_secret="test-only-secret",
        google_redirect_uri="https://test.biz-e.app/auth/google/callback",
    )
    oidc.setup_google_oidc(app, config)
    assert app.extensions["google_oidc_client"].client_id == CLIENT_ID
    with app.app_context():
        assert oidc.google_client() is app.extensions["google_oidc_client"]
    app2 = Flask(__name__)
    oidc.setup_google_oidc(app2, SimpleNamespace(getboolean=lambda *args: False))
    assert "google_oidc_client" not in app2.extensions
    with app2.app_context(), pytest.raises(GoogleSignInError):
        oidc.google_client()


def test_provider_must_return_a_verified_id_token(world, monkeypatch):
    app, _, _, _ = world
    client = app.extensions["google_oidc_client"]
    monkeypatch.setattr(client, "authorize_access_token", lambda **kwargs: {"access_token": "irrelevant"})
    with app.test_request_context(), pytest.raises(GoogleSignInError):
        oidc.exchange_verified_identity("nonce")
