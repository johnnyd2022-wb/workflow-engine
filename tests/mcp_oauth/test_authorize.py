"""AC4-AC6: /oauth/authorize, sign-in hand-off and the consent page."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pyotp
import pytest

from app.core.db.models.org_role import OrgRole
from app.core.db.models.user import User, UserRole
from app.features.mcp_oauth.models import OAuthAuthorizationCode, OAuthGrant
from tests.mcp_oauth.conftest import PASSWORD
from tests.mcp_oauth.support import (
    REDIRECT,
    RESOURCE,
    authorize_params,
    authorize_url,
    pkce_pair,
    redirect_params,
)


def _consent_form(world, who="admin", **overrides):
    """GET the consent page as ``who`` and return (session, params, response)."""
    verifier, challenge = pkce_pair()
    params = authorize_params(world.client_row.client_id, challenge, **overrides)
    session = world.session(who)
    resp = session.get(authorize_url(params))
    return session, params, resp, verifier


# --- AC4 ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides,error",
    [
        ({"code_challenge": None, "code_challenge_method": None}, "invalid_request"),
        ({"code_challenge_method": None}, "invalid_request"),
        ({"code_challenge_method": "plain"}, "invalid_request"),
        ({"code_challenge": "short"}, "invalid_request"),
        ({"response_type": "token"}, "unsupported_response_type"),
        ({"scope": "bize.write"}, "invalid_scope"),
        ({"scope": "bize.read admin"}, "invalid_scope"),
        ({"resource": "https://elsewhere.example.test/mcp"}, "invalid_target"),
        ({"resource": None}, "invalid_target"),
    ],
)
def test_ac4_a_bad_protocol_parameter_redirects_with_an_error_and_the_same_state(world, overrides, error):
    session, params, resp, _ = _consent_form(world, **overrides)
    assert resp.status_code == 302
    location = resp.headers["Location"]
    assert location.startswith(REDIRECT + "?")
    got = redirect_params(resp)
    assert got["error"] == error
    assert got["state"] == "state-123"
    assert "code" not in got


def test_ac4_the_error_redirect_also_happens_when_signed_out(world):
    _verifier, challenge = pkce_pair()
    params = authorize_params(world.client_row.client_id, challenge, code_challenge_method="plain")
    resp = world.anon().get(authorize_url(params))
    assert resp.status_code == 302
    assert redirect_params(resp)["error"] == "invalid_request"


def test_ac4_an_unknown_redirect_uri_shows_an_error_page_and_never_redirects(world):
    session, params, resp, _ = _consent_form(world, redirect_uri="https://attacker.example.test/steal")
    assert resp.status_code == 400
    assert "Location" not in resp.headers
    assert resp.mimetype == "text/html"


@pytest.mark.parametrize(
    "redirect_uri", [None, REDIRECT + "/", REDIRECT + "?x=1", "https://assistant.example.test/Callback"]
)
def test_ac4_redirect_uri_must_match_a_registered_one_exactly(world, redirect_uri):
    session, params, resp, _ = _consent_form(world, redirect_uri=redirect_uri)
    assert resp.status_code == 400
    assert "Location" not in resp.headers


def test_ac4_an_unknown_client_shows_an_error_page_and_never_redirects(world):
    _verifier, challenge = pkce_pair()
    resp = world.session("admin").get(authorize_url(authorize_params("no-such-client", challenge)))
    assert resp.status_code == 400
    assert "Location" not in resp.headers


def test_ac4_an_error_for_a_bad_client_never_redirects_even_signed_out(world):
    _verifier, challenge = pkce_pair()
    resp = world.anon().get(authorize_url(authorize_params("no-such-client", challenge)))
    assert resp.status_code == 400
    assert "Location" not in resp.headers


def test_ac4_the_error_page_does_not_reflect_markup(world):
    _verifier, challenge = pkce_pair()
    resp = world.session("admin").get(
        authorize_url(authorize_params("<script>alert(1)</script>", challenge, redirect_uri="<img src=x>"))
    )
    assert resp.status_code == 400
    assert b"<script>alert(1)</script>" not in resp.data
    assert b"<img src=x>" not in resp.data


# --- AC5 ----------------------------------------------------------------------------------------


def _landing_page(path):
    """The sign-in page lives on app.app (the top-level pages), not on create_app()."""
    import app.app as app_module

    client = app_module.app.test_client()
    client.environ_base["wsgi.url_scheme"] = "https"
    client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
    return client.get(path)


def test_ac5_signed_out_authorize_lands_on_login_and_returns_to_consent_after_password_and_2fa(world, db):
    user = world.users["member"]
    secret = pyotp.random_base32()
    db.get(User, user.id).totp_secret = secret
    db.get(User, user.id).two_factor_enabled = True
    db.commit()

    _verifier, challenge = pkce_pair()
    params = authorize_params(world.client_row.client_id, challenge)
    original = authorize_url(params)
    browser = world.anon()

    hop = browser.get(original)
    assert hop.status_code == 302
    location = hop.headers["Location"]
    parsed = urlparse(location)
    assert parsed.path == "/"
    query = parse_qs(parsed.query)
    assert query == {"login": ["1"]}  # 8.2h: the request waits in the session, never in the URL

    landing = _landing_page(location)
    assert landing.status_code == 200
    assert b"loginModal" in landing.data  # the normal sign-in page

    login = browser.post("/auth/login", json={"email": user.email, "password": PASSWORD})
    assert login.status_code == 200
    assert login.get_json() == {"requires_2fa": True}
    verified = browser.post("/auth/verify-2fa", json={"token": pyotp.TOTP(secret).now()})
    assert verified.status_code == 200

    assert verified.get_json()["next"].startswith("/oauth/authorize?")
    consent = browser.get(verified.get_json()["next"])
    assert consent.status_code == 200
    html = consent.get_data(as_text=True)
    assert 'value="approve"' in html
    assert world.client_row.client_name in html


# --- AC6 ----------------------------------------------------------------------------------------


def _approve(session, params, **extra):
    data = {**params, "decision": "approve", "access_level": "read", **extra}
    return session.post("/oauth/authorize", data=data)


def test_ac6_consent_with_org_mcp_off_shows_the_message_and_no_approve_button(world, db):
    world.enable(enabled=False)
    session, params, resp, _ = _consent_form(world)
    assert resp.status_code == 403
    html = resp.get_data(as_text=True)
    assert "Your organisation hasn&#39;t turned on AI assistant access" in html or (
        "Your organisation hasn't turned on AI assistant access" in html
    )
    assert "An admin can turn it on in Settings." in html
    assert 'value="approve"' not in html
    assert "Approve" not in html
    posted = _approve(session, params)
    assert posted.status_code == 403
    assert "Location" not in posted.headers
    db.expire_all()
    assert db.query(OAuthGrant).filter_by(org_id=world.org.id).count() == 0
    assert db.query(OAuthAuthorizationCode).filter_by(org_id=world.org.id).count() == 0


def test_ac6_consent_when_the_users_role_is_not_allowed_is_blocked(world, db):
    world.enable(roles=["admin", "member"])  # sales is not ticked
    session, params, resp, _ = _consent_form(world, who="sales")
    assert resp.status_code == 403
    html = resp.get_data(as_text=True)
    assert "can&#39;t use AI assistant access" in html or "can't use AI assistant access" in html
    assert "Ask an admin." in html
    assert 'value="approve"' not in html
    posted = _approve(session, params)
    assert posted.status_code == 403
    db.expire_all()
    assert db.query(OAuthGrant).filter_by(org_id=world.org.id).count() == 0


def test_ac6_a_custom_role_is_allowed_by_its_custom_key_not_its_base_role(world, db):
    role = OrgRole(org_id=world.org.id, name="Bottling lead", base_role="production", permissions=["production.view"])
    db.add(role)
    db.commit()
    user = world.add_user(UserRole.PRODUCTION)
    db.get(User, user.id).custom_role_id = role.id
    db.commit()
    # builtin:production is ticked, the custom key is not: the custom role is what counts.
    world.enable(roles=["admin", "production"])
    session = world.session(user=user)
    _v, challenge = pkce_pair()
    params = authorize_params(world.client_row.client_id, challenge)
    assert session.get(authorize_url(params)).status_code == 403
    world.enable(roles=["admin"], extra_keys=[f"custom:{role.id}"])
    assert session.get(authorize_url(params)).status_code == 200


def test_ac6_a_disabled_client_is_blocked(world, db):
    row = world.client_row
    from datetime import UTC, datetime

    row.disabled_at = datetime.now(UTC)
    db.commit()
    session, params, resp, _ = _consent_form(world)
    assert resp.status_code == 403
    assert 'value="approve"' not in resp.get_data(as_text=True)
    assert _approve(session, params).status_code == 403


# --- the consent page and its decisions ---------------------------------------------------------


def test_the_consent_page_names_the_client_org_user_and_read_only_access(world):
    session, params, resp, _ = _consent_form(world, who="member")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert world.client_row.client_name in html
    assert "Unverified app" in html
    assert "assistant.example.test" in html  # the redirect host
    assert world.org.name in html
    assert world.users["member"].email in html
    assert "Read only" in html
    assert "Read and write" in html and "Coming later" in html
    assert 'value="read"' in html and "checked" in html
    # the write option is shown but cannot be chosen
    write = html[html.index('value="write"') - 200 : html.index('value="write"') + 200]
    assert "disabled" in write
    assert resp.headers["Cache-Control"].startswith("no-store")
    assert resp.headers["X-Frame-Options"] == "DENY"


def test_a_verified_client_is_not_labelled_unverified(world, db):
    world.client_row.verified = True
    db.commit()
    _s, _p, resp, _ = _consent_form(world)
    assert "Unverified app" not in resp.get_data(as_text=True)


def test_the_consent_page_lists_only_what_the_users_own_role_can_read(world):
    sales = _consent_form(world, who="sales")[2].get_data(as_text=True)
    assert "customers, invoices and revenue" in sales
    assert "stock on hand" in sales
    assert "costs" not in sales.lower().replace("costs.view", "")
    assert "workflows, batches" not in sales
    admin = _consent_form(world, who="admin")[2].get_data(as_text=True)
    for phrase in (
        "customers, invoices and revenue",
        "stock on hand",
        "workflows, batches",
        "compliance checks",
        "costs",
    ):
        assert phrase in admin
    # Write-ish permissions and people/settings are never listed as something an assistant gets.
    assert "Invite and remove people" not in admin
    assert "Maintenance actions" not in admin


def test_the_consent_page_escapes_a_hostile_client_name(world, db):
    world.client_row.client_name = 'MCPTEST <script>alert("x")</script>'
    db.commit()
    html = _consent_form(world)[2].get_data(as_text=True)
    assert '<script>alert("x")</script>' not in html
    assert "&lt;script&gt;" in html


def test_approve_redirects_with_a_code_and_the_state_and_creates_one_grant(world, db):
    session, params, _resp, _ = _consent_form(world, who="member")
    resp = _approve(session, params)
    assert resp.status_code == 302
    got = redirect_params(resp)
    assert resp.headers["Location"].startswith(REDIRECT + "?")
    assert got["state"] == "state-123"
    assert got["code"].startswith("bzc_")
    db.expire_all()
    grants = db.query(OAuthGrant).filter_by(org_id=world.org.id).all()
    assert len(grants) == 1
    assert grants[0].user_id == world.users["member"].id
    assert grants[0].scope == "bize.read"
    assert grants[0].resource == RESOURCE
    codes = db.query(OAuthAuthorizationCode).filter_by(org_id=world.org.id).all()
    assert len(codes) == 1
    assert codes[0].code_hash != got["code"]  # hashed, never the raw code
    assert got["code"] not in codes[0].code_hash


def test_approving_twice_for_the_same_client_keeps_one_live_grant(world, db):
    session, params, _resp, _ = _consent_form(world, who="member")
    assert _approve(session, params).status_code == 302
    assert _approve(session, params).status_code == 302
    db.expire_all()
    live = db.query(OAuthGrant).filter_by(org_id=world.org.id, revoked_at=None).count()
    assert live == 1


def test_deny_redirects_with_access_denied_and_the_state_and_makes_nothing(world, db):
    session, params, _resp, _ = _consent_form(world)
    resp = session.post("/oauth/authorize", data={**params, "decision": "deny", "access_level": "read"})
    assert resp.status_code == 302
    got = redirect_params(resp)
    assert got["error"] == "access_denied"
    assert got["state"] == "state-123"
    db.expire_all()
    assert db.query(OAuthGrant).filter_by(org_id=world.org.id).count() == 0


def test_the_decision_is_revalidated_so_a_tampered_redirect_uri_never_redirects(world):
    session, params, _resp, _ = _consent_form(world)
    tampered = {**params, "redirect_uri": "https://attacker.example.test/steal"}
    resp = _approve(session, tampered)
    assert resp.status_code == 400
    assert "Location" not in resp.headers


def test_read_and_write_cannot_be_approved(world, db):
    session, params, _resp, _ = _consent_form(world)
    resp = session.post("/oauth/authorize", data={**params, "decision": "approve", "access_level": "write"})
    assert resp.status_code in {400, 302}
    if resp.status_code == 302:
        assert redirect_params(resp)["error"] in {"invalid_scope", "invalid_request"}
    db.expire_all()
    assert db.query(OAuthGrant).filter_by(org_id=world.org.id).count() == 0


def test_the_consent_form_is_csrf_protected(world, flask_app, monkeypatch, db):
    session, params, resp, _ = _consent_form(world)
    html = resp.get_data(as_text=True)
    assert 'name="csrf_token"' in html
    monkeypatch.setitem(flask_app.config, "WTF_CSRF_ENABLED", True)
    rejected = _approve(session, params)
    assert rejected.status_code in {400, 401}
    assert "Location" not in rejected.headers
    db.expire_all()
    assert db.query(OAuthGrant).filter_by(org_id=world.org.id).count() == 0


def test_the_consent_form_works_with_csrf_on_when_it_sends_its_token_and_referer(world, flask_app, monkeypatch):
    """What the browser does: CSRF is enforced and Flask-WTF also wants a same-origin Referer on HTTPS."""
    import re

    session, params, resp, _ = _consent_form(world)
    html = resp.get_data(as_text=True)
    token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
    # The page tells the browser to send the Referer to its own site, and to nobody else.
    assert resp.headers["Referrer-Policy"] == "same-origin"
    assert '<meta name="referrer" content="same-origin">' in html
    monkeypatch.setitem(flask_app.config, "WTF_CSRF_ENABLED", True)
    posted = session.post(
        "/oauth/authorize",
        data={**params, "decision": "approve", "access_level": "read", "csrf_token": token},
        headers={"Referer": "https://localhost/oauth/authorize"},
    )
    assert posted.status_code == 302
    assert redirect_params(posted)["code"].startswith("bzc_")
    assert posted.headers["Referrer-Policy"] == "same-origin"


def test_the_authorize_endpoints_cannot_be_reached_by_a_bearer_token(world):
    from tests.mcp_oauth.support import bearer, mint_grant

    _g, access, _r = mint_grant(world.db, world.users["admin"], world.client_row)
    _v, challenge = pkce_pair()
    url = authorize_url(authorize_params(world.client_row.client_id, challenge))
    resp = world.anon().get(url, headers=bearer(access))
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "insufficient_scope"
    posted = world.anon().post("/oauth/authorize", data={"decision": "approve"}, headers=bearer(access))
    assert posted.status_code == 403


def test_a_signed_in_user_without_the_2fa_enrolment_they_owe_does_not_reach_consent(world, db, flask_app):
    flask_app.config["REQUIRE_ADMIN_2FA"] = True
    try:
        session = world.anon()
        assert (
            session.post("/auth/login", json={"email": world.users["admin"].email, "password": PASSWORD}).status_code
            == 200
        )
        _v, challenge = pkce_pair()
        resp = session.get(
            authorize_url(authorize_params(world.client_row.client_id, challenge)), headers={"Accept": "text/html"}
        )
        assert resp.status_code == 302
        assert "enroll2fa=1" in resp.headers["Location"]
    finally:
        flask_app.config["REQUIRE_ADMIN_2FA"] = False
