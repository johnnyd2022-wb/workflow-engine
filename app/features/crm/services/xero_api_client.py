"""XeroAPIClient — thin wrapper around xero-python SDK with rate limiting, retry, and pagination."""

import logging
import time
from collections import deque
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from app.features.crm.services.xero_oauth_service import XeroOAuthService

logger = logging.getLogger(__name__)

# Xero rate limit: 60 calls per 60-second rolling window
_RATE_LIMIT_CALLS = 60
_RATE_LIMIT_WINDOW = 62  # slight buffer

# Retry config
_MAX_RETRIES = 3
_RETRY_BACKOFF = [2, 5, 10]


class XeroRateLimiter:
    """Thread-local rolling window rate limiter (60 calls/min)."""

    def __init__(self):
        self._timestamps: deque = deque()

    def wait_if_needed(self) -> None:
        now = time.monotonic()
        # Drop timestamps older than the window
        while self._timestamps and now - self._timestamps[0] > _RATE_LIMIT_WINDOW:
            self._timestamps.popleft()

        if len(self._timestamps) >= _RATE_LIMIT_CALLS:
            sleep_for = _RATE_LIMIT_WINDOW - (now - self._timestamps[0]) + 0.5
            if sleep_for > 0:
                logger.debug("Xero rate limit — sleeping %.1fs", sleep_for)
                time.sleep(sleep_for)

        self._timestamps.append(time.monotonic())


_rate_limiter = XeroRateLimiter()


class XeroAPIClient:
    """Provides high-level, paginated access to Xero Accounting API."""

    def __init__(self, db: Session, org_id: UUID):
        self.db = db
        self.org_id = org_id
        self._oauth_service = XeroOAuthService(db)
        self._api_client = None
        self._xero_tenant_id: str | None = None

    def _get_api_client(self):
        """Lazily build an authenticated xero-python api_client."""
        if self._api_client:
            return self._api_client

        from xero_python.api_client import ApiClient
        from xero_python.api_client.configuration import Configuration
        from xero_python.api_client.oauth2 import OAuth2Token

        access_token, tenant_id = self._oauth_service.get_valid_token(self.org_id)
        self._xero_tenant_id = tenant_id

        api_client = ApiClient(configuration=Configuration())
        api_client.set_oauth2_token(OAuth2Token(access_token=access_token))
        self._api_client = api_client
        return api_client

    def _refresh_client(self) -> None:
        """Force token refresh and rebuild client."""
        self._api_client = None
        self._get_api_client()

    def _call_with_retry(self, fn, *args, **kwargs):
        """Execute fn(*args, **kwargs) with rate limiting and retry."""
        for attempt in range(_MAX_RETRIES):
            _rate_limiter.wait_if_needed()
            try:
                return fn(*args, **kwargs)
            except Exception as e:
                code = getattr(e, "status", None)

                if code == 429:
                    wait = _RETRY_BACKOFF[min(attempt, len(_RETRY_BACKOFF) - 1)]
                    logger.warning("Xero 429 rate limit (attempt %d) — sleeping %ds", attempt + 1, wait)
                    time.sleep(wait)
                    continue

                if code == 401 and attempt == 0:
                    logger.info("Xero 401 — refreshing token and retrying")
                    self._refresh_client()
                    continue

                if code in (500, 503):
                    wait = _RETRY_BACKOFF[min(attempt, len(_RETRY_BACKOFF) - 1)]
                    logger.warning("Xero %s server error (attempt %d) — sleeping %ds", code, attempt + 1, wait)
                    time.sleep(wait)
                    continue

                raise

        raise RuntimeError("Xero API call failed after max retries")

    # ------------------------------------------------------------------
    # Contacts
    # ------------------------------------------------------------------

    def get_all_contacts(self, modified_after: datetime | None = None) -> list:
        """Return all contacts, paginating automatically."""
        from xero_python.accounting import AccountingApi

        api = AccountingApi(self._get_api_client())
        tenant_id = self._xero_tenant_id
        contacts = []
        page = 1

        kwargs: dict = {"include_archived": True}
        if modified_after:
            if modified_after.tzinfo is None:
                modified_after = modified_after.replace(tzinfo=timezone.utc)
            kwargs["if_modified_since"] = modified_after

        while True:
            result = self._call_with_retry(api.get_contacts, tenant_id, page=page, **kwargs)
            batch = result.contacts or []
            contacts.extend(batch)
            logger.debug("Contacts page %d: %d records", page, len(batch))
            if len(batch) < 100:
                break
            page += 1

        return contacts

    # ------------------------------------------------------------------
    # Invoices
    # ------------------------------------------------------------------

    def get_all_invoices(self, modified_after: datetime | None = None) -> list:
        """Return all ACCREC invoices, paginating automatically."""
        from xero_python.accounting import AccountingApi

        api = AccountingApi(self._get_api_client())
        tenant_id = self._xero_tenant_id
        invoices = []
        page = 1

        kwargs: dict = {"statuses": ["DRAFT", "SUBMITTED", "AUTHORISED", "PAID", "VOIDED"]}
        if modified_after:
            if modified_after.tzinfo is None:
                modified_after = modified_after.replace(tzinfo=timezone.utc)
            kwargs["if_modified_since"] = modified_after

        while True:
            result = self._call_with_retry(api.get_invoices, tenant_id, page=page, where='Type=="ACCREC"', **kwargs)
            batch = result.invoices or []
            invoices.extend(batch)
            logger.debug("Invoices page %d: %d records", page, len(batch))
            if len(batch) < 100:
                break
            page += 1

        return invoices
