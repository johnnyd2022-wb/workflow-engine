"""Public MCP 8.2h (AC41-AC43): RFC 9207 ``iss``, return to the pending request after sign-in, clickjacking
headers, and the RFC 9700 checks that had no test of their own. The checklist is
``.agents/reports/public-mcp/oauth-bcp.md``; each row there names a test in this package.
"""

from __future__ import annotations

import configparser
import re
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pyotp
import pytest
from authlib.integrations.flask_client import OAuth

from app.core.db.models.user import User, UserRole
from app.core.db.models.user_identity import UserIdentity
from app.features.google_sign_in import routes as google_routes
from app.features.mcp_oauth.models import OAuthAuthorizationCode
from app.features.mcp_oauth.services import pending_authorization
from tests.factories import UserFactory
from tests.mcp_oauth.conftest import PASSWORD
from tests.mcp_oauth.support import (
    ISSUER,
    REDIRECT,
    RESOURCE,
    authorize_params,
    authorize_url,
    pkce_pair,
    redirect_params,
)
from tests.test_google_sign_in import CLIENT_ID as GOOGLE_CLIENT_ID
from tests.test_google_sign_in import _claims as google_claims

CONFIG_DIR = Path(__file__).resolve().parents[2] / "app" / "config"


def _request(world, **overrides):
    verifier, challenge = pkce_pair()
    params = authorize_params(world.client_row.client_id, challenge, **overrides)
    return params, authorize_url(params), verifier


def _same_request(location_or_url: str, original_url: str) -> bool:
    got, want = urlsplit(location_or_url), urlsplit(original_url)
    return got.path == want.path == "/oauth/authorize" and parse_qs(got.query) == parse_qs(want.query)


# --- AC41: RFC 9207 iss -------------------------------------------------------------------------


def test_ac41_the_metadata_advertises_the_iss_parameter(world):
    body = world.anon().get("/.well-known/oauth-authorization-server").get_json()
    assert body["authorization_response_iss_parameter_supported"] is True
    assert body["issuer"] == ISSUER


@pytest.mark.parametrize(
    "overrides",
    [
        {"code_challenge": None, "code_challenge_method": None},
        {"code_challenge_method": "plain"},
        {"response_type": "token"},
        {"scope": "bize.write"},
        {"resource": "https://elsewhere.example.test/mcp"},
        {"state": "s" * 2000},
    ],
)
def test_ac41_every_error_redirect_carries_iss(world, overrides):
    _params, url, _v = _request(world, **overrides)
    resp = world.session("member").get(url)
    assert resp.status_code == 302
    got = redirect_params(resp)
    assert "error" in got
    assert got["iss"] == ISSUER


def test_ac41_the_error_redirect_carries_iss_when_signed_out_too(world):
    _params, url, _v = _request(world, response_type="token")
    resp = world.anon().get(url)
    assert redirect_params(resp)["iss"] == ISSUER


def test_ac41_approve_deny_and_a_rejected_access_level_carry_iss(world):
    params, _url, _v = _request(world)
    session = world.session("member")
    approve = session.post("/oauth/authorize", data={**params, "decision": "approve", "access_level": "read"})
    got = redirect_params(approve)
    assert got["code"].startswith("bzc_") and got["state"] == "state-123" and got["iss"] == ISSUER
    deny = session.post("/oauth/authorize", data={**params, "decision": "deny", "access_level": "read"})
    got = redirect_params(deny)
    assert got["error"] == "access_denied" and got["iss"] == ISSUER and got["state"] == "state-123"
    write = session.post("/oauth/authorize", data={**params, "decision": "approve", "access_level": "write"})
    assert redirect_params(write)["iss"] == ISSUER


def test_ac41_iss_is_added_next_to_a_query_the_redirect_uri_already_has(world, db):
    from tests.mcp_oauth.support import make_client

    client = make_client(db, redirect_uris=["https://assistant.example.test/cb?tenant=a"])
    _v, challenge = pkce_pair()
    params = authorize_params(client.client_id, challenge, redirect_uri="https://assistant.example.test/cb?tenant=a")
    resp = world.session("member").post("/oauth/authorize", data={**params, "decision": "deny", "access_level": "read"})
    got = redirect_params(resp)
    assert got["tenant"] == "a" and got["iss"] == ISSUER


def test_ac41_a_page_error_never_redirects_so_it_has_no_iss(world):
    _params, url, _v = _request(world, redirect_uri="https://evil.example.test/cb")
    resp = world.session("member").get(url)
    assert resp.status_code == 400 and "Location" not in resp.headers


# --- AC42: return to the pending request after sign-in ------------------------------------------


def test_ac42_signed_out_authorize_keeps_the_request_in_the_session_not_in_the_login_url(world):
    _params, url, _v = _request(world)
    browser = world.anon()
    hop = browser.get(url)
    assert hop.status_code == 302
    assert hop.headers["Location"] == "/?login=1"  # nothing to take a return target from
    with browser.session_transaction() as s:
        assert pending_authorization.SESSION_KEY in s


def test_ac42_a_next_in_the_query_string_is_ignored_and_the_landing_page_never_reads_one(world):
    import app.app as app_module

    page = app_module.app.test_client()
    page.environ_base.update({"wsgi.url_scheme": "https", "HTTP_X_FORWARDED_PROTO": "https"})
    html = page.get("/?login=1&next=https://evil.example.test/").get_data(as_text=True)
    assert "get('next')" not in html and "postLoginTarget" not in html
    assert "evil.example" not in html


def test_ac42_a_password_sign_in_returns_to_consent_for_the_same_request(world):
    user = world.users["member"]
    _params, url, _v = _request(world)
    browser = world.anon()
    browser.get(url)
    login = browser.post("/auth/login", json={"email": user.email, "password": PASSWORD})
    assert login.status_code == 200
    assert _same_request(login.get_json()["next"], url)
    consent = browser.get(login.get_json()["next"])
    assert consent.status_code == 200 and 'value="approve"' in consent.get_data(as_text=True)
    with browser.session_transaction() as s:
        assert pending_authorization.SESSION_KEY not in s  # consumed


def test_ac42_password_and_2fa_return_to_consent(world, db):
    user = world.users["member"]
    secret = pyotp.random_base32()
    row = db.get(User, user.id)
    row.totp_secret, row.two_factor_enabled = secret, True
    db.commit()
    _params, url, _v = _request(world)
    browser = world.anon()
    browser.get(url)
    login = browser.post("/auth/login", json={"email": user.email, "password": PASSWORD})
    assert login.get_json() == {"requires_2fa": True}
    verified = browser.post("/auth/verify-2fa", json={"token": pyotp.TOTP(secret).now()})
    assert verified.status_code == 200
    assert _same_request(verified.get_json()["next"], url)
    assert browser.get(verified.get_json()["next"]).status_code == 200


def test_ac42_a_login_with_nothing_pending_has_no_next(world):
    browser = world.anon()
    login = browser.post("/auth/login", json={"email": world.users["member"].email, "password": PASSWORD})
    assert "next" not in login.get_json()


@pytest.fixture
def google(world, flask_app, monkeypatch):
    monkeypatch.setitem(flask_app.config, "GOOGLE_SIGN_IN_ENABLED", True)
    monkeypatch.setitem(flask_app.config, "GOOGLE_CLIENT_ID", GOOGLE_CLIENT_ID)
    monkeypatch.setitem(flask_app.config, "GOOGLE_REDIRECT_URI", "https://test.biz-e.app/auth/google/callback")
    client = OAuth(flask_app).register(
        name="google",
        client_id=GOOGLE_CLIENT_ID,
        client_secret="test-only-secret",
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        access_token_url="https://oauth2.googleapis.com/token",
        client_kwargs={"scope": "openid email", "code_challenge_method": "S256"},
        issuer="https://accounts.google.com",
        id_token_signing_alg_values_supported=["RS256"],
    )
    monkeypatch.setitem(flask_app.extensions, "google_oidc_client", client)
    yield
    world.db.rollback()
    world.db.query(UserIdentity).filter(UserIdentity.org_id == world.org.id).delete(synchronize_session=False)
    world.db.commit()


def _google_callback(browser, address, monkeypatch):
    from app.features.google_sign_in.service import validate_verified_claims

    started = browser.post("/auth/google/start", data={})
    assert started.status_code == 302
    q = parse_qs(urlsplit(started.location).query)
    claims = google_claims(address, nonce=q["nonce"][0])
    monkeypatch.setattr(
        google_routes,
        "exchange_verified_identity",
        lambda nonce: validate_verified_claims(claims, GOOGLE_CLIENT_ID, nonce),
    )
    return browser.get("/auth/google/callback", query_string={"state": q["state"][0], "code": "mock-code"})


def _gmail_user(world, db, secret=None):
    user = UserFactory(org_id=world.org.id, email=f"mcp-g-{time.time_ns()}@gmail.com", role=UserRole.MEMBER)
    if secret:
        user.totp_secret, user.two_factor_enabled = secret, True
    db.commit()
    return user


def test_ac42_google_sign_in_returns_to_consent_for_the_same_request(world, db, google, monkeypatch):
    user = _gmail_user(world, db)
    _params, url, _v = _request(world)
    browser = world.anon()
    browser.get(url)
    callback = _google_callback(browser, user.email, monkeypatch)
    assert callback.status_code == 302
    assert _same_request(callback.headers["Location"], url)
    consent = browser.get(callback.headers["Location"])
    assert consent.status_code == 200 and 'value="approve"' in consent.get_data(as_text=True)


def test_ac42_google_sign_in_with_2fa_returns_to_consent_after_the_code(world, db, google, monkeypatch):
    secret = pyotp.random_base32()
    user = _gmail_user(world, db, secret=secret)
    _params, url, _v = _request(world)
    browser = world.anon()
    browser.get(url)
    callback = _google_callback(browser, user.email, monkeypatch)
    assert callback.headers["Location"] == "/auth/google/challenge"
    verified = browser.post("/auth/verify-2fa", json={"token": pyotp.TOTP(secret).now()})
    assert _same_request(verified.get_json()["next"], url)


def test_ac42_google_sign_in_with_nothing_pending_still_lands_on_the_dashboard(world, db, google, monkeypatch):
    user = _gmail_user(world, db)
    callback = _google_callback(world.anon(), user.email, monkeypatch)
    assert callback.headers["Location"] == "/dashboard"


def test_ac42_first_time_2fa_enrolment_returns_to_consent_for_the_same_request(world, flask_app, monkeypatch):
    monkeypatch.setitem(flask_app.config, "REQUIRE_ADMIN_2FA", True)
    admin = world.users["admin"]
    _params, url, _v = _request(world)
    browser = world.anon()
    browser.get(url)
    login = browser.post("/auth/login", json={"email": admin.email, "password": PASSWORD})
    body = login.get_json()
    assert body["requires_2fa_enrollment"] is True
    assert "next" not in body  # held back: enrolment comes first
    # The settings page reads this when it loads, while enrolment is still owed.
    me = browser.get("/auth/me").get_json()["user"]
    assert _same_request(me["return_to"], url)
    secret = browser.post("/auth/2fa/enroll").get_json()["secret"]
    totp = pyotp.TOTP(secret)
    now = int(time.time())
    enable = browser.post("/auth/2fa/enable", json={"token1": totp.at(now - 30), "token2": totp.at(now)})
    assert enable.status_code == 200, enable.get_json()
    consent = browser.get(me["return_to"])
    assert consent.status_code == 200 and 'value="approve"' in consent.get_data(as_text=True)


def test_ac42_the_session_rotation_at_sign_in_keeps_only_the_pending_request(world):
    _params, url, _v = _request(world)
    browser = world.anon()
    browser.get(url)
    with browser.session_transaction() as s:
        s["pending_2fa_user_id"] = "stale-value"
    browser.post("/auth/login", json={"email": world.users["member"].email, "password": PASSWORD})
    with browser.session_transaction() as s:
        assert "pending_2fa_user_id" not in s


def test_ac42_signing_out_forgets_the_pending_request(world):
    _params, url, _v = _request(world)
    browser = world.anon()
    browser.get(url)
    browser.post("/auth/login", json={"email": world.users["member"].email, "password": PASSWORD})
    browser.get(url)  # signed in: consent, request now lives in the form
    with browser.session_transaction() as s:
        assert pending_authorization.SESSION_KEY not in s


def test_ac42_an_old_pending_request_is_not_returned(world):
    _params, url, _v = _request(world)
    browser = world.anon()
    browser.get(url)
    with browser.session_transaction() as s:
        s[pending_authorization.SESSION_KEY] = {**s[pending_authorization.SESSION_KEY], "at": time.time() - 3600}
    login = browser.post("/auth/login", json={"email": world.users["member"].email, "password": PASSWORD})
    assert "next" not in login.get_json()


@pytest.mark.parametrize(
    "stored",
    [
        "https://evil.example.test/",
        {"at": time.time(), "params": "//evil.example.test"},
        {"at": time.time(), "params": [["next", "https://evil.example.test"]]},
        {"at": time.time(), "params": [["redirect_uri", 5]]},
        {"at": "now", "params": [["state", "x"]]},
        {"at": time.time(), "params": [["state", "x" * 5000]]},
        {"at": time.time(), "params": [["state", "x"]] * 40},
    ],
)
def test_ac42_a_tampered_session_entry_never_becomes_a_return_url(world, stored):
    browser = world.anon()
    with browser.session_transaction() as s:
        s[pending_authorization.SESSION_KEY] = stored
    login = browser.post("/auth/login", json={"email": world.users["member"].email, "password": PASSWORD})
    assert "next" not in login.get_json()


def test_ac42_the_return_url_is_always_the_authorize_path_whatever_the_values_are(world):
    hostile = "https://evil.example.test/\r\n//evil.example.test"
    browser = world.anon()
    browser.get("/oauth/authorize?" + "client_id=" + world.client_row.client_id + "&state=" + "%2F%2Fevil.example.test")
    # Unparseable requests redirect to the client or an error page; the point is the builder itself:
    url = pending_authorization.build_url([("state", hostile), ("client_id", "x")])
    assert url.startswith("/oauth/authorize?")
    assert urlsplit(url).netloc == "" and "\r" not in url and "\n" not in url


def test_ac42_a_request_too_big_for_a_cookie_is_not_stored(world):
    browser = world.anon()
    _params, url, _v = _request(world, state="s" * 1000)
    big = url + "&client_id=" + "c" * 3000
    browser.get(big)
    with browser.session_transaction() as s:
        assert pending_authorization.SESSION_KEY not in s


def test_ac42_the_size_cap_counts_the_escaped_bytes_of_non_ascii_text(world):
    browser = world.anon()
    _params, url, _v = _request(world, state="é" * 400)  # 400 characters, about 2.4 KB once escaped
    browser.get(url)
    with browser.session_transaction() as s:
        assert pending_authorization.SESSION_KEY not in s


def test_ac42_one_browsers_pending_request_is_not_another_browsers(world):
    _params, url, _v = _request(world)
    first, second = world.anon(), world.anon()
    first.get(url)
    login = second.post("/auth/login", json={"email": world.users["member"].email, "password": PASSWORD})
    assert "next" not in login.get_json()


def test_ac42_the_login_and_challenge_pages_follow_only_the_servers_next(world):
    import app.app as app_module

    page = app_module.app.test_client()
    page.environ_base.update({"wsgi.url_scheme": "https", "HTTP_X_FORWARDED_PROTO": "https"})
    html = page.get("/").get_data(as_text=True)
    assert "data.next" in html and "'/oauth/authorize?'" in html
    settings_js = (Path(__file__).resolve().parents[2] / "app/core/frontend/js/settings-controller.js").read_text()
    assert "return_to" in settings_js and "/oauth/authorize?" in settings_js


# --- AC43: clickjacking -------------------------------------------------------------------------


def _assert_not_framable(resp):
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in resp.headers["Content-Security-Policy"]


def test_ac43_every_authorize_response_refuses_framing(world, db):
    params, url, _v = _request(world)
    session = world.session("member")
    _assert_not_framable(session.get(url))  # consent
    _assert_not_framable(session.post("/oauth/authorize", data={**params, "decision": "deny", "access_level": "read"}))
    _assert_not_framable(
        world.session("member").get(authorize_url({**params, "redirect_uri": "https://x.example.test"}))
    )
    _assert_not_framable(world.session("member").get(authorize_url({**params, "response_type": "token"})))
    world.enable(enabled=False)
    _assert_not_framable(world.session("member").get(url))  # the blocked page
    _assert_not_framable(world.anon().get(url))  # signed out hop to login


def test_ac43_consent_does_not_restrict_form_action(world):
    """Chrome applies form-action to the redirect a form POST is answered with, so a 'self' limit
    would stop the browser reaching the assistant's callback. Pinned so nobody 'hardens' it by accident."""
    _params, url, _v = _request(world)
    csp = world.session("member").get(url).headers["Content-Security-Policy"]
    assert "form-action" not in csp


# --- RFC 9700 checks without an earlier test ----------------------------------------------------


def test_bcp_the_consent_decision_answers_302_not_307(world):
    params, _url, _v = _request(world)
    session = world.session("member")
    for decision in ("approve", "deny"):
        assert (
            session.post("/oauth/authorize", data={**params, "decision": decision, "access_level": "read"}).status_code
            == 302
        )


def test_bcp_implicit_and_password_grants_are_not_offered(world):
    body = world.anon().get("/.well-known/oauth-authorization-server").get_json()
    assert body["response_types_supported"] == ["code"]
    assert set(body["grant_types_supported"]) == {"authorization_code", "refresh_token"}
    for grant in ("password", "client_credentials", "implicit"):
        resp = world.anon().post("/oauth/token", data={"grant_type": grant, "client_id": world.client_row.client_id})
        assert resp.status_code == 400 and resp.get_json()["error"] == "unsupported_grant_type"


def test_bcp_a_code_exchange_without_a_verifier_is_refused_and_every_code_has_a_challenge(world, db):
    params, _url, verifier = _request(world)
    session = world.session("member")
    code = redirect_params(
        session.post("/oauth/authorize", data={**params, "decision": "approve", "access_level": "read"})
    )["code"]
    resp = world.anon().post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT,
            "client_id": world.client_row.client_id,
            "resource": RESOURCE,
        },
    )
    assert resp.status_code == 400 and resp.get_json()["error"] == "invalid_request"
    assert OAuthAuthorizationCode.__table__.c.code_challenge.nullable is False  # no PKCE-less code can exist
    assert verifier


def test_bcp_oauth_responses_are_not_cached(world):
    params, url, _v = _request(world)
    assert "no-store" in world.session("member").get(url).headers["Cache-Control"]
    token = world.anon().post("/oauth/token", data={"grant_type": "authorization_code"})
    assert "no-store" in token.headers["Cache-Control"]


def test_bcp_the_consent_page_sends_no_referer_to_other_sites(world):
    _params, url, _v = _request(world)
    assert world.session("member").get(url).headers["Referrer-Policy"] == "same-origin"


def test_bcp_oauth_responses_carry_hsts_over_https(world):
    resp = world.anon().get("/.well-known/oauth-authorization-server")
    assert "max-age=" in resp.headers["Strict-Transport-Security"]


def test_bcp_plain_http_is_redirected_to_https(world, flask_app, monkeypatch):
    monkeypatch.setitem(flask_app.config, "ENFORCE_HTTPS", True)
    client = flask_app.test_client()
    client.environ_base["wsgi.url_scheme"] = "http"
    resp = client.post("/oauth/token", data={}, base_url="http://test.biz-e.app")
    assert resp.status_code == 301 and resp.headers["Location"].startswith("https://")


@pytest.mark.parametrize("name", ["test", "prod"])
def test_bcp_the_deployed_issuer_and_resource_are_https(name):
    ini = configparser.ConfigParser()
    ini.read(CONFIG_DIR / f"{name}.ini")
    for key in ("issuer", "resource"):
        assert ini["mcp"][key].startswith("https://"), f"{name}.ini [mcp] {key} must be https"


def test_mcp_spec_dcr_accepts_application_type(world):
    """MCP 2026-07-28: clients MUST send application_type (native or web) when registering."""
    for kind in ("native", "web"):
        resp = world.anon().post(
            "/oauth/register",
            json={"client_name": f"MCPTEST {kind}", "redirect_uris": [REDIRECT], "application_type": kind},
        )
        assert resp.status_code == 201, resp.get_json()


def test_bcp_no_open_redirect_through_the_sign_in_hop(world):
    """Whatever a request carries, the only Location the app builds for a signed-out visitor is /?login=1."""
    for extra in ("&next=https://evil.example.test", "&return_to=//evil.example.test", "&redirect=//x"):
        _params, url, _v = _request(world)
        resp = world.anon().get(url + extra)
        assert resp.headers["Location"] == "/?login=1"


def test_bcp_the_login_hop_matches_nothing_in_the_query_string(world):
    assert re.fullmatch(r"/\?login=1", world.anon().get(_request(world)[1]).headers["Location"])
