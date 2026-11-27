"""XeroOAuthService — OAuth2 flow, token encryption/decryption, refresh."""

import base64
import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import requests
from sqlalchemy.orm import Session

from app.features.crm.models.xero_oauth_token import XeroOAuthToken
from app.features.crm.models.xero_pending_connection import XeroPendingConnection
from app.features.crm.repositories.xero_pending_connection_repo import XeroPendingConnectionRepository
from app.features.crm.repositories.xero_tenant_repo import XeroTenantRepository
from app.features.crm.repositories.xero_token_repo import XeroTokenRepository
from app.observability import get_logger
from app.utils.config_loader import config

logger = get_logger(__name__)

XERO_TOKEN_URL = "https://identity.xero.com/connect/token"
XERO_REVOKE_URL = "https://identity.xero.com/connect/revocation"
XERO_CONNECTIONS_URL = "https://api.xero.com/connections"
XERO_AUTH_URL = "https://login.xero.com/identity/connect/authorize"
XERO_SELECTION_LIFETIME = timedelta(minutes=10)
# accounting.banktransactions.read + accounting.settings.read: live-cogs 8.1b (purchases and the chart
# of accounts). Existing connections reconnect once to grant them.
XERO_SCOPES = (
    "openid profile email accounting.contacts accounting.invoices accounting.invoices.read "
    "accounting.banktransactions.read accounting.settings.read "
    "accounting.reports.profitandloss.read offline_access"
)


class XeroTokenExpiredError(Exception):
    """Raised when the stored Xero token is invalid or cannot be refreshed."""


class XeroOAuthService:
    def __init__(self, db: Session):
        self.db = db
        self.token_repo = XeroTokenRepository(db)
        self.tenant_repo = XeroTenantRepository(db)
        self.pending_repo = XeroPendingConnectionRepository(db)

    # ------------------------------------------------------------------
    # Encryption helpers — Fernet key derived from config.xero_token_secret
    # (XERO_TOKEN_ENCRYPTION_KEY in production; see Config.xero_token_secret)
    # ------------------------------------------------------------------

    @staticmethod
    def _fernet():
        from cryptography.fernet import Fernet

        key = hashlib.sha256(config.xero_token_secret.encode()).digest()
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

    def store_tokens(
        self, org_id: UUID, token_data: dict, connection: dict, *, expires_at: datetime | None = None
    ) -> None:
        """Persist encrypted tokens and the chosen Xero tenant.

        connection — one entry from GET /connections:
          {"id": str, "tenantId": str, "tenantName": str, "tenantType": str}
        """
        if expires_at is None:
            expires_at = datetime.now(UTC) + timedelta(seconds=token_data.get("expires_in", 1800))

        self.pending_repo.clear(org_id)
        self.token_repo.upsert(
            org_id=org_id,
            xero_tenant_id=connection["tenantId"],
            access_token_encrypted=self.encrypt(token_data["access_token"]),
            refresh_token_encrypted=self.encrypt(token_data["refresh_token"]),
            expires_at=expires_at,
            scopes=token_data.get("scope"),
        )

        self.tenant_repo.mark_disconnected(org_id, keep_tenant_id=connection["tenantId"])
        self.tenant_repo.upsert(
            org_id=org_id,
            xero_tenant_id=connection["tenantId"],
            xero_tenant_name=connection.get("tenantName"),
            xero_tenant_type=connection.get("tenantType"),
            xero_connection_id=connection.get("id"),
        )

        self.db.commit()

    def stage_selection(self, org_id: UUID, user_id: UUID, token_data: dict, connections: list[dict]) -> UUID:
        """Persist one pending selection without changing active credentials."""
        now = datetime.now(UTC)
        token_expires_at = now + timedelta(seconds=token_data.get("expires_in", 1800))
        selection_id = uuid4()
        credentials = {
            "access_token": token_data["access_token"],
            "refresh_token": token_data["refresh_token"],
            "scope": token_data.get("scope"),
        }
        self.pending_repo.put(
            org_id,
            user_id,
            selection_id,
            connections,
            self.encrypt(json.dumps(credentials)),
            token_expires_at,
            min(token_expires_at, now + XERO_SELECTION_LIFETIME),
        )
        self.db.commit()
        return selection_id

    def activate_selection(self, pending: XeroPendingConnection, connection: dict) -> None:
        """Use the locked selection and consume it in the same transaction as activation."""
        token_data = json.loads(self.decrypt(pending.credentials_encrypted))
        self.store_tokens(pending.org_id, token_data, connection, expires_at=pending.token_expires_at)

    # ------------------------------------------------------------------
    # Get a valid (auto-refreshed) access token
    # ------------------------------------------------------------------

    def get_valid_token(self, org_id: UUID) -> tuple[str, str]:
        """Return (access_token, xero_tenant_id). Auto-refreshes if near expiry."""
        token_record = self.token_repo.get(org_id)
        if not token_record:
            raise XeroTokenExpiredError("No Xero token found — connect Xero first.")

        now = datetime.now(UTC)
        expires_at = token_record.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)

        if now >= expires_at - timedelta(minutes=5):
            token_record = self._refresh_token(org_id, token_record)

        try:
            access_token = self.decrypt(token_record.access_token_encrypted)
        except Exception:
            raise XeroTokenExpiredError("Token decryption failed — reconnect Xero.")

        return access_token, token_record.xero_tenant_id

    def _refresh_token(self, org_id: UUID, token_record: XeroOAuthToken) -> XeroOAuthToken:
        previous_refresh_token = token_record.refresh_token_encrypted
        try:
            refresh_plain = self.decrypt(previous_refresh_token)
        except Exception:
            return self._reject_refresh(org_id, previous_refresh_token, "Refresh token decryption failed.")

        try:
            resp = requests.post(
                XERO_TOKEN_URL,
                data={"grant_type": "refresh_token", "refresh_token": refresh_plain},
                auth=(config.xero_client_id, config.xero_client_secret),
                timeout=15,
            )
            resp.raise_for_status()
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code in (400, 401):
                return self._reject_refresh(
                    org_id, previous_refresh_token, "Xero refresh token rejected — reconnect required."
                )
            raise

        token_data = resp.json()
        expires_at = datetime.now(UTC) + timedelta(seconds=token_data.get("expires_in", 1800))
        next_refresh_token = token_data.get("refresh_token") or refresh_plain
        updated = self.token_repo.update_after_refresh(
            org_id,
            previous_refresh_token,
            access_token_encrypted=self.encrypt(token_data["access_token"]),
            refresh_token_encrypted=self.encrypt(next_refresh_token),
            expires_at=expires_at,
            scopes=token_data.get("scope"),
        )
        self.db.commit()
        if updated:
            logger.info("xero_refresh_completed", org_id=str(org_id))
        return self._active_token_after_refresh(org_id)

    def _reject_refresh(self, org_id: UUID, previous_refresh_token: str, message: str) -> XeroOAuthToken:
        invalidated = self.token_repo.invalidate(org_id, previous_refresh_token=previous_refresh_token)
        self.db.commit()
        if invalidated:
            raise XeroTokenExpiredError(message)
        return self._active_token_after_refresh(org_id)

    def _active_token_after_refresh(self, org_id: UUID) -> XeroOAuthToken:
        # A rotation, selection or disconnect can win while the provider request is in flight.
        self.db.expire_all()
        token = self.token_repo.get(org_id)
        if token is None:
            raise XeroTokenExpiredError("No Xero token found — connect Xero first.")
        return token

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
            except Exception as exc:
                logger.warning("xero_revocation_failed", org_id=str(org_id), error_type=type(exc).__name__)

        self.pending_repo.clear(org_id)
        self.token_repo.invalidate(org_id)
        self.tenant_repo.mark_disconnected(org_id)
        self.db.commit()
