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
        from app.core.db.models.trusted_device import TrustedDevice
        from app.core.db.models.two_factor_backup_code import TwoFactorBackupCode
        from app.core.db.models.user_identity import UserIdentity

        user_ids = [row.id for row in db.query(User.id).filter(User.org_id.in_(ids)).all()]
        db.query(TrustedDevice).filter(TrustedDevice.user_id.in_(user_ids)).delete(synchronize_session=False)
        from app.admin_site import documents as admin_documents
        from app.admin_site.models import AdminOrgDocument, AdminOrgNote

        for document in db.query(AdminOrgDocument).filter(AdminOrgDocument.org_id.in_(ids)).all():
            admin_documents.remove(document.org_id, document.stored_name)
        for model in (AdminOrgNote, AdminOrgDocument):
            db.query(model).filter(model.org_id.in_(ids)).delete(synchronize_session=False)
        for model in (AuditLog, FeatureSubscription, TwoFactorBackupCode, UserIdentity, Site, User):
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


def test_the_sign_in_form_works_with_csrf_on_as_a_browser_sends_it():
    """Over HTTPS, CSRF protection also checks the Referer. A browser only sends one if the
    page's referrer policy allows it, so the policy and the check are tested together."""
    import re

    browser = _browser(_app(csrf=True))
    base = "https://admin.biz-e.app"
    page = browser.get("/sign-in", base_url=base)
    assert page.headers["Referrer-Policy"] == "same-origin"
    html = page.get_data(as_text=True)
    assert 'name="referrer" content="same-origin"' in html and "no-referrer" not in html
    token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)

    def start(**headers):
        return browser.post("/auth/google/start", base_url=base, data={"csrf_token": token}, headers=headers)

    assert start().status_code == 400  # what a no-referrer policy made every browser send
    assert start(Referer="https://attacker.test/").status_code == 400
    sent = start(Referer=f"{base}/sign-in")
    assert sent.status_code == 302 and sent.location.startswith("https://accounts.google.com/")


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
    assert response.status_code == 404
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


# ── Support actions ────────────────────────────────────────────────────────────


def _admin_of(db, org):
    return next(user for user in ops.list_users(db, org.id) if user.role is UserRole.ADMIN)


def _reload(db, user):
    db.expire_all()
    with unscoped():
        return db.query(User).filter(User.id == user.id).one()


def test_the_only_admin_cannot_be_demoted_or_deactivated(site, db, org):
    _, browser = site
    _signed_in(browser)
    admin = _admin_of(db, org)
    base = f"/organisations/{org.id}/users/{admin.id}"
    for path, data in ((f"{base}/role", {"role": "member"}), (f"{base}/active", {"active": "no"})):
        response = browser.post(path, data=data)
        assert response.status_code == 400 and "only admin" in response.get_data(as_text=True)
    admin = _reload(db, admin)
    assert admin.role is UserRole.ADMIN and admin.is_active

    # With a second admin in place, the first can step down and be deactivated, then return.
    second, _ = ops.create_user(
        db, org.id, email=f"{uuid4().hex}@example.test", role="admin", password="a-long-test-password", actor="test"
    )
    assert browser.post(f"{base}/role", data={"role": "member"}).status_code == 200
    assert browser.post(f"{base}/active", data={"active": "no"}).status_code == 200
    admin = _reload(db, admin)
    assert admin.role is UserRole.MEMBER and not admin.is_active
    assert browser.post(f"{base}/active", data={"active": "yes"}).status_code == 200
    assert _reload(db, admin).is_active
    assert browser.post(f"{base}/role", data={"role": "owner"}).status_code == 400


def test_an_invited_person_is_not_activated_around_their_invite(site, db, org):
    _, browser = site
    _signed_in(browser)
    invited, _ = ops.create_user(db, org.id, email=f"{uuid4().hex}@example.test", actor="test")
    response = browser.post(f"/organisations/{org.id}/users/{invited.id}/active", data={"active": "yes"})
    assert response.status_code == 400 and not _reload(db, invited).is_active


def test_changing_an_email_refuses_one_already_in_use(site, db, org):
    _, browser = site
    _signed_in(browser)
    admin = _admin_of(db, org)
    other, _ = ops.create_user(db, org.id, email=f"{uuid4().hex}@example.test", actor="test")
    url = f"/organisations/{org.id}/users/{admin.id}/email"
    assert browser.post(url, data={"email": other.email}).status_code == 400
    assert browser.post(url, data={"email": "not an email"}).status_code == 400
    new_email = f"{uuid4().hex}@example.test"
    assert browser.post(url, data={"email": new_email.upper()}).status_code == 200
    assert _reload(db, admin).email == new_email


def test_resetting_2fa_removes_everything_tied_to_the_enrolment(site, db, org):
    from app.core.db.models.two_factor_backup_code import TwoFactorBackupCode
    from app.core.db.repositories.backup_code_repo import BackupCodeRepository

    _, browser = site
    _signed_in(browser)
    admin = _admin_of(db, org)
    url = f"/organisations/{org.id}/users/{admin.id}/two-factor"
    assert browser.post(url).status_code == 400  # nothing to reset

    with unscoped():
        admin.totp_secret, admin.two_factor_enabled = "JBSWY3DPEHPK3PXP", True
        db.commit()
        BackupCodeRepository(db).generate_and_store_codes(org.id, admin.id, commit=True)
        assert db.query(TwoFactorBackupCode).filter(TwoFactorBackupCode.user_id == admin.id).count() == 10
    assert "Reset 2FA" in browser.get(f"/organisations/{org.id}/users/{admin.id}").get_data(as_text=True)
    assert browser.post(url).status_code == 200
    admin = _reload(db, admin)
    assert not admin.two_factor_enabled and admin.totp_secret is None
    with unscoped():
        assert db.query(TwoFactorBackupCode).filter(TwoFactorBackupCode.user_id == admin.id).count() == 0


def test_renaming_an_organisation(site, db, org, created):
    _, browser = site
    _signed_in(browser)
    other_name = f"Admin site test {uuid4().hex[:12]}"
    created.append(other_name)
    ops.create_organisation(db, name=other_name, admin_email=f"{uuid4().hex}@example.test", actor="test")
    url = f"/organisations/{org.id}/name"
    assert browser.post(url, data={"name": other_name}).status_code == 400
    assert browser.post(url, data={"name": "  "}).status_code == 400
    new_name = f"Admin site test {uuid4().hex[:12]}"
    created.append(new_name)
    assert browser.post(url, data={"name": new_name}).status_code == 200
    db.expire_all()
    assert ops.get_organisation(db, org.id).name == new_name


def test_finding_a_person_by_email_across_organisations(site, db, org):
    _, browser = site
    _signed_in(browser)
    admin = _admin_of(db, org)
    page = browser.get("/people", query_string={"q": admin.email[:20].upper()}).get_data(as_text=True)
    assert admin.email in page and org.name in page and f"/organisations/{org.id}/users/{admin.id}" in page
    assert "at least three characters" in browser.get("/people", query_string={"q": "a@"}).get_data(as_text=True)
    # Wildcards are matched literally, not as "everything".
    assert ops.find_people(db, "%%%") == [] and ops.find_people(db, "___") == []


def test_history_shows_what_staff_and_customers_did(site, db, org):
    _, browser = site
    _signed_in(browser)
    admin = _admin_of(db, org)
    with unscoped():
        from app.core.db.repositories.audit_repo import AuditRepository

        AuditRepository(db).write_log(org_id=org.id, user_id=admin.id, action="login", entity="user")
    browser.post(f"/organisations/{org.id}/features", data={"feature": "compliant", "state": "on"})
    page = browser.get(f"/organisations/{org.id}/audit").get_data(as_text=True)
    assert "grant feature" in page and JOHNNY in page and "biz-e staff" in page
    assert admin.email in page and "login" in page
    overview = ops.organisation_overview(db, org.id)
    assert overview["last_sign_ins"][admin.id] == overview["last_sign_in"] and overview["sites"] == 1
    assert "Last sign-in" in browser.get(f"/organisations/{org.id}").get_data(as_text=True)


def test_the_cli_runs_the_same_operations(db, org):
    from click.testing import CliRunner

    from app.cli import cli

    runner = CliRunner()
    admin = _admin_of(db, org)
    found = runner.invoke(cli, ["find-user", "--email", admin.email])
    assert found.exit_code == 0 and str(admin.id) in found.output and org.name in found.output

    person = ["--org-id", str(org.id), "--user-id", str(admin.id)]
    refused = runner.invoke(cli, ["set-role", *person, "--role", "member"])
    assert refused.exit_code == 1 and "only admin" in refused.output
    assert runner.invoke(cli, ["deactivate-user", *person]).exit_code == 1
    assert runner.invoke(cli, ["reset-2fa", *person]).exit_code == 1

    invited = runner.invoke(cli, ["invite-user", "--org-id", str(org.id), "--email", f"{uuid4().hex}@example.test"])
    assert invited.exit_code == 0 and "/invite/" in invited.output
    assert runner.invoke(cli, ["suspend-org", "--org-id", str(org.id)]).exit_code == 0
    db.expire_all()
    assert ops.get_organisation(db, org.id).status is OrganisationStatus.SUSPENDED
    assert runner.invoke(cli, ["reactivate-org", "--org-id", str(org.id)]).exit_code == 0
    history = runner.invoke(cli, ["org-history", "--org-id", str(org.id)])
    assert history.exit_code == 0 and "platform_admin.set_status" in history.output and "cli" in history.output
    assert runner.invoke(cli, ["org-history", "--org-id", "nope"]).exit_code == 1


# ── More support actions ───────────────────────────────────────────────────────


def test_access_end_dates_follow_the_apps_own_rules(site, db, org):
    from datetime import UTC, datetime, timedelta

    _, browser = site
    _signed_in(browser)
    member, _ = ops.create_user(
        db, org.id, email=f"{uuid4().hex}@example.test", password="a-long-test-password", actor="test"
    )
    url = f"/organisations/{org.id}/users/{member.id}/access"
    soon = (datetime.now(UTC) + timedelta(days=14)).date().isoformat()
    assert browser.post(url, data={"until": "2020-01-01"}).status_code == 400
    assert browser.post(url, data={"until": "soon"}).status_code == 400
    assert browser.post(url, data={"until": soon}).status_code == 200
    assert _reload(db, member).access_expires_at is not None
    assert browser.post(url, data={"until": ""}).status_code == 200
    assert _reload(db, member).access_expires_at is None

    # An auditor always has an end date, at most 90 days out.
    with unscoped():
        member.role = UserRole.AUDITOR
        db.commit()
    assert browser.post(url, data={"until": ""}).status_code == 400
    far = (datetime.now(UTC) + timedelta(days=120)).date().isoformat()
    assert browser.post(url, data={"until": far}).status_code == 400
    assert browser.post(url, data={"until": soon}).status_code == 200


def test_unlinking_google_needs_a_password_to_fall_back_on(site, db, org):
    from app.core.db.models.user_identity import UserIdentity

    _, browser = site
    _signed_in(browser)
    admin = _admin_of(db, org)
    url = f"/organisations/{org.id}/users/{admin.id}/google"
    assert browser.post(url).status_code == 400  # nothing linked
    with unscoped():
        db.add(
            UserIdentity(
                org_id=org.id, user_id=admin.id, provider="google", subject=uuid4().hex, email_at_link=admin.email
            )
        )
        original, admin.password_hash = admin.password_hash, ""
        db.commit()
    refused = browser.post(url)
    assert refused.status_code == 400 and "Reset their password first" in refused.get_data(as_text=True)
    with unscoped():
        admin.password_hash = original
        db.commit()
    assert "Unlink Google" in browser.get(f"/organisations/{org.id}/users/{admin.id}").get_data(as_text=True)
    assert browser.post(url).status_code == 200
    with unscoped():
        assert db.query(UserIdentity).filter(UserIdentity.user_id == admin.id).count() == 0


def test_forgetting_remembered_devices(site, db, org):
    from datetime import UTC, datetime, timedelta

    from app.core.db.models.trusted_device import TrustedDevice

    _, browser = site
    _signed_in(browser)
    admin = _admin_of(db, org)
    with unscoped():
        db.add(
            TrustedDevice(
                org_id=org.id,
                user_id=admin.id,
                device_token=uuid4().hex,
                device_fingerprint="fp",
                expires_at=datetime.now(UTC) + timedelta(days=30),
            )
        )
        db.commit()
    assert ops.remembered_devices(db, admin) == 1
    response = browser.post(f"/organisations/{org.id}/users/{admin.id}/devices")
    assert response.status_code == 200 and "Forgot 1 remembered device " in response.get_data(as_text=True)
    assert ops.remembered_devices(db, admin) == 0


def test_disconnecting_xero_invalidates_the_stored_connection(site, db, org):
    from app.core.utils.time import utc_now
    from app.features.crm.models.xero_tenant import XeroTenant

    _, browser = site
    _signed_in(browser)
    url = f"/organisations/{org.id}/xero"
    assert browser.post(url).status_code == 400  # not connected
    with unscoped():
        db.add(
            XeroTenant(org_id=org.id, xero_tenant_id=uuid4().hex, xero_tenant_name="Demo Co", connected_at=utc_now())
        )
        db.commit()
    assert "Disconnect Xero" in browser.get(f"/organisations/{org.id}").get_data(as_text=True)
    assert browser.post(url).status_code == 200
    db.expire_all()
    assert ops.organisation_overview(db, org.id)["xero_name"] is None
    with unscoped():
        db.query(XeroTenant).filter(XeroTenant.org_id == org.id).delete(synchronize_session=False)
        db.commit()


def test_needs_attention_finds_who_is_stuck(site, db, org):
    from datetime import UTC, datetime, timedelta

    from click.testing import CliRunner

    from app.cli import cli
    from app.core.db.repositories.user_repo import UserRepository

    _, browser = site
    _signed_in(browser)
    past = datetime.now(UTC) - timedelta(days=1)
    locked, _ = ops.create_user(
        db, org.id, email=f"{uuid4().hex}@example.test", password="a-long-test-password", actor="test"
    )
    lapsed, _ = ops.create_user(db, org.id, email=f"{uuid4().hex}@example.test", actor="test")
    ended, _ = ops.create_user(
        db, org.id, email=f"{uuid4().hex}@example.test", password="a-long-test-password", actor="test"
    )
    with unscoped():
        UserRepository(db).lock_account(locked.id, 30)
        lapsed.invite_expires_at = past
        ended.access_expires_at = past
        db.commit()

    def emails(key):
        return {user.email for user, _ in ops.needs_attention(db, limit=5000)[key][0]}

    assert locked.email in emails("locked") and lapsed.email in emails("invite_expired")
    assert ended.email in emails("access_expired")
    assert org.id not in {o.id for o in ops.needs_attention(db, limit=5000)["no_admin"][0]}

    # Its only admin deactivated directly (the site refuses to do this): now it has none.
    with unscoped():
        _admin_of(db, org).is_active = False
        db.commit()
    assert org.id in {o.id for o in ops.needs_attention(db, limit=5000)["no_admin"][0]}

    page = browser.get("/attention")
    assert page.status_code == 200 and "Locked out" in page.get_data(as_text=True)
    listed = CliRunner().invoke(cli, ["needs-attention"])
    assert listed.exit_code == 0 and "Locked out:" in listed.output and "No admin who can sign in:" in listed.output


def test_a_persons_history_is_only_theirs(site, db, org):
    from app.core.db.repositories.audit_repo import AuditRepository

    _, browser = site
    _signed_in(browser)
    admin = _admin_of(db, org)
    other, _ = ops.create_user(
        db, org.id, email=f"{uuid4().hex}@example.test", password="a-long-test-password", actor="test"
    )
    with unscoped():
        AuditRepository(db).write_log(org_id=org.id, user_id=other.id, action="login", entity="user")
    ops.unlock_user(db, org.id, admin.id, actor=JOHNNY)
    entries, total = ops.list_audit(db, org.id, user_id=admin.id)
    assert total == 1 and entries[0][0].action == "platform_admin.unlock"
    page = browser.get(f"/organisations/{org.id}/audit", query_string={"user": str(admin.id)}).get_data(as_text=True)
    assert "unlock" in page and "Show everyone" in page
    assert "Recent history" in browser.get(f"/organisations/{org.id}/users/{admin.id}").get_data(as_text=True)
    assert browser.get(f"/organisations/{org.id}/audit", query_string={"user": str(uuid4())}).status_code == 404


# ── Backup codes, notes and documents ──────────────────────────────────────────


def test_staff_can_read_out_backup_codes_and_each_look_is_audited(site, db, org):
    from click.testing import CliRunner

    from app.cli import admin as cli_admin
    from app.core.db.repositories.backup_code_repo import BackupCodeRepository

    _, browser = site
    _signed_in(browser)
    admin = _admin_of(db, org)
    url = f"/organisations/{org.id}/users/{admin.id}/backup-codes"
    assert browser.post(url).status_code == 400  # 2FA is off
    with unscoped():
        admin.totp_secret, admin.two_factor_enabled = "JBSWY3DPEHPK3PXP", True
        db.commit()
    assert "Reset their 2FA instead" in browser.post(url).get_data(as_text=True)  # on, but no codes
    with unscoped():
        codes = BackupCodeRepository(db).generate_and_store_codes(org.id, admin.id, commit=True)
        assert BackupCodeRepository(db).verify_and_consume_code(admin.id, codes[0])
        db.commit()

    response = browser.post(url)
    page = response.get_data(as_text=True)
    assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
    assert all(code in page for code in codes) and page.count("admin-codes__used") == 1
    assert not any(
        code in browser.get(f"/organisations/{org.id}/users/{admin.id}").get_data(as_text=True) for code in codes
    )
    with unscoped():
        looks = db.query(AuditLog).filter(
            AuditLog.org_id == org.id, AuditLog.action == "platform_admin.view_backup_codes"
        )
        assert looks.count() == 1 and looks.one().meta_data["platform_admin"] == JOHNNY
        assert not any(code in str(looks.one().meta_data) for code in codes)

    listed = CliRunner().invoke(cli_admin.get_backup_codes, ["--user-id", str(admin.id)])
    assert listed.exit_code == 0 and codes[1] in listed.output and "Available: 9" in listed.output


def test_backup_codes_need_the_key_in_production(db, org, monkeypatch):
    admin = _admin_of(db, org)
    with unscoped():
        admin.two_factor_enabled = True
        db.commit()
    monkeypatch.delenv("BACKUP_CODE_ENCRYPTION_KEY", raising=False)
    monkeypatch.setattr(config, "environment", "prod")
    with pytest.raises(ops.AdminOperationError, match="backup-code key"):
        ops.get_backup_codes(db, org.id, admin.id, actor="test")


def test_notes_are_kept_with_their_author_and_stay_internal(site, db, org):
    _, browser = site
    _signed_in(browser)
    url = f"/organisations/{org.id}/notes"
    assert browser.post(url, data={"body": "   "}).status_code == 400
    body = "Spoke to Sam.\nWaiting on <b>their</b> accountant."
    assert browser.post(url, data={"body": body}).status_code == 200
    note = ops.list_notes(db, org.id)[0]
    assert (note.body, note.author_email) == (body, JOHNNY)
    page = browser.get(f"/organisations/{org.id}").get_data(as_text=True)
    assert "Waiting on &lt;b&gt;their&lt;/b&gt; accountant." in page and JOHNNY in page
    # Internal: nothing about notes reaches the organisation's own audit log.
    with unscoped():
        assert db.query(AuditLog).filter(AuditLog.org_id == org.id, AuditLog.entity.like("%note%")).count() == 0
    assert browser.post(f"{url}/{note.id}/delete").status_code == 200
    assert ops.list_notes(db, org.id) == []
    assert browser.post(f"{url}/{note.id}/delete").status_code == 400


def test_documents_upload_download_and_delete(site, db, org, tmp_path, monkeypatch):
    import io

    monkeypatch.setenv("ADMIN_DOCUMENTS_ROOT", str(tmp_path))
    _, browser = site
    _signed_in(browser)
    url = f"/organisations/{org.id}/documents"
    content = b"%PDF-1.7 a signed contract"

    def upload(data, name, **fields):
        return browser.post(url, data={"file": (io.BytesIO(data), name), **fields}, content_type="multipart/form-data")

    assert upload(content, "../../Signed contract.pdf", title="Contract 2026").status_code == 200
    document = ops.list_documents(db, org.id)[0]
    assert (document.title, document.original_filename, document.size_bytes) == (
        "Contract 2026",
        "Signed contract.pdf",
        len(content),
    )
    assert document.uploaded_by == JOHNNY and (tmp_path / str(org.id) / document.stored_name).read_bytes() == content
    assert [path.name for path in tmp_path.rglob("*") if path.is_file()] == [document.stored_name]

    download = browser.get(f"{url}/{document.id}")
    assert download.data == content and download.mimetype == "application/octet-stream"
    assert "attachment" in download.headers["Content-Disposition"]
    assert download.headers["X-Content-Type-Options"] == "nosniff"

    assert browser.post(f"{url}/{document.id}/delete").status_code == 200
    assert ops.list_documents(db, org.id) == [] and not list(tmp_path.rglob("*.pdf"))
    assert browser.get(f"{url}/{document.id}").status_code == 404


@pytest.mark.parametrize(
    "data,name",
    [
        (b"<script>alert(1)</script>", "page.html"),
        (b"MZ\x90\x00", "setup.exe"),
        (b"<html>not a pdf</html>", "contract.pdf"),
        (b"", "empty.txt"),
        (b"binary\x00data", "notes.txt"),
        (b"%PDF-1.7", ""),
    ],
)
def test_documents_that_are_not_what_they_claim_are_refused(site, db, org, tmp_path, monkeypatch, data, name):
    import io

    monkeypatch.setenv("ADMIN_DOCUMENTS_ROOT", str(tmp_path))
    _, browser = site
    _signed_in(browser)
    response = browser.post(
        f"/organisations/{org.id}/documents",
        data={"file": (io.BytesIO(data), name)},
        content_type="multipart/form-data",
    )
    assert response.status_code == 400
    assert ops.list_documents(db, org.id) == [] and not [p for p in tmp_path.rglob("*") if p.is_file()]


def test_documents_are_limited_in_size_and_other_forms_stay_small(site, db, org, tmp_path, monkeypatch):
    import io

    from app.admin_site import documents

    monkeypatch.setenv("ADMIN_DOCUMENTS_ROOT", str(tmp_path))
    monkeypatch.setattr(documents, "MAX_BYTES", 1024)
    _, browser = site
    _signed_in(browser)
    too_big = browser.post(
        f"/organisations/{org.id}/documents",
        data={"file": (io.BytesIO(b"%PDF" + b"x" * 2048), "big.pdf")},
        content_type="multipart/form-data",
    )
    assert too_big.status_code == 400 and not [p for p in tmp_path.rglob("*") if p.is_file()]
    assert browser.post(f"/organisations/{org.id}/notes", data={"body": "x" * 100_000}).status_code == 413


def test_a_document_belongs_to_one_organisation(site, db, org, created, tmp_path, monkeypatch):
    import io

    monkeypatch.setenv("ADMIN_DOCUMENTS_ROOT", str(tmp_path))
    _, browser = site
    _signed_in(browser)
    other_name = f"Admin site test {uuid4().hex[:12]}"
    created.append(other_name)
    other, _, _ = ops.create_organisation(db, name=other_name, admin_email=f"{uuid4().hex}@example.test", actor="test")
    document = ops.add_document(db, other.id, io.BytesIO(b"%PDF-1.7"), "theirs.pdf", actor="test")
    assert browser.get(f"/organisations/{org.id}/documents/{document.id}").status_code == 404
    assert browser.post(f"/organisations/{org.id}/documents/{document.id}/delete").status_code == 400
    assert ops.get_document(db, other.id, document.id)[0].id == document.id


def test_production_refuses_to_store_documents_without_a_volume(monkeypatch):
    from app.admin_site import documents

    monkeypatch.delenv("ADMIN_DOCUMENTS_ROOT", raising=False)
    monkeypatch.setattr(config, "environment", "prod")
    with pytest.raises(documents.DocumentError):
        documents.storage_root()


def test_notes_and_documents_from_the_cli(db, org, tmp_path, monkeypatch):
    from click.testing import CliRunner

    from app.cli import cli

    monkeypatch.setenv("ADMIN_DOCUMENTS_ROOT", str(tmp_path / "store"))
    runner, target = CliRunner(), ["--org-id", str(org.id)]
    assert runner.invoke(cli, ["add-note", *target, "--note", "Renewal due in March"]).exit_code == 0
    assert "Renewal due in March" in runner.invoke(cli, ["org-notes", *target]).output
    source = tmp_path / "contract.pdf"
    source.write_bytes(b"%PDF-1.7 contract")
    added = runner.invoke(cli, ["add-document", *target, "--file", str(source), "--title", "Contract"])
    assert added.exit_code == 0, added.output
    listed = runner.invoke(cli, ["org-documents", *target]).output
    assert "Contract" in listed and "contract.pdf" in listed
    document = ops.list_documents(db, org.id)[0]
    assert runner.invoke(cli, ["delete-document", *target, "--document-id", str(document.id)]).exit_code == 0
    assert runner.invoke(cli, ["delete-document", *target, "--document-id", str(document.id)]).exit_code == 1
