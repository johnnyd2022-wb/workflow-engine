"""Authenticating a request that carries ``Authorization: Bearer bza_...`` (spec "Bearer path").

Called from the tenant-context middleware, and only when the request has no session user. The
order of the checks is the contract:

1. the access token exists, is unrevoked and unexpired, its grant is unrevoked, and the grant's
   audience is this deployment's configured MCP resource  -> else 401 ``invalid_token``
2. the grant is rate limited (120 a minute)                -> else 429
3. the person is active, their organisation is active, their access has not ended, and they have
   not changed their password since they approved          -> else 401 ``invalid_token``
4. the organisation has assistants on and the person's role is ticked -> else 403 ``mcp_not_allowed``
5. the client is not switched off by Biz-E                  -> else 401 ``invalid_token``
6. the client is verified, or the organisation allows unverified apps -> else 403 ``mcp_not_allowed``
   (design review S3; the grant is kept, so turning the setting on restores it)

Checks 3 to 6 run on every request, so a switch flipped in Settings, a role changed, or a password
reset takes effect on the next call. Nothing here logs the token.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from limits.errors import StorageError

from app.api.ratelimit_store import RETRY_AFTER_SECONDS
from app.core.db.models.organisation import Organisation, OrganisationStatus
from app.core.db.models.user import User
from app.core.security.access_policy import access_expired
from app.core.security.auth_service import auth_stamp
from app.core.security.tenant_scope import tenant_scope
from app.features.mcp_oauth.models import OAuthClient, OAuthGrant
from app.features.mcp_oauth.repositories.grant_repo import GrantRepository
from app.features.mcp_oauth.services import rate_limit, token_service, verified_clients
from app.features.mcp_oauth.services.settings_service import client_is_allowed, is_allowed_for
from app.features.mcp_oauth.services.tokens import ACCESS_PREFIX, CODE_PREFIX, REFRESH_PREFIX, hash_token, looks_like
from app.observability import get_logger
from app.utils.config_loader import config

logger = get_logger(__name__)

WWW_INVALID_TOKEN = 'Bearer error="invalid_token"'
LAST_USED_RESOLUTION = timedelta(minutes=1)


class BearerRejectedError(Exception):
    """The request must be answered with this status, JSON body and headers instead of running."""

    def __init__(self, status: int, error: str, headers: dict | None = None, reason: str = ""):
        super().__init__(error)
        self.status = status
        self.error = error
        self.headers = headers or {}
        self.reason = reason or error


@dataclass(frozen=True)
class BearerPrincipal:
    user: User
    org: Organisation
    grant: OAuthGrant
    client_id: str
    scope: str


def _invalid(reason: str) -> BearerRejectedError:
    return BearerRejectedError(401, "invalid_token", {"WWW-Authenticate": WWW_INVALID_TOKEN}, reason)


def parse_bearer(header: str | None) -> str | None:
    """The presented value when the header is ``Bearer bz?_...`` (one of our prefixes), else ``None``.

    Anything else is not ours and is left to the normal sign-in rules. A value that starts like ours
    but is the wrong kind or the wrong shape is *ours to refuse*, so it gets ``invalid_token`` rather
    than being mistaken for no credentials.
    """
    if not header or header[:7].lower() != "bearer ":  # the scheme name is case-insensitive (RFC 7235)
        return None
    raw = header[7:].strip()
    return raw if raw.startswith((ACCESS_PREFIX, REFRESH_PREFIX, CODE_PREFIX)) else None


def authenticate(db, raw: str, *, now: datetime | None = None, calculation: bool = False) -> BearerPrincipal:
    """``calculation``: the route is an ``x-bize.kind: calculation`` operation (its own, lower limit)."""
    now = now or datetime.now(UTC)
    if not looks_like(ACCESS_PREFIX, raw):
        raise _invalid("malformed_token")
    repo = GrantRepository(db)
    token = repo.find_token_by_hash(hash_token(raw))
    if token is None or token.kind != "access" or token.revoked_at is not None or token.expires_at <= now:
        raise _invalid("unknown_or_expired_token")
    org_id = token.org_id
    with tenant_scope(org_id):  # the row told us the org; everything below is scoped to it
        grant = repo.get_grant(org_id, token.grant_id)
        if grant is None or grant.revoked_at is not None:
            raise _invalid("grant_revoked")
        resource = config.mcp_resource
        if not resource or grant.resource != resource:
            raise _invalid("wrong_audience")

        try:
            retry_after = rate_limit.hit_bearer(grant.id, calculation=calculation)
        except StorageError:
            # The shared store is down: refuse rather than count nothing (design review S4).
            raise BearerRejectedError(
                503, "temporarily_unavailable", {"Retry-After": str(RETRY_AFTER_SECONDS)}, "ratelimit_store_unavailable"
            ) from None
        if retry_after is not None:
            raise BearerRejectedError(429, "rate_limited", {"Retry-After": str(retry_after)}, "rate_limited")

        user = db.query(User).filter(User.org_id == org_id, User.id == grant.user_id).one_or_none()
        org = db.query(Organisation).filter(Organisation.id == org_id).one_or_none()
        if user is None or not user.is_active or org is None or org.status != OrganisationStatus.ACTIVE:
            raise _invalid("account_unavailable")
        if access_expired(user, now):
            raise _invalid("access_ended")
        if auth_stamp(user.password_hash) != grant.auth_stamp:
            token_service.revoke(db, repo, grant, "password_changed", now)
            raise _invalid("password_changed")
        if not is_allowed_for(db, org_id, user):
            raise BearerRejectedError(403, "mcp_not_allowed", reason="org_off_or_role_not_allowed")

        # oauth_clients is the one global table: no tenant filter applies, by design.
        client = db.query(OAuthClient).filter(OAuthClient.id == grant.client_pk).one_or_none()
        if client is None or client.disabled_at is not None:
            raise _invalid("client_disabled")  # the kill switch ends live connections, not just new ones
        verified_clients.sync(client)  # the code list decides; committed below with last_used
        if not client_is_allowed(db, org_id, client):
            db.commit()
            raise BearerRejectedError(403, "mcp_not_allowed", reason="unverified_client_not_allowed")

        repo.touch_last_used(org_id, grant.id, now, now - LAST_USED_RESOLUTION)
        db.commit()
        return BearerPrincipal(
            user=user,
            org=org,
            grant=grant,
            client_id=client.client_id[:200],
            scope=grant.scope,
        )
