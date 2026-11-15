"""AC7-AC10: the token endpoint, code and refresh-token rules, and what is logged."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import pytest

from app.features.mcp_oauth.models import OAuthAuthorizationCode, OAuthGrant, OAuthToken
from app.features.mcp_oauth.services.tokens import hash_token
from tests.mcp_oauth.support import (
    REDIRECT,
    RESOURCE,
    authorize_params,
    authorize_url,
    bearer,
    make_client,
    pkce_pair,
    redirect_params,
)


def connect(world, who="member", client=None, **overrides):
    """Sign in, open consent and approve. Returns (code, verifier, token_form)."""
    client = client or world.client_row
    verifier, challenge = pkce_pair()
    params = authorize_params(client.client_id, challenge, **overrides)
    session = world.session(who)
    assert session.get(authorize_url(params)).status_code == 200
    resp = session.post("/oauth/authorize", data={**params, "decision": "approve", "access_level": "read"})
    assert resp.status_code == 302, resp.get_data(as_text=True)[:300]
    code = redirect_params(resp)["code"]
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "code_verifier": verifier,
        "redirect_uri": REDIRECT,
        "client_id": client.client_id,
        "resource": RESOURCE,
    }
    return code, verifier, form


def token(world, form):
    return world.anon().post("/oauth/token", data=form)


# --- AC7 ----------------------------------------------------------------------------------------


def test_ac7_the_right_verifier_returns_a_bearer_pair_valid_for_an_hour(world):
    _code, _verifier, form = connect(world)
    resp = token(world, form)
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body["token_type"] == "Bearer"
    assert body["expires_in"] == 3600
    assert body["scope"] == "bize.read"
    assert body["access_token"].startswith("bza_")
    assert body["refresh_token"].startswith("bzr_")
    assert len(body["access_token"]) >= 40
    assert resp.headers["Cache-Control"] == "no-store"
    assert resp.headers["Pragma"] == "no-cache"
    assert "Set-Cookie" not in resp.headers


def test_ac7_the_stored_values_are_hashes_and_the_expiries_match_the_spec(world, db):
    _code, _verifier, form = connect(world)
    body = token(world, form).get_json()
    db.expire_all()
    rows = {t.kind: t for t in db.query(OAuthToken).filter_by(org_id=world.org.id).all()}
    assert rows["access"].token_hash == hash_token(body["access_token"])
    assert rows["refresh"].token_hash == hash_token(body["refresh_token"])
    assert body["access_token"] not in (rows["access"].token_hash, rows["refresh"].token_hash)
    now = datetime.now(UTC)
    assert timedelta(minutes=59) < rows["access"].expires_at - now <= timedelta(hours=1)
    assert timedelta(days=29, hours=23) < rows["refresh"].expires_at - now <= timedelta(days=30)
    used = db.query(OAuthAuthorizationCode).filter_by(org_id=world.org.id).one()
    assert used.used_at is not None


def test_ac7_a_wrong_verifier_is_invalid_grant_and_issues_nothing(world, db):
    _code, _verifier, form = connect(world)
    other_verifier, _ = pkce_pair()
    resp = token(world, {**form, "code_verifier": other_verifier})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "invalid_grant"
    db.expire_all()
    assert db.query(OAuthToken).filter_by(org_id=world.org.id).count() == 0
    # The real client can still finish: a stranger's bad guess does not burn the code.
    assert token(world, form).status_code == 200


def test_ac7_the_same_code_twice_is_invalid_grant_and_the_first_tokens_are_revoked(world, db):
    _code, _verifier, form = connect(world)
    first = token(world, form)
    assert first.status_code == 200
    access = first.get_json()["access_token"]
    me = world.anon().get("/api/core/mcp/me", headers=bearer(access))
    assert me.status_code == 200

    second = token(world, form)
    assert second.status_code == 400
    assert second.get_json()["error"] == "invalid_grant"

    again = world.anon().get("/api/core/mcp/me", headers=bearer(access))
    assert again.status_code == 401
    db.expire_all()
    grant = db.query(OAuthGrant).filter_by(org_id=world.org.id).one()
    assert grant.revoked_at is not None
    assert grant.revoked_reason == "code_reuse"
    assert all(t.revoked_at is not None for t in db.query(OAuthToken).filter_by(org_id=world.org.id))


@pytest.mark.parametrize(
    "change",
    [
        {"redirect_uri": "https://assistant.example.test/other"},
        {"client_id": "someone-else"},
        {"resource": "https://elsewhere.example.test/mcp"},
        {"code": "bzc_notacode"},
        {"code_verifier": None},
        {"code": None},
        {"grant_type": "password"},
        {"grant_type": None},
    ],
)
def test_ac7_every_binding_on_the_code_must_match(world, change):
    _code, _verifier, form = connect(world)
    bad = {**form, **change}
    bad = {k: v for k, v in bad.items() if v is not None}
    resp = token(world, bad)
    assert resp.status_code == 400
    assert resp.get_json()["error"] in {"invalid_grant", "invalid_request", "invalid_client", "unsupported_grant_type"}
    # None of those mismatches used the code up.
    assert token(world, form).status_code == 200


def test_ac7_a_code_for_one_client_cannot_be_redeemed_by_another(world, db):
    _code, _verifier, form = connect(world)
    thief = make_client(db)
    resp = token(world, {**form, "client_id": thief.client_id})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "invalid_grant"


def test_ac7_the_token_endpoint_needs_no_csrf_token_and_ignores_cookies(world, flask_app, monkeypatch):
    _code, _verifier, form = connect(world)
    monkeypatch.setitem(flask_app.config, "WTF_CSRF_ENABLED", True)
    session = world.session("admin")  # a browser session with a cookie is no help and no hindrance
    resp = session.post("/oauth/token", data=form)
    assert resp.status_code == 200


def test_ac7_errors_are_rfc6749_json_with_status_400(world):
    resp = token(world, {"grant_type": "authorization_code"})
    assert resp.status_code == 400
    assert resp.mimetype == "application/json"
    assert resp.get_json()["error"] == "invalid_request"
    assert resp.headers["Cache-Control"] == "no-store"


def test_ac7_the_token_endpoint_is_rate_limited_per_client_and_address(world):
    client = world.anon()
    form = {"grant_type": "authorization_code", "code": "bzc_x", "client_id": "rate-client"}
    statuses = [client.post("/oauth/token", data=form).status_code for _ in range(61)]
    assert statuses[:60] == [400] * 60
    assert statuses[60] == 429
    # Another client id from the same address has its own allowance.
    assert client.post("/oauth/token", data={**form, "client_id": "other-client"}).status_code == 400


# --- AC8 ----------------------------------------------------------------------------------------


def test_ac8_a_code_older_than_60_seconds_is_invalid_grant(world, db):
    _code, _verifier, form = connect(world)
    stored = db.query(OAuthAuthorizationCode).filter_by(org_id=world.org.id).one()
    assert timedelta(seconds=55) < stored.expires_at - datetime.now(UTC) <= timedelta(seconds=60)
    stored.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    resp = token(world, form)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "invalid_grant"
    db.expire_all()
    assert db.query(OAuthToken).filter_by(org_id=world.org.id).count() == 0


# --- AC9 ----------------------------------------------------------------------------------------


def test_ac9_refresh_rotates_the_token_and_reuse_revokes_the_grant(world, db):
    _code, _verifier, form = connect(world)
    first = token(world, form).get_json()
    refresh_form = {
        "grant_type": "refresh_token",
        "refresh_token": first["refresh_token"],
        "client_id": world.client_row.client_id,
    }

    second = token(world, refresh_form)
    assert second.status_code == 200, second.get_json()
    rotated = second.get_json()
    assert rotated["refresh_token"].startswith("bzr_")
    assert rotated["refresh_token"] != first["refresh_token"]
    assert rotated["access_token"] != first["access_token"]
    assert rotated["expires_in"] == 3600
    assert world.anon().get("/api/core/mcp/me", headers=bearer(rotated["access_token"])).status_code == 200

    db.expire_all()
    old = db.query(OAuthToken).filter_by(token_hash=hash_token(first["refresh_token"])).one()
    new = db.query(OAuthToken).filter_by(token_hash=hash_token(rotated["refresh_token"])).one()
    assert old.revoked_at is not None
    assert old.replaced_by_id == new.id

    reuse = token(world, refresh_form)
    assert reuse.status_code == 400
    assert reuse.get_json()["error"] == "invalid_grant"

    newest = world.anon().get("/api/core/mcp/me", headers=bearer(rotated["access_token"]))
    assert newest.status_code == 401
    db.expire_all()
    grant = db.query(OAuthGrant).filter_by(org_id=world.org.id).one()
    assert grant.revoked_at is not None
    assert grant.revoked_reason == "refresh_reuse"
    assert token(world, {**refresh_form, "refresh_token": rotated["refresh_token"]}).status_code == 400


def test_ac9_an_expired_refresh_token_is_invalid_grant(world, db):
    _code, _verifier, form = connect(world)
    first = token(world, form).get_json()
    row = db.query(OAuthToken).filter_by(token_hash=hash_token(first["refresh_token"])).one()
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    resp = token(
        world,
        {
            "grant_type": "refresh_token",
            "refresh_token": first["refresh_token"],
            "client_id": world.client_row.client_id,
        },
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "invalid_grant"


def test_ac9_a_refresh_token_belongs_to_one_client(world, db):
    _code, _verifier, form = connect(world)
    first = token(world, form).get_json()
    thief = make_client(db)
    resp = token(
        world, {"grant_type": "refresh_token", "refresh_token": first["refresh_token"], "client_id": thief.client_id}
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "invalid_grant"


def test_ac9_an_access_token_is_not_accepted_as_a_refresh_token(world):
    _code, _verifier, form = connect(world)
    first = token(world, form).get_json()
    resp = token(
        world,
        {
            "grant_type": "refresh_token",
            "refresh_token": first["access_token"],
            "client_id": world.client_row.client_id,
        },
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "invalid_grant"


def test_ac9_refresh_cannot_widen_the_scope(world):
    _code, _verifier, form = connect(world)
    first = token(world, form).get_json()
    resp = token(
        world,
        {
            "grant_type": "refresh_token",
            "refresh_token": first["refresh_token"],
            "client_id": world.client_row.client_id,
            "scope": "bize.read bize.write",
        },
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "invalid_scope"


def test_reconnecting_the_same_client_replaces_the_grants_tokens(world, db):
    """Assumption M2: one grant per person per client."""
    _code, _verifier, form = connect(world)
    first = token(world, form).get_json()
    _code2, _verifier2, form2 = connect(world)
    second = token(world, form2).get_json()
    db.expire_all()
    assert db.query(OAuthGrant).filter_by(org_id=world.org.id, revoked_at=None).count() == 1
    assert world.anon().get("/api/core/mcp/me", headers=bearer(first["access_token"])).status_code == 401
    assert world.anon().get("/api/core/mcp/me", headers=bearer(second["access_token"])).status_code == 200


# --- revocation (RFC 7009) ----------------------------------------------------------------------


def test_revoking_an_access_token_ends_only_that_token(world):
    _code, _verifier, form = connect(world)
    pair = token(world, form).get_json()
    resp = world.anon().post(
        "/oauth/revoke", data={"token": pair["access_token"], "client_id": world.client_row.client_id}
    )
    assert resp.status_code == 200
    assert world.anon().get("/api/core/mcp/me", headers=bearer(pair["access_token"])).status_code == 401
    refreshed = token(
        world,
        {
            "grant_type": "refresh_token",
            "refresh_token": pair["refresh_token"],
            "client_id": world.client_row.client_id,
        },
    )
    assert refreshed.status_code == 200


def test_revoking_a_refresh_token_ends_the_grant(world, db):
    _code, _verifier, form = connect(world)
    pair = token(world, form).get_json()
    resp = world.anon().post("/oauth/revoke", data={"token": pair["refresh_token"]})
    assert resp.status_code == 200
    assert world.anon().get("/api/core/mcp/me", headers=bearer(pair["access_token"])).status_code == 401
    db.expire_all()
    assert db.query(OAuthGrant).filter_by(org_id=world.org.id).one().revoked_at is not None


@pytest.mark.parametrize("value", ["bza_doesnotexist", "garbage", "", "bzr_" + "x" * 43])
def test_revoke_always_answers_200(world, value):
    resp = world.anon().post("/oauth/revoke", data={"token": value})
    assert resp.status_code == 200


def test_revoke_needs_no_csrf_token(world, flask_app, monkeypatch):
    monkeypatch.setitem(flask_app.config, "WTF_CSRF_ENABLED", True)
    assert world.anon().post("/oauth/revoke", data={"token": "bza_x"}).status_code == 200


def test_another_clients_revoke_does_not_end_the_grant(world, db):
    _code, _verifier, form = connect(world)
    pair = token(world, form).get_json()
    thief = make_client(db)
    world.anon().post("/oauth/revoke", data={"token": pair["refresh_token"], "client_id": thief.client_id})
    assert world.anon().get("/api/core/mcp/me", headers=bearer(pair["access_token"])).status_code == 200


# --- AC10 ---------------------------------------------------------------------------------------


def test_ac10_no_raw_token_is_logged_while_a_connection_is_made(world, caplog, capfd):
    caplog.set_level(logging.DEBUG)
    _code, _verifier, form = connect(world)
    pair = token(world, form).get_json()
    refresh_form = {
        "grant_type": "refresh_token",
        "refresh_token": pair["refresh_token"],
        "client_id": world.client_row.client_id,
    }
    rotated = token(world, refresh_form).get_json()
    world.anon().get("/api/core/mcp/me", headers=bearer(rotated["access_token"]))
    world.anon().post("/oauth/revoke", data={"token": rotated["access_token"]})
    token(world, refresh_form)  # reuse, so the failure paths log too

    out = capfd.readouterr()
    haystack = "\n".join([caplog.text, out.out, out.err])
    secrets_seen = [
        form["code"],
        form["code_verifier"],
        pair["access_token"],
        pair["refresh_token"],
        rotated["access_token"],
        rotated["refresh_token"],
    ]
    # The scan is only meaningful if the run actually logged what we expect it to.
    assert "mcp.token_issued" in haystack
    assert "mcp.request" in haystack
    for secret in secrets_seen:
        assert secret not in haystack, secret[:8]


def test_ac10_the_events_are_emitted_without_the_secret(world, caplog):
    caplog.set_level(logging.DEBUG)
    _code, _verifier, form = connect(world)
    pair = token(world, form).get_json()
    world.anon().get("/api/core/mcp/me", headers=bearer(pair["access_token"]))
    text = caplog.text
    assert "mcp.token_issued" in text
    assert "mcp.request" in text
    assert pair["access_token"] not in text


@pytest.mark.parametrize(
    "line",
    [
        "Authorization: Bearer bza_" + "A" * 43,
        "refresh bzr_" + "b-_" * 14 + "c",
        "GET /cb?code=bzc_" + "z" * 43 + "&state=1",
        "token=bza_" + "q" * 43,
    ],
)
def test_ac10_a_log_line_with_a_token_value_is_redacted(line):
    from app.observability.logging_config import scrub_personal_text

    event = scrub_personal_text(None, "info", {"event": line, "detail": {"nested": line}})
    for text in (event["event"], event["detail"]["nested"]):
        assert "bza_" + "A" * 10 not in text
        assert "bzr_" + "b-_" * 4 not in text
        assert "bzc_" + "z" * 10 not in text
        assert "bza_" + "q" * 10 not in text


def test_ac10_a_token_under_a_secret_looking_key_is_redacted():
    from app.observability.logging_config import redact_sensitive_fields

    event = redact_sensitive_fields(None, "info", {"event": "x", "access_token": "bza_abc", "refresh_token": "bzr_abc"})
    assert event["access_token"] == "[REDACTED]"
    assert event["refresh_token"] == "[REDACTED]"
