"""Helpers for the public-MCP 8.2b tests (spec .agents/specs/public-mcp.md).

Plain functions, no fixtures: the fixtures live in ``conftest.py`` beside this file.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import threading
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlencode, urlparse
from uuid import UUID, uuid4

from app.features.mcp_oauth.models import OAuthClient, OAuthGrant, OAuthToken
from app.features.mcp_oauth.services.tokens import (
    ACCESS_PREFIX,
    REFRESH_PREFIX,
    hash_token,
    new_token,
)
from app.utils.config_loader import config

RESOURCE = config.mcp_resource
ISSUER = config.mcp_issuer
REDIRECT = "https://assistant.example.test/callback"
TEST_NAME_PREFIX = "MCPTEST"  # the world fixture deletes every client whose name starts with this
ASSISTANT_NAME = f"{TEST_NAME_PREFIX} Assistant"

_addr_lock = threading.Lock()
_addr_counter = [0]


def unique_addr() -> str:
    """A fresh client address per test client, so per-IP rate limits never bleed between tests."""
    with _addr_lock:
        _addr_counter[0] += 1
        n = _addr_counter[0]
    return f"10.{(n >> 16) & 255}.{(n >> 8) & 255}.{n & 255}"


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def pkce_pair() -> tuple[str, str]:
    """(verifier, S256 challenge)."""
    verifier = secrets.token_urlsafe(48)
    return verifier, b64url(hashlib.sha256(verifier.encode()).digest())


def make_client(db, *, redirect_uris=None, name=ASSISTANT_NAME, verified=False, disabled=False, client_id=None):
    row = OAuthClient(
        client_id=client_id or f"test-client-{uuid4().hex}",
        client_name=name,
        redirect_uris=list(redirect_uris or [REDIRECT]),
        registration="dcr",
        verified=verified,
        disabled_at=datetime.now(UTC) if disabled else None,
    )
    db.add(row)
    db.commit()
    return row


def authorize_params(client_id, challenge, **overrides):
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT,
        "state": "state-123",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "scope": "bize.read",
        "resource": RESOURCE,
    }
    params.update(overrides)
    return {k: v for k, v in params.items() if v is not None}


def authorize_url(params) -> str:
    return "/oauth/authorize?" + urlencode(params)


def redirect_params(response) -> dict[str, str]:
    """Query parameters of a redirect response's Location."""
    location = response.headers["Location"]
    return {k: v[0] for k, v in parse_qs(urlparse(location).query).items()}


def mint_grant(
    db,
    user,
    client,
    *,
    resource=None,
    access_ttl=timedelta(hours=1),
    scope="bize.read",
    auth_stamp=None,
):
    """A grant with a live access and refresh token, written straight to the tables.

    Returns ``(grant, access_token, refresh_token)`` with the raw token values.
    """
    from app.core.security.auth_service import auth_stamp as compute_stamp

    now = datetime.now(UTC)
    grant = OAuthGrant(
        org_id=user.org_id,
        user_id=user.id,
        client_pk=client.id,
        scope=scope,
        resource=resource or RESOURCE,
        auth_stamp=auth_stamp or compute_stamp(user.password_hash),
    )
    db.add(grant)
    db.flush()
    access = new_token(ACCESS_PREFIX)
    refresh = new_token(REFRESH_PREFIX)
    db.add(
        OAuthToken(
            org_id=user.org_id,
            grant_id=grant.id,
            kind="access",
            token_hash=hash_token(access),
            expires_at=now + access_ttl,
        )
    )
    db.add(
        OAuthToken(
            org_id=user.org_id,
            grant_id=grant.id,
            kind="refresh",
            token_hash=hash_token(refresh),
            expires_at=now + timedelta(days=30),
        )
    )
    db.commit()
    return grant, access, refresh


def bearer(token) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def as_uuid(value) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))
