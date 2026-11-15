"""Grants, authorization codes and tokens.

Every method that knows the organisation takes ``org_id`` and filters on it inline. The two
``find_*_by_hash`` methods are the exception: a code or token is presented without any other hint,
so the organisation is learned *from* the row. They run unscoped on purpose, look the row up by
the hash of a 256-bit secret, and hand the row's own ``org_id`` back to the caller, who scopes
everything after that.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.db.models.user import User
from app.core.security.tenant_scope import unscoped
from app.features.mcp_oauth.models import OAuthAuthorizationCode, OAuthClient, OAuthGrant, OAuthToken


class GrantRepository:
    def __init__(self, db: Session):
        self.db = db

    # --- lookups by secret: the organisation is not known yet ---------------------------------

    def find_code_by_hash(self, code_hash: str, *, lock: bool = False) -> OAuthAuthorizationCode | None:
        with unscoped():  # org unknown until the row is found; the hash is the key
            query = self.db.query(OAuthAuthorizationCode).filter(OAuthAuthorizationCode.code_hash == code_hash)
            if lock:
                query = query.with_for_update()
            return query.one_or_none()

    def find_token_by_hash(self, token_hash: str, *, lock: bool = False) -> OAuthToken | None:
        with unscoped():  # org unknown until the row is found; the hash is the key
            query = self.db.query(OAuthToken).filter(OAuthToken.token_hash == token_hash)
            if lock:
                query = query.with_for_update()
            return query.one_or_none()

    # --- grants -------------------------------------------------------------------------------

    def get_grant(self, org_id: UUID, grant_id: UUID, *, lock: bool = False) -> OAuthGrant | None:
        query = self.db.query(OAuthGrant).filter(OAuthGrant.org_id == org_id, OAuthGrant.id == grant_id)
        if lock:
            query = query.with_for_update()
        return query.one_or_none()

    def get_live_grant(self, org_id: UUID, user_id: UUID, client_pk: UUID) -> OAuthGrant | None:
        return (
            self.db.query(OAuthGrant)
            .filter(
                OAuthGrant.org_id == org_id,
                OAuthGrant.user_id == user_id,
                OAuthGrant.client_pk == client_pk,
                OAuthGrant.revoked_at.is_(None),
            )
            .one_or_none()
        )

    def list_live_grants(self, org_id: UUID, user_id: UUID | None = None) -> list[tuple[OAuthGrant, OAuthClient, User]]:
        query = (
            self.db.query(OAuthGrant, OAuthClient, User)
            .join(OAuthClient, OAuthClient.id == OAuthGrant.client_pk)
            .join(User, (User.org_id == OAuthGrant.org_id) & (User.id == OAuthGrant.user_id))
            .filter(OAuthGrant.org_id == org_id, OAuthGrant.revoked_at.is_(None))
        )
        if user_id is not None:
            query = query.filter(OAuthGrant.user_id == user_id)
        return query.order_by(OAuthGrant.created_at.desc()).all()

    def revoke_grant(self, org_id: UUID, grant_id: UUID, reason: str, now: datetime) -> bool:
        """End a grant and every token under it. True when it was live."""
        grant = self.get_grant(org_id, grant_id)
        if grant is None or grant.revoked_at is not None:
            return False
        grant.revoked_at = now
        grant.revoked_reason = reason
        self.revoke_tokens(org_id, grant_id, now)
        return True

    def revoke_user_grants(self, org_id: UUID, user_id: UUID, reason: str, now: datetime) -> int:
        ids = [
            g.id
            for g in self.db.query(OAuthGrant).filter(
                OAuthGrant.org_id == org_id, OAuthGrant.user_id == user_id, OAuthGrant.revoked_at.is_(None)
            )
        ]
        return sum(1 for grant_id in ids if self.revoke_grant(org_id, grant_id, reason, now))

    def touch_last_used(self, org_id: UUID, grant_id: UUID, now: datetime, older_than: datetime) -> None:
        """Stamp ``last_used_at`` unless it was already stamped since ``older_than``."""
        self.db.execute(
            update(OAuthGrant)
            .where(
                OAuthGrant.org_id == org_id,
                OAuthGrant.id == grant_id,
                (OAuthGrant.last_used_at.is_(None)) | (OAuthGrant.last_used_at < older_than),
            )
            .values(last_used_at=now)
        )

    # --- tokens -------------------------------------------------------------------------------

    def revoke_tokens(self, org_id: UUID, grant_id: UUID, now: datetime, *, keep: tuple[UUID, ...] = ()) -> None:
        query = self.db.query(OAuthToken).filter(
            OAuthToken.org_id == org_id, OAuthToken.grant_id == grant_id, OAuthToken.revoked_at.is_(None)
        )
        for token in query:
            if token.id not in keep:
                token.revoked_at = now

    def add_token(self, org_id: UUID, grant_id: UUID, kind: str, token_hash: str, expires_at: datetime) -> OAuthToken:
        token = OAuthToken(org_id=org_id, grant_id=grant_id, kind=kind, token_hash=token_hash, expires_at=expires_at)
        self.db.add(token)
        self.db.flush()
        return token

    def add_code(
        self,
        org_id: UUID,
        grant_id: UUID,
        *,
        code_hash: str,
        code_challenge: str,
        redirect_uri: str,
        resource: str,
        expires_at: datetime,
    ) -> OAuthAuthorizationCode:
        code = OAuthAuthorizationCode(
            org_id=org_id,
            grant_id=grant_id,
            code_hash=code_hash,
            code_challenge=code_challenge,
            redirect_uri=redirect_uri,
            resource=resource,
            expires_at=expires_at,
        )
        self.db.add(code)
        self.db.flush()
        return code
