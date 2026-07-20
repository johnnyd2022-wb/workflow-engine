"""Repository for XeroOAuthToken records."""

from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.utils.time import utc_now
from app.features.crm.models.xero_oauth_token import XeroOAuthToken


class XeroTokenRepository:
    def __init__(self, db: Session):
        self.db = db

    def upsert(
        self,
        org_id: UUID,
        xero_tenant_id: str,
        access_token_encrypted: str,
        refresh_token_encrypted: str,
        expires_at: datetime,
        scopes: str | None = None,
    ) -> XeroOAuthToken:
        token = self.db.query(XeroOAuthToken).filter(XeroOAuthToken.org_id == org_id).first()

        if token:
            token.xero_tenant_id = xero_tenant_id
            token.access_token_encrypted = access_token_encrypted
            token.refresh_token_encrypted = refresh_token_encrypted
            token.expires_at = expires_at
            token.scopes = scopes
            token.is_valid = True
            token.last_refreshed_at = utc_now()
            token.updated_at = utc_now()
        else:
            token = XeroOAuthToken(
                org_id=org_id,
                xero_tenant_id=xero_tenant_id,
                access_token_encrypted=access_token_encrypted,
                refresh_token_encrypted=refresh_token_encrypted,
                expires_at=expires_at,
                scopes=scopes,
                is_valid=True,
                last_refreshed_at=utc_now(),
            )
            self.db.add(token)

        return token

    def get(self, org_id: UUID) -> XeroOAuthToken | None:
        return (
            self.db.query(XeroOAuthToken)
            .filter(
                XeroOAuthToken.org_id == org_id,
                XeroOAuthToken.is_valid == True,  # noqa: E712
            )
            .first()
        )

    def update_xero_tenant_id(self, org_id: UUID, xero_tenant_id: str) -> None:
        self.db.query(XeroOAuthToken).filter(XeroOAuthToken.org_id == org_id).update(
            {"xero_tenant_id": xero_tenant_id, "updated_at": utc_now()}
        )

    def invalidate(self, org_id: UUID) -> None:
        self.db.query(XeroOAuthToken).filter(XeroOAuthToken.org_id == org_id).update(
            {"is_valid": False, "updated_at": utc_now()}
        )
