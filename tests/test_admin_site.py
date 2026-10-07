"""The admin site: who gets in, what stays shut, and what its operations do. Real PostgreSQL."""

import time
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from authlib.integrations.flask_client import OAuth

from app.admin_site import auth
from app.admin_site import operations as ops
from app.admin_site.app_factory import create_admin_app
from app.admin_site.settings import (
    DEFAULT_ALLOWED_EMAILS,
    IDLE_MINUTES,
    SESSION_HOURS,
    AdminSettings,
    load_settings,
    parse_allowed_emails,
)
from app.core.db.models.audit_log import AuditLog
from app.core.db.models.feature_subscription import FeatureSubscription
from app.core.db.models.organisation import Organisation, OrganisationStatus
from app.core.db.models.site import Site
from app.core.db.models.user import User, UserRole
from app.core.security.auth_service import AuthService
from app.core.security.tenant_scope import unscoped
from app.features.google_sign_in.service import validate_verified_claims
from app.utils.config_loader import config

CLIENT_ID = "admin-test.apps.googleusercontent.com"
JOHNNY, NIKO = DEFAULT_ALLOWED_EMAILS


def _settings(**changes):
    values = {
        "environment": "test",
        "allowed_emails": frozenset(DEFAULT_ALLOWED_EMAILS),
        "require_authoritative_email": True,
        "secret_key": "admin-site-test-key-" + "x" * 32,
        "google_client_id": CLIENT_ID,
        "google_client_secret": "test-only-secret",
        "google_redirect_uri": "https://admin.biz-e.app/auth/google/callback",
        "customer_app_url": "https://biz-e.app",
    }
    values.update(changes)
    return AdminSettings(**values)


def _app(csrf=False, **changes):
    app = create_admin_app(_settings(**changes))
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=csrf)
    auth.limiter.storage.reset()
    # A statically configured Google client: nothing in these tests reaches the network.
    app.extensions["google_oidc_client"] = OAuth(app).register(
        name="google",
        client_id=CLIENT_ID,
        client_secret="test-only-secret",
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        access_token_url="https://oauth2.googleapis.com/token",
        client_kwargs={"scope": "openid email", "code_challenge_method": "S256"},
        issuer="https://accounts.google.com",
        id_token_signing_alg_values_supported=["RS256"],
    )
    return app


def _browser(app):
    browser = app.test_client()
    browser.environ_base.update(HTTP_X_FORWARDED_PROTO="https", **{"wsgi.url_scheme": "https"})
    return browser


@pytest.fixture
def site():
    app = _app()
    return app, _browser(app)


def _claims(email, **changes):
    claims = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "exp": int(time.time()) + 300,
        "sub": uuid4().hex,
        "email": email,
        "email_verified": True,
        "hd": email.rsplit("@", 1)[1].lower(),
    }
    claims.update(changes)
    return {key: value for key, value in claims.items() if value is not None}


def _google_sign_in(browser, claims, monkeypatch):
    response = browser.post("/auth/google/start")
    assert response.status_code == 302 and response.location.startswith("https://accounts.google.com/")
    params = parse_qs(urlsplit(response.location).query)
    claims = dict(claims, nonce=params["nonce"][0])
    monkeypatch.setattr(
        auth, "exchange_verified_identity", lambda nonce: validate_verified_claims(claims, CLIENT_ID, nonce)
    )
    return browser.get("/auth/google/callback", query_string={"state": params["state"][0], "code": "mock-code"})


def _signed_in(browser, email=JOHNNY, **changes):
    now = time.time()
    with browser.session_transaction() as session:
        session.update(admin_email=email, admin_sub="sub", signed_in_at=now, last_seen_at=now)
        session.update(changes)


@pytest.fixture
def created(db):
    """Names of organisations a test creates through the site; removed afterwards."""
    names = []
    yield names
    db.rollback()
    with unscoped():
        ids = [org.id for org in db.query(Organisation).filter(Organisation.name.in_(names)).all()]
        for model in (AuditLog, FeatureSubscription, Site, User):
            db.query(model).filter(model.org_id.in_(ids)).delete(synchronize_session=False)
        db.query(Organisation).filter(Organisation.id.in_(ids)).delete(synchronize_session=False)
        db.commit()


@pytest.fixture
def org(db, created):
    name = f"Admin site test {uuid4().hex[:12]}"
    created.append(name)
    organisation, _, _ = ops.create_organisation(
        db, name=name, admin_email=f"{uuid4().hex}@example.test", password="a-long-test-password", actor="test"
    )
    return organisation


# ── Who gets in ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("email", [JOHNNY, NIKO, JOHNNY.upper()])
def test_an_allow_listed_google_account_signs_in(site, monkeypatch, email):
    _, browser = site
    response = _google_sign_in(browser, _claims(email), monkeypatch)
    assert response.status_code == 302 and response.location.endswith("/organisations")
    assert browser.get("/organisations").status_code == 200


@pytest.mark.parametrize(
    "claims",
    [
        _claims("someone.else@whistlebird.co.nz"),
        _claims("johnny@whistlebird.co.nz.attacker.test"),
        _claims("johnny@gmail.com"),
        # The right address on a personal Google account: Google is not the authority for it.
        _claims(JOHNNY, hd=None),
        _claims(JOHNNY, hd="attacker.test"),
    ],
)
def test_any_other_google_account_is_refused(site, monkeypatch, claims):
    _, browser = site
    response = _google_sign_in(browser, claims, monkeypatch)
    assert response.status_code == 403
    assert browser.get("/organisations").status_code == 302


def test_an_unverified_email_never_reaches_the_allow_list(site, monkeypatch):
    _, browser = site
    assert _google_sign_in(browser, _claims(JOHNNY, email_verified=False), monkeypatch).status_code == 400
    assert auth.permitted_email(_claims(JOHNNY, email_verified="true"), _settings()) is None


def test_the_callback_refuses_a_state_it_did_not_issue(site, monkeypatch):
    _, browser = site
    monkeypatch.setattr(auth, "exchange_verified_identity", lambda nonce: _claims(JOHNNY))
    assert browser.get("/auth/google/callback", query_string={"state": "forged", "code": "x"}).status_code == 400
    browser.post("/auth/google/start")
    assert browser.get("/auth/google/callback", query_string={"state": "forged", "code": "x"}).status_code == 400
    assert browser.get("/organisations").status_code == 302


def test_starting_sign_in_needs_a_csrf_token():
    browser = _browser(_app(csrf=True))
    assert browser.post("/auth/google/start").status_code == 400


# ── What stays shut ────────────────────────────────────────────────────────────


def test_every_route_but_the_public_ones_needs_an_admin(site):
    app, browser = site
    checked = 0
    for rule in app.url_map.iter_rules():
        if rule.endpoint in auth.PUBLIC_ENDPOINTS:
            continue
        path = rule.rule
        for argument in rule.arguments:
            path = path.replace(f"<{argument}>", str(uuid4()))
        for method in rule.methods - {"HEAD", "OPTIONS"}:
            response = browser.open(path, method=method)
            if method == "GET":
                assert response.status_code == 302 and response.location.endswith("/sign-in"), (method, path)
            else:
                assert response.status_code == 401, (method, path)
            checked += 1
    assert checked >= 10
    # And the public set is exactly what it is meant to be.
    assert {rule.endpoint for rule in app.url_map.iter_rules()} >= auth.PUBLIC_ENDPOINTS
    assert auth.PUBLIC_ENDPOINTS == {
        "admin_auth.sign_in",
        "admin_auth.start",
        "admin_auth.callback",
        "healthcheck",
        "static",
        "shared_style",
    }


@pytest.mark.parametrize(
    "stale",
    [
        {"last_seen_at": time.time() - IDLE_MINUTES * 60 - 5},
        {"signed_in_at": time.time() - SESSION_HOURS * 3600 - 5},
        {"admin_email": "someone.else@whistlebird.co.nz"},
        {"signed_in_at": "yesterday"},
    ],
)
def test_a_stale_or_unlisted_session_is_ended(site, stale):
    _, browser = site
    _signed_in(browser, **stale)
    assert browser.get("/organisations").status_code == 302
    with browser.session_transaction() as session:
        assert "admin_email" not in session


def test_removing_someone_from_the_allow_list_ends_their_session():
    app = _app(allowed_emails=frozenset({JOHNNY}))
    browser = _browser(app)
    _signed_in(browser, email=NIKO)
    assert browser.get("/organisations").status_code == 302


def test_sign_out_ends_the_session(site):
    _, browser = site
    _signed_in(browser)
    assert browser.post("/sign-out").status_code == 302
    assert browser.get("/organisations").status_code == 302


def test_the_session_cookie_is_its_own_and_locked_down(site, monkeypatch):
    app, browser = site
    response = _google_sign_in(browser, _claims(JOHNNY), monkeypatch)
    cookie = next(value for value in response.headers.getlist("Set-Cookie") if value.startswith("bize_admin_session="))
    assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=Lax" in cookie
    page = browser.get("/organisations")
    assert page.headers["Cache-Control"] == "no-store"
    assert "default-src 'none'" in page.headers["Content-Security-Policy"]
    assert page.headers["X-Frame-Options"] == "DENY"
    assert b"<script" not in page.data


def test_only_the_two_shared_stylesheets_are_served(site):
    _, browser = site
    assert browser.get("/shared/workspace-overviews.css").status_code == 200
    assert browser.get("/shared/styles.css").status_code == 404
    assert browser.get("/shared/..%2f..%2fconfig%2fprod.ini").status_code in {302, 404}


# ── Settings fail closed ───────────────────────────────────────────────────────


def test_the_allow_list_defaults_to_the_two_admins_and_is_never_empty():
    assert parse_allowed_emails(None) == {"johnny@whistlebird.co.nz", "niko@whistlebird.co.nz"}
    assert parse_allowed_emails(" A@x.test , b@x.test ") == {"a@x.test", "b@x.test"}
    for bad in (",", "not-an-email", "a@x.test, @x.test"):
        with pytest.raises(RuntimeError):
            parse_allowed_emails(bad)


def test_production_needs_its_own_session_key(monkeypatch):
    monkeypatch.setattr(config, "environment", "prod")
    monkeypatch.delenv("ADMIN_FLASK_SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ADMIN_FLASK_SECRET_KEY"):
        load_settings(config)
    monkeypatch.setenv("ADMIN_FLASK_SECRET_KEY", "k" * 40)
    monkeypatch.setenv("FLASK_SECRET_KEY", "k" * 40)
    with pytest.raises(RuntimeError, match="must differ"):
        load_settings(config)
    monkeypatch.setenv("FLASK_SECRET_KEY", "j" * 40)
    assert load_settings(config).secret_key == "k" * 40


def test_the_app_will_not_start_without_a_google_client():
    with pytest.raises(RuntimeError, match="Google sign-in requires credentials"):
        create_admin_app(_settings(google_client_secret=""))
    with pytest.raises(RuntimeError, match="Google sign-in requires credentials"):
        create_admin_app(_settings(google_redirect_uri="http://admin.biz-e.app/auth/google/callback"))


# ── Organisations, people and features ─────────────────────────────────────────


def test_creating_an_organisation_invites_its_admin_and_is_audited(site, db, created):
    _, browser = site
    _signed_in(browser)
    name, email = f"Admin site test {uuid4().hex[:12]}", f"{uuid4().hex}@example.test"
    created.append(name)
    response = browser.post("/organisations", data={"name": name, "admin_email": email})
    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert "https://biz-e.app/invite/" in page and name in page

    with unscoped():
        org = db.query(Organisation).filter(Organisation.name == name).one()
        user = db.query(User).filter(User.org_id == org.id).one()
        entry = db.query(AuditLog).filter(AuditLog.org_id == org.id, AuditLog.entity == "organisation").one()
    assert (user.email, user.role, user.is_active) == (email, UserRole.ADMIN, False)
    assert user.invite_token_hash and user.invite_expires_at
    assert entry.action == "platform_admin.create" and entry.meta_data["platform_admin"] == JOHNNY

    # The same name again is refused, on the list page, with what was typed kept.
    again = browser.post("/organisations", data={"name": name, "admin_email": "other@example.test"})
    assert again.status_code == 400 and "already exists" in again.get_data(as_text=True)
    assert name in browser.get("/organisations", query_string={"q": name[-12:]}).get_data(as_text=True)


def test_suspending_takes_the_name_typed_out(site, db, org):
    _, browser = site
    _signed_in(browser)
    url = f"/organisations/{org.id}/status"
    assert browser.post(url, data={"status": "suspended", "confirm_name": "nope"}).status_code == 400
    db.expire_all()
    assert ops.get_organisation(db, org.id).status is OrganisationStatus.ACTIVE
    assert browser.post(url, data={"status": "suspended", "confirm_name": org.name}).status_code == 200
    db.expire_all()
    assert ops.get_organisation(db, org.id).status is OrganisationStatus.SUSPENDED
    assert browser.post(url, data={"status": "active"}).status_code == 200
    db.expire_all()
    assert ops.get_organisation(db, org.id).status is OrganisationStatus.ACTIVE


def test_features_switch_on_and_off(site, db, org):
    _, browser = site
    _signed_in(browser)
    url = f"/organisations/{org.id}/features"
    assert browser.post(url, data={"feature": "compliant", "state": "on"}).status_code == 200
    db.expire_all()
    assert [(row.feature_key, row.active) for row in ops.list_features(db, org.id)] == [("compliant", True)]
    assert browser.post(url, data={"feature": "compliant", "state": "off"}).status_code == 200
    db.expire_all()
    assert [(row.feature_key, row.active) for row in ops.list_features(db, org.id)] == [("compliant", False)]
    assert browser.post(url, data={"feature": "not a key!", "state": "on"}).status_code == 400


def test_inviting_resetting_and_unlocking_people(site, db, org):
    _, browser = site
    _signed_in(browser)
    email = f"{uuid4().hex}@example.test"
    invited = browser.post(f"/organisations/{org.id}/users", data={"email": email, "role": "member"})
    assert invited.status_code == 200 and "https://biz-e.app/invite/" in invited.get_data(as_text=True)
    with unscoped():
        person = db.query(User).filter(User.email == email).one()
    first_hash = person.invite_token_hash
    assert browser.post(f"/organisations/{org.id}/users/{person.id}/invite").status_code == 200
    db.expire_all()
    with unscoped():
        assert db.query(User).filter(User.id == person.id).one().invite_token_hash != first_hash

    admin = next(user for user in ops.list_users(db, org.id) if user.is_active)
    old_hash = admin.password_hash
    with unscoped():
        from app.core.db.repositories.user_repo import UserRepository

        UserRepository(db).lock_account(admin.id, 30)
    assert browser.post(f"/organisations/{org.id}/users/{admin.id}/unlock").status_code == 200
    db.expire_all()
    assert not ops.is_locked(ops.list_users(db, org.id, active_only=True)[0])

    reset = browser.post(f"/organisations/{org.id}/users/{admin.id}/reset-password")
    assert reset.status_code == 200 and "Temporary password" in reset.get_data(as_text=True)
    db.expire_all()
    with unscoped():
        refreshed = db.query(User).filter(User.id == admin.id).one()
    assert refreshed.password_hash != old_hash
    assert not AuthService.verify_password("a-long-test-password", refreshed.password_hash)


def test_a_person_is_only_reachable_through_their_own_organisation(site, db, org, created):
    _, browser = site
    _signed_in(browser)
    other_name = f"Admin site test {uuid4().hex[:12]}"
    created.append(other_name)
    other, outsider, _ = ops.create_organisation(
        db, name=other_name, admin_email=f"{uuid4().hex}@example.test", password="a-long-test-password", actor="test"
    )
    before = outsider.password_hash
    response = browser.post(f"/organisations/{org.id}/users/{outsider.id}/reset-password")
    assert response.status_code == 400
    db.expire_all()
    with unscoped():
        assert db.query(User).filter(User.id == outsider.id).one().password_hash == before
    assert browser.get(f"/organisations/{uuid4()}").status_code == 404
    assert browser.get("/organisations/not-a-uuid").status_code == 404


def test_demo_and_system_pages_render(site):
    _, browser = site
    _signed_in(browser)
    assert "Not available yet" in browser.get("/demo").get_data(as_text=True)
    system = browser.get("/system").get_data(as_text=True)
    assert JOHNNY in system and NIKO in system and "Reachable" in system
