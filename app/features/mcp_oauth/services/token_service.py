"""``POST /oauth/token`` and ``POST /oauth/revoke``: code exchange, refresh rotation, revocation.

Rules that matter most (spec "OAuth", RFC 6749 §10.5, RFC 7009, OAuth 2.1 refresh-token rotation):

* A code is single use. Presenting a used code again ends the grant and every token under it.
* PKCE ``S256`` must match; ``redirect_uri``, ``client_id`` and ``resource`` must equal what the
  code was issued for. A wrong guess does not burn the code (a stranger must not be able to
  spoil a real person's connection by guessing).
* A refresh token rotates: the old one is revoked and points at its replacement. Presenting a
  revoked one ends the whole grant, except for one retry shortly after the rotation whose
  replacement has not been used yet (a lost response; see ``_unseen_successor``).
* Everything is looked up by the SHA-256 of the presented value; the raw value is never stored or
  logged. Nothing here puts a token in a log line, an exception message or an audit row.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from app.core.db.models.organisation import Organisation, OrganisationStatus
from app.core.db.models.user import User
from app.core.security.access_policy import access_expired
from app.core.security.auth_service import auth_stamp
from app.core.security.tenant_scope import tenant_scope, unscoped
from app.core.utils.log_action import log_action
from app.features.mcp_oauth import SUPPORTED_SCOPES
from app.features.mcp_oauth.models import OAuthClient, OAuthGrant, OAuthToken
from app.features.mcp_oauth.repositories.grant_repo import GrantRepository
from app.features.mcp_oauth.services.tokens import (
    ACCESS_PREFIX,
    ACCESS_TTL,
    CODE_PREFIX,
    REFRESH_PREFIX,
    REFRESH_REUSE_GRACE,
    REFRESH_TTL,
    hash_token,
    looks_like,
    new_token,
    verifier_matches,
)
from app.observability import get_logger

logger = get_logger(__name__)


class TokenError(Exception):
    """An RFC 6749 §5.2 error response."""

    def __init__(self, error: str, description: str = "", status: int = 400):
        super().__init__(f"{error}: {description}" if description else error)
        self.error = error
        self.description = description
        self.status = status

    def body(self) -> dict:
        body = {"error": self.error}
        if self.description:
            body["error_description"] = self.description
        return body


@dataclass(frozen=True)
class Issued:
    access_token: str
    refresh_token: str
    scope: str

    def body(self) -> dict:
        return {
            "access_token": self.access_token,
            "token_type": "Bearer",
            "expires_in": int(ACCESS_TTL.total_seconds()),
            "refresh_token": self.refresh_token,
            "scope": self.scope,
        }


def _text(form, key: str, *, required: bool = True, limit: int = 2048) -> str | None:
    value = form.get(key)
    if value is None or value == "":
        if required:
            raise TokenError("invalid_request", f"{key} is required")
        return None
    if not isinstance(value, str) or len(value) > limit:
        raise TokenError("invalid_request", f"{key} is invalid")
    return value


def _client(db, client_id: str) -> OAuthClient:
    # oauth_clients is global (no tenant filter). Metadata-URL clients are not fetched here: the
    # row exists from the authorization request, and this endpoint is unauthenticated.
    client = db.query(OAuthClient).filter(OAuthClient.client_id == client_id).one_or_none()
    if client is None:
        raise TokenError("invalid_client", "Unknown client")
    return client


def _check_user_and_org(db, grant: OAuthGrant, repo: GrantRepository, now: datetime) -> None:
    """The person must still be able to use their account, and must not have changed their password."""
    user = db.query(User).filter(User.org_id == grant.org_id, User.id == grant.user_id).one_or_none()
    org = db.query(Organisation).filter(Organisation.id == grant.org_id).one_or_none()
    if (
        user is None
        or not user.is_active
        or access_expired(user, now)
        or org is None
        or org.status != OrganisationStatus.ACTIVE
    ):
        raise TokenError("invalid_grant", "The account is not available")
    if auth_stamp(user.password_hash) != grant.auth_stamp:
        revoke(db, repo, grant, "password_changed", now)
        raise TokenError("invalid_grant", "The password has changed; connect again")


def revoke(db, repo: GrantRepository, grant: OAuthGrant, reason: str, now: datetime) -> None:
    """End the grant, commit, and leave a trace. Never receives a raw token."""
    org_id, grant_id, user_id = grant.org_id, grant.id, grant.user_id
    if repo.revoke_grant(org_id, grant_id, reason, now):
        db.commit()
        log_action("mcp_grant_revoked", "oauth_grant", grant_id, {"reason": reason}, org_id, None)
        logger.info("mcp.grant_revoked", grant_id=str(grant_id), reason=reason, user_id=str(user_id))


def _issue(db, repo: GrantRepository, grant: OAuthGrant, now: datetime, *, replaces=None, via: str) -> Issued:
    access = new_token(ACCESS_PREFIX)
    refresh = new_token(REFRESH_PREFIX)
    repo.add_token(grant.org_id, grant.id, "access", hash_token(access), now + ACCESS_TTL)
    new_refresh = repo.add_token(grant.org_id, grant.id, "refresh", hash_token(refresh), now + REFRESH_TTL)
    if replaces is not None:
        replaces.revoked_at = now
        replaces.replaced_by_id = new_refresh.id
    db.commit()
    logger.info("mcp.token_issued", grant_id=str(grant.id), org_id=str(grant.org_id), via=via)
    return Issued(access_token=access, refresh_token=refresh, scope=grant.scope)


def exchange_code(db, form) -> Issued:
    code = _text(form, "code")
    verifier = _text(form, "code_verifier", limit=256)
    redirect_uri = _text(form, "redirect_uri")
    client = _client(db, _text(form, "client_id"))
    resource = _text(form, "resource", required=False)
    now = datetime.now(UTC)
    invalid = TokenError("invalid_grant", "The authorization code is invalid, expired or already used")
    if not looks_like(CODE_PREFIX, code):
        raise invalid

    repo = GrantRepository(db)
    row = repo.find_code_by_hash(hash_token(code), lock=True)
    if row is None:
        raise invalid
    with tenant_scope(row.org_id):  # the organisation is now known: everything below is scoped to it
        grant = repo.get_grant(row.org_id, row.grant_id, lock=True)
        if grant is None:
            raise invalid
        if row.used_at is not None:
            # RFC 6749 §10.5: a replayed code means it may have been stolen. End the connection.
            revoke(db, repo, grant, "code_reuse", now)
            raise invalid
        if (
            grant.revoked_at is not None
            or client.disabled_at is not None
            or grant.client_pk != client.id
            or row.expires_at <= now
            or redirect_uri != row.redirect_uri
            or (resource is not None and resource != row.resource)
            or not verifier_matches(verifier, row.code_challenge)
        ):
            db.rollback()
            raise invalid
        _check_user_and_org(db, grant, repo, now)
        row.used_at = now
        # One live grant per person per client (M2): a new connection replaces the old tokens.
        repo.revoke_tokens(grant.org_id, grant.id, now)
        return _issue(db, repo, grant, now, via="authorization_code")


def _unseen_successor(repo: GrantRepository, grant: OAuthGrant, token: OAuthToken, now: datetime) -> OAuthToken | None:
    """The successor of a refresh token that was rotated out moments ago, if this is a retry.

    A client that lost the response to a refresh presents the old token again (S5). That is told
    apart from a stolen copy by three things, all required: the rotation was within
    ``REFRESH_REUSE_GRACE`` (measured from the rotation, so retries never extend it); the successor
    is still unused (nothing has refreshed from it, so no second holder has appeared); and it is
    still a live refresh token of this same grant. Anything else is reuse and ends the grant.
    """
    if token.revoked_at is None or now - token.revoked_at > REFRESH_REUSE_GRACE:
        return None
    successor = repo.get_token(grant.org_id, grant.id, token.replaced_by_id)
    if successor is None or successor.kind != "refresh" or successor.revoked_at is not None:
        return None
    return successor


def refresh(db, form) -> Issued:
    raw = _text(form, "refresh_token")
    client = _client(db, _text(form, "client_id"))
    scope = _text(form, "scope", required=False)
    resource = _text(form, "resource", required=False)
    now = datetime.now(UTC)
    invalid = TokenError("invalid_grant", "The refresh token is invalid, expired or revoked")
    if not looks_like(REFRESH_PREFIX, raw):
        raise invalid

    repo = GrantRepository(db)
    token = repo.find_token_by_hash(hash_token(raw), lock=True)
    if token is None or token.kind != "refresh":
        raise invalid
    with tenant_scope(token.org_id):
        grant = repo.get_grant(token.org_id, token.grant_id, lock=True)
        if grant is None or grant.client_pk != client.id:
            db.rollback()
            raise invalid
        retry_of = None  # the unseen successor a retried rotation replaces (see _unseen_successor)
        if token.revoked_at is not None:
            if token.replaced_by_id is not None:
                retry_of = _unseen_successor(repo, grant, token, now)
                if retry_of is None:
                    # A rotated-out refresh token coming back: someone has a copy. End the connection.
                    revoke(db, repo, grant, "refresh_reuse", now)
                    raise invalid
            else:
                # Revoked by a reconnection (M2), not by rotation: that device is simply signed out.
                # Not a theft signal, so the newer connection stays.
                db.rollback()
                raise invalid
        if grant.revoked_at is not None or client.disabled_at is not None or token.expires_at <= now:
            db.rollback()
            raise invalid
        if resource is not None and resource != grant.resource:
            db.rollback()
            raise invalid
        if scope is not None and not set(scope.split()) <= set(grant.scope.split()) & set(SUPPORTED_SCOPES):
            db.rollback()
            raise TokenError("invalid_scope", "A refresh cannot widen the scope")
        _check_user_and_org(db, grant, repo, now)
        if retry_of is not None:
            # The raw successor is not stored, so it cannot be handed out again: retire it unseen
            # and issue a fresh one in its place.
            return _issue(db, repo, grant, now, replaces=retry_of, via="refresh_token_retry")
        return _issue(db, repo, grant, now, replaces=token, via="refresh_token")


def revoke_presented(db, form) -> None:
    """RFC 7009. The caller answers 200 whatever happens here; this never reveals whether a token existed."""
    raw = form.get("token")
    if not isinstance(raw, str) or not raw or len(raw) > 256:
        return
    client_id = form.get("client_id")
    now = datetime.now(UTC)
    repo = GrantRepository(db)
    token = repo.find_token_by_hash(hash_token(raw))
    if token is None:
        return
    with tenant_scope(token.org_id):
        grant = repo.get_grant(token.org_id, token.grant_id)
        if grant is None:
            return
        if isinstance(client_id, str) and client_id:
            with unscoped():
                client = db.query(OAuthClient).filter(OAuthClient.id == grant.client_pk).one_or_none()
            if client is None or client.client_id != client_id:
                return  # a token only its own client may revoke
        if token.kind == "refresh":
            revoke(db, repo, grant, "revoked_by_client", now)
        elif token.revoked_at is None:
            token.revoked_at = now
            db.commit()
            logger.info("mcp.token_revoked", grant_id=str(grant.id), kind=token.kind)
