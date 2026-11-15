"""Fixes from the build review (.agents/reports/public-mcp/build-review-oauth.md)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest import mock

from app.core.db.models.user import User
from app.core.security.access_policy import ROLE_PERMISSIONS  # noqa: F401
from app.core.security.auth_service import AuthService
from app.features.mcp_oauth.models import OAuthGrant, OAuthToken
from app.features.mcp_oauth.services import client_registry
from app.features.mcp_oauth.services.tokens import hash_token
from tests.mcp_oauth.support import authorize_params, authorize_url, bearer, mint_grant, pkce_pair, redirect_params
from tests.mcp_oauth.test_tokens import connect, token


def test_f1_a_signed_out_visitor_cannot_make_the_server_fetch_a_url(world, monkeypatch):
    spy = mock.Mock()
    monkeypatch.setattr(client_registry, "http_get_pinned", spy)
    _v, challenge = pkce_pair()
    resp = world.anon().get(authorize_url(authorize_params("https://stranger.example.test/c.json", challenge)))
    assert resp.status_code == 302
    assert resp.headers["Location"].startswith("/?login=1&next=")
    assert spy.call_count == 0


def test_f3_a_device_signed_out_by_a_reconnect_does_not_end_the_new_connection(world, db):
    _c, _v, form = connect(world)
    first = token(world, form).get_json()
    _c2, _v2, form2 = connect(world)
    second = token(world, form2).get_json()
    resp = token(
        world,
        {
            "grant_type": "refresh_token",
            "refresh_token": first["refresh_token"],
            "client_id": world.client_row.client_id,
        },
    )
    assert resp.status_code == 400 and resp.get_json()["error"] == "invalid_grant"
    assert world.anon().get("/api/core/mcp/me", headers=bearer(second["access_token"])).status_code == 200
    db.expire_all()
    assert db.query(OAuthGrant).filter_by(org_id=world.org.id, revoked_at=None).count() == 1


def test_f4_disabling_a_client_ends_its_live_connections(world, db):
    _c, _v, form = connect(world)
    pair = token(world, form).get_json()
    world.client_row.disabled_at = datetime.now(UTC)
    db.commit()
    assert world.anon().get("/api/core/mcp/me", headers=bearer(pair["access_token"])).status_code == 401
    resp = token(
        world,
        {
            "grant_type": "refresh_token",
            "refresh_token": pair["refresh_token"],
            "client_id": world.client_row.client_id,
        },
    )
    assert resp.status_code == 400


def test_f5_reconnecting_after_a_password_change_does_not_revive_old_tokens(world, db):
    grant, access, _r = mint_grant(db, world.users["member"], world.client_row)
    db.get(User, world.users["member"].id).password_hash = AuthService.hash_password("Another-Passw0rd!9")
    db.commit()
    # Sign in with the new password and approve again, before the old token is ever used.
    verifier, challenge = pkce_pair()
    params = authorize_params(world.client_row.client_id, challenge)
    session = world.anon()
    login = session.post("/auth/login", json={"email": world.users["member"].email, "password": "Another-Passw0rd!9"})
    assert login.status_code == 200
    approved = session.post("/oauth/authorize", data={**params, "decision": "approve", "access_level": "read"})
    assert approved.status_code == 302
    form = {
        "grant_type": "authorization_code",
        "code": redirect_params(approved)["code"],
        "code_verifier": verifier,
        "redirect_uri": params["redirect_uri"],
        "client_id": params["client_id"],
        "resource": params["resource"],
    }
    db.expire_all()
    assert db.get(OAuthGrant, grant.id).revoked_at is not None
    assert world.anon().get("/api/core/mcp/me", headers=bearer(access)).status_code == 401
    assert token(world, form).status_code == 200


def test_f11_the_bearer_scheme_name_is_case_insensitive(world, db):
    _g, access, _r = mint_grant(db, world.users["member"], world.client_row)
    resp = world.anon().get("/api/core/mcp/me", headers={"Authorization": f"bearer {access}"})
    assert resp.status_code == 200
    assert db.query(OAuthToken).filter_by(token_hash=hash_token(access)).count() == 1
