"""XeroAPIClient — thin wrapper around xero-python SDK with rate limiting, retry, and pagination."""

import logging
import time
from collections import deque
from datetime import date, datetime, timezone
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


class XeroInsufficientScopeError(Exception):
    """Raised when the connected Xero token is missing required scopes."""


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

        # The SDK's OAuth2Token is populated at request time via the getter.
        # We manage token storage and refresh ourselves, so the saver is a no-op.
        token_obj = OAuth2Token()
        _token_dict = {
            "access_token": access_token,
            "refresh_token": "",
            "token_type": "Bearer",
            "expires_in": 1800,
            "scope": "",
            "expires_at": None,
        }
        api_client = ApiClient(
            configuration=Configuration(oauth2_token=token_obj),
            oauth2_token_getter=lambda: _token_dict,
            oauth2_token_saver=lambda _: None,
        )
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
                code = _extract_status_code(e)

                if _is_insufficient_scope(e):
                    raise XeroInsufficientScopeError(
                        "Connected Xero permissions are missing required invoice scope. "
                        "Reconnect Xero to update permissions."
                    ) from e

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

    def get_contact_payment_terms(self, contact_xero_id: str) -> dict | None:
        """Fetch a single contact's payment terms from Xero."""
        from xero_python.accounting import AccountingApi

        api = AccountingApi(self._get_api_client())
        tenant_id = self._xero_tenant_id
        result = self._call_with_retry(api.get_contact, tenant_id, contact_xero_id)
        contacts = getattr(result, "contacts", None) or []
        if not contacts:
            return None
        contact = contacts[0]
        raw = getattr(contact, "payment_terms", None)
        return _normalise_payment_terms(raw)

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

        kwargs: dict = {"statuses": ["DRAFT", "SUBMITTED", "AUTHORISED", "PAID", "VOIDED", "DELETED"]}
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

    def create_invoice(
        self,
        *,
        contact_xero_id: str,
        invoice_date: date,
        due_date: date | None,
        line_items: list[dict],
        status: str = "DRAFT",
    ):
        """Create an ACCREC invoice in Xero and return the created invoice model."""
        from xero_python.accounting import AccountingApi
        from xero_python.accounting.models import Contact, Invoice, Invoices, LineItem

        api = AccountingApi(self._get_api_client())
        tenant_id = self._xero_tenant_id

        invoice_status = (status or "DRAFT").strip().upper()
        if invoice_status not in {"DRAFT", "AUTHORISED"}:
            raise ValueError("status must be DRAFT or AUTHORISED")

        li_models = []
        for item in line_items:
            li_models.append(
                LineItem(
                    description=item.get("description"),
                    item_code=item.get("item_code"),
                    quantity=item.get("quantity"),
                    unit_amount=item.get("unit_amount"),
                    tax_type=item.get("tax_type"),
                    account_code=item.get("account_code"),
                )
            )

        invoice_model = Invoice(
            type="ACCREC",
            status=invoice_status,
            contact=Contact(contact_id=contact_xero_id),
            date=invoice_date,
            due_date=due_date,
            line_items=li_models,
        )
        payload = Invoices(invoices=[invoice_model])

        def _create():
            try:
                return api.create_invoices(tenant_id, invoices=payload, summarize_errors=False)
            except TypeError:
                return api.create_invoices(tenant_id, payload, summarize_errors=False)

        result = self._call_with_retry(_create)
        invoices = getattr(result, "invoices", None) or []
        if not invoices:
            raise RuntimeError("Xero did not return a created invoice")
        return invoices[0]

    def authorise_invoice(self, *, xero_invoice_id: str):
        """Authorise an existing ACCREC invoice in Xero."""
        from xero_python.accounting import AccountingApi
        from xero_python.accounting.models import Invoice, Invoices

        api = AccountingApi(self._get_api_client())
        tenant_id = self._xero_tenant_id

        payload = Invoices(invoices=[Invoice(status="AUTHORISED")])

        def _authorise():
            try:
                return api.update_invoice(tenant_id, xero_invoice_id, invoices=payload)
            except TypeError:
                return api.update_invoice(tenant_id, xero_invoice_id, payload)

        result = self._call_with_retry(_authorise)
        invoices = getattr(result, "invoices", None) or []
        if not invoices:
            raise RuntimeError("Xero did not return an updated invoice")
        return invoices[0]


def _normalise_payment_terms(raw) -> dict | None:
    if not raw:
        return None

    def _term_obj(obj):
        if not obj:
            return None
        day = getattr(obj, "day", None)
        if day is None:
            day = getattr(obj, "Day", None)
        month = getattr(obj, "month", None)
        if month is None:
            month = getattr(obj, "Month", None)
        type_value = getattr(obj, "type", None)
        if type_value is None:
            type_value = getattr(obj, "Type", None)
        if hasattr(type_value, "value"):
            type_value = type_value.value
        return {
            "day": int(day) if day is not None else None,
            "month": int(month) if month is not None else None,
            "type": str(type_value) if type_value else None,
        }

    sales = _term_obj(getattr(raw, "sales", None) or getattr(raw, "Sales", None))
    bills = _term_obj(getattr(raw, "bills", None) or getattr(raw, "Bills", None))
    if not sales and not bills:
        return None
    return {"sales": sales, "bills": bills}


def _extract_status_code(error: Exception) -> int | None:
    for attr in ("status", "status_code", "statusCode", "code"):
        val = getattr(error, attr, None)
        if isinstance(val, int):
            return val
        if isinstance(val, str) and val.isdigit():
            return int(val)
    http_resp = getattr(error, "http_resp", None)
    if http_resp is not None:
        val = getattr(http_resp, "status", None)
        if isinstance(val, int):
            return val
    resp = getattr(error, "response", None)
    if resp is not None:
        val = getattr(resp, "status_code", None)
        if isinstance(val, int):
            return val
    return None


def _is_insufficient_scope(error: Exception) -> bool:
    text = str(error).lower()
    if "insufficient_scope" in text:
        return True
    http_resp = getattr(error, "http_resp", None)
    if http_resp is not None:
        headers = getattr(http_resp, "headers", None)
        if headers:
            try:
                for key, value in headers.items():
                    if str(key).lower() == "www-authenticate" and "insufficient_scope" in str(value).lower():
                        return True
            except Exception:
                pass
    return False
