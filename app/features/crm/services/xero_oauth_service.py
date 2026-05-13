"""XeroOAuthService — OAuth2 flow, token encryption/decryption, refresh."""

import base64
import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

import requests
from sqlalchemy.orm import Session

from app.features.crm.models.xero_oauth_token import XeroOAuthToken
from app.features.crm.repositories.xero_tenant_repo import XeroTenantRepository
from app.features.crm.repositories.xero_token_repo import XeroTokenRepository
from app.utils.config_loader import config

logger = logging.getLogger(__name__)

XERO_TOKEN_URL = "https://identity.xero.com/connect/token"
XERO_REVOKE_URL = "https://identity.xero.com/connect/revocation"
XERO_CONNECTIONS_URL = "https://api.xero.com/connections"
XERO_AUTH_URL = "https://login.xero.com/identity/connect/authorize"
XERO_SCOPES = "openid profile email accounting.contacts accounting.transactions offline_access"


class XeroTokenExpiredError(Exception):
    """Raised when the stored Xero token is invalid or cannot be refreshed."""


class XeroOAuthService:
    def __init__(self, db: Session):
        self.db = db
        self.token_repo = XeroTokenRepository(db)
        self.tenant_repo = XeroTenantRepository(db)

    # ------------------------------------------------------------------
    # Encryption helpers — Fernet key derived from app secret_key
    # ------------------------------------------------------------------

    @staticmethod
    def _fernet():
        from cryptography.fernet import Fernet

        secret = config.get("app", "secret_key", fallback="dev-secret-key-change-in-production")
        key = hashlib.sha256(secret.encode()).digest()
        return Fernet(base64.urlsafe_b64encode(key))

    @classmethod
    def encrypt(cls, plaintext: str) -> str:
        return cls._fernet().encrypt(plaintext.encode()).decode()

    @classmethod
    def decrypt(cls, ciphertext: str) -> str:
        return cls._fernet().decrypt(ciphertext.encode()).decode()

    # ------------------------------------------------------------------
    # OAuth2 authorization URL
    # ------------------------------------------------------------------

    def build_auth_url(self, state: str) -> str:
        from urllib.parse import urlencode

        params = {
            "response_type": "code",
            "client_id": config.xero_client_id,
            "redirect_uri": config.xero_redirect_uri,
            "scope": XERO_SCOPES,
            "state": state,
        }
        return f"{XERO_AUTH_URL}?{urlencode(params)}"

    @staticmethod
    def generate_state() -> str:
        return secrets.token_urlsafe(32)

    # ------------------------------------------------------------------
    # Token exchange (authorization_code grant)
    # ------------------------------------------------------------------

    def exchange_code(self, code: str) -> dict:
        resp = requests.post(
            XERO_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": config.xero_redirect_uri,
            },
            auth=(config.xero_client_id, config.xero_client_secret),
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Tenant (connection) discovery
    # ------------------------------------------------------------------

    def get_connections(self, access_token: str) -> list[dict]:
        resp = requests.get(
            XERO_CONNECTIONS_URL,
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Persist tokens after exchange/refresh
    # ------------------------------------------------------------------

    def store_tokens(self, org_id: UUID, token_data: dict, connections: list[dict]) -> None:
        expires_in = token_data.get("expires_in", 1800)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

        # Use the first tenant connection
        xero_tenant_id = connections[0]["tenantId"] if connections else ""
        tenant_name = connections[0].get("tenantName") if connections else None
        tenant_type = connections[0].get("tenantType") if connections else None

        self.token_repo.upsert(
            org_id=org_id,
            xero_tenant_id=xero_tenant_id,
            access_token_encrypted=self.encrypt(token_data["access_token"]),
            refresh_token_encrypted=self.encrypt(token_data["refresh_token"]),
            expires_at=expires_at,
            scopes=token_data.get("scope"),
        )

        self.tenant_repo.upsert(
            org_id=org_id,
            xero_tenant_id=xero_tenant_id,
            xero_tenant_name=tenant_name,
            xero_tenant_type=tenant_type,
        )

        self.db.commit()

    # ------------------------------------------------------------------
    # Get a valid (auto-refreshed) access token
    # ------------------------------------------------------------------

    def get_valid_token(self, org_id: UUID) -> tuple[str, str]:
        """Return (access_token, xero_tenant_id). Auto-refreshes if near expiry."""
        token_record = self.token_repo.get(org_id)
        if not token_record:
            raise XeroTokenExpiredError("No Xero token found — connect Xero first.")

        now = datetime.now(timezone.utc)
        expires_at = token_record.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        if now >= expires_at - timedelta(minutes=5):
            token_record = self._refresh_token(org_id, token_record)

        try:
            access_token = self.decrypt(token_record.access_token_encrypted)
        except Exception:
            raise XeroTokenExpiredError("Token decryption failed — reconnect Xero.")

        return access_token, token_record.xero_tenant_id

    def _refresh_token(self, org_id: UUID, token_record: XeroOAuthToken) -> XeroOAuthToken:
        try:
            refresh_token = self.decrypt(token_record.refresh_token_encrypted)
        except Exception as e:
            self.token_repo.invalidate(org_id)
            self.db.commit()
            raise XeroTokenExpiredError("Refresh token decryption failed.") from e

        try:
            resp = requests.post(
                XERO_TOKEN_URL,
                data={"grant_type": "refresh_token", "refresh_token": refresh_token},
                auth=(config.xero_client_id, config.xero_client_secret),
                timeout=15,
            )
            resp.raise_for_status()
            token_data = resp.json()
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code in (400, 401):
                self.token_repo.invalidate(org_id)
                self.db.commit()
                raise XeroTokenExpiredError("Xero refresh token rejected — reconnect required.") from e
            raise

        expires_at = datetime.now(timezone.utc) + timedelta(seconds=token_data.get("expires_in", 1800))
        updated = self.token_repo.upsert(
            org_id=org_id,
            xero_tenant_id=token_record.xero_tenant_id,
            access_token_encrypted=self.encrypt(token_data["access_token"]),
            refresh_token_encrypted=self.encrypt(token_data.get("refresh_token", "")),
            expires_at=expires_at,
            scopes=token_data.get("scope"),
        )
        self.db.commit()
        logger.info("Refreshed Xero token for org_id=%s", org_id)
        return updated

    # ------------------------------------------------------------------
    # Disconnect
    # ------------------------------------------------------------------

    def disconnect(self, org_id: UUID) -> None:
        token_record = self.token_repo.get(org_id)
        if token_record:
            try:
                refresh_token = self.decrypt(token_record.refresh_token_encrypted)
                requests.post(
                    XERO_REVOKE_URL,
                    data={"token": refresh_token},
                    auth=(config.xero_client_id, config.xero_client_secret),
                    timeout=10,
                )
            except Exception as e:
                logger.warning("Xero token revocation failed (continuing disconnect): %s", e)

        self.token_repo.invalidate(org_id)
        self.tenant_repo.mark_disconnected(org_id)
        self.db.commit()
