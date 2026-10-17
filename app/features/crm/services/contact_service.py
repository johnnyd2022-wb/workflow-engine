"""Sales contacts created and edited in Biz-E, and sending them to Xero.

Every Xero contact is pulled into Sales by XeroSyncService. This module covers the other
direction:

- A contact created in Biz-E (``source="bize"``) lives only in Biz-E until its Xero sync is on:
  its own ``sync_to_xero``, or the Sales default (``SalesTraceabilityConfig.sync_contacts_to_xero``)
  when it has no choice of its own. Turning sync on sends it to Xero; after that, edits follow.
- A contact that is in Xero (pulled from Xero, or a Biz-E contact already sent) has its Biz-E
  edits sent back to Xero, unless it is a Biz-E contact whose sync has been turned off.

The local save always commits first. A failed send never loses an edit: it is recorded on the
contact (``xero_push_status="failed"`` with the reason) for the page to show with a retry, and
the Xero pull leaves those fields alone until a send succeeds (see XeroSyncService).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.backend.event_writer import EventWriter
from app.core.utils.time import utc_now
from app.features.crm.models.sales_traceability_config import SalesTraceabilityConfig
from app.features.crm.models.xero_contact import XeroContact
from app.features.crm.repositories.xero_contact_repo import XeroContactRepository
from app.features.crm.repositories.xero_tenant_repo import XeroTenantRepository
from app.features.crm.repositories.xero_token_repo import XeroTokenRepository
from app.observability import get_logger

logger = get_logger(__name__)

# The contact details Biz-E edits and sends to Xero, with their length limits (Xero's own
# limits for name and email; the column sizes for the rest).
EDITABLE_FIELDS: dict[str, int] = {
    "name": 255,
    "first_name": 255,
    "last_name": 255,
    "email_address": 255,
    "phone_number": 50,
}
# Xero's two address types, and the parts of each Biz-E keeps (Xero's own length limits).
ADDRESS_TYPES = ("POBOX", "STREET")
ADDRESS_PARTS: dict[str, int] = {
    "line1": 500,
    "line2": 500,
    "line3": 500,
    "line4": 500,
    "city": 255,
    "region": 255,
    "postal_code": 50,
    "country": 50,
    "attention_to": 255,
}
# Everything Biz-E sends to Xero for a contact: the text details plus its addresses.
SYNCED_FIELDS: tuple[str, ...] = (*EDITABLE_FIELDS, "addresses")
CONTACT_WRITE_SCOPE = "accounting.contacts"


class ContactNotFoundError(LookupError):
    pass


class ContactSyncService:
    def __init__(self, db: Session):
        self.db = db
        self.contact_repo = XeroContactRepository(db)
        self.tenant_repo = XeroTenantRepository(db)
        self.token_repo = XeroTokenRepository(db)

    # ------------------------------------------------------------------
    # The Sales default
    # ------------------------------------------------------------------

    def sync_default(self, org_id: UUID) -> bool:
        row = self._config(org_id)
        return bool(row and row.sync_contacts_to_xero)

    def settings(self, org_id: UUID) -> dict[str, Any]:
        return {"sync_contacts_to_xero": self.sync_default(org_id), "xero": self.connection(org_id)}

    def set_sync_default(self, org_id: UUID, enabled: bool, *, actor_id: UUID | None = None) -> dict[str, Any]:
        """Turn the Sales default on or off. Turning it on sends every Biz-E contact that follows
        the default and is not yet in Xero; the result says how many went and how many failed."""
        row = self._config(org_id)
        before = bool(row and row.sync_contacts_to_xero)
        if row is None:
            row = SalesTraceabilityConfig(org_id=org_id)
            self.db.add(row)
        row.sync_contacts_to_xero = bool(enabled)
        self.db.flush()
        if before != bool(enabled):
            self._emit(
                org_id,
                "crm_contact_sync_default.updated",
                "crm_traceability_config",
                row.id,
                {"sync_contacts_to_xero": bool(enabled)},
                {"sync_contacts_to_xero": {"before": before, "after": bool(enabled)}},
                actor_id,
            )
        self.db.commit()
        sent = failed = 0
        if enabled:
            waiting = (
                self.db.query(XeroContact)
                .filter(
                    XeroContact.org_id == org_id,
                    XeroContact.source == "bize",
                    XeroContact.sync_to_xero.is_(None),
                    XeroContact.xero_contact_id.is_(None),
                )
                .order_by(XeroContact.name)
                .all()
            )
            for contact in waiting:
                if self._push(org_id, contact, actor_id=actor_id):
                    sent += 1
                else:
                    failed += 1
        return {**self.settings(org_id), "sent": sent, "failed": failed}

    # ------------------------------------------------------------------
    # One contact
    # ------------------------------------------------------------------

    def effective_sync(self, contact: XeroContact, default: bool | None = None) -> bool:
        """Whether Biz-E sends this contact's changes to Xero."""
        if contact.source != "bize":
            return True
        if contact.sync_to_xero is not None:
            return bool(contact.sync_to_xero)
        return self.sync_default(contact.org_id) if default is None else default

    def describe(self, contact: XeroContact, default: bool | None = None) -> dict[str, Any]:
        """The contact's Xero state as the Sales pages show it."""
        effective = self.effective_sync(contact, default)
        return {
            "source": contact.source,
            "in_xero": bool(contact.xero_contact_id),
            "sync_to_xero": contact.sync_to_xero,
            "follows_default": contact.source == "bize" and contact.sync_to_xero is None,
            "syncs": effective,
            "push_status": contact.xero_push_status,
            "push_error": contact.xero_push_error,
            "pushed_at": contact.xero_pushed_at.isoformat() if contact.xero_pushed_at else None,
        }

    def create_contact(
        self, org_id: UUID, data: dict[str, Any], *, actor_id: UUID | None = None
    ) -> tuple[XeroContact, dict[str, Any]]:
        fields = _clean_fields(data, require_name=True)
        if "addresses" in data:
            fields["addresses"] = _clean_addresses(data["addresses"], None)
        self._refuse_duplicate_name(org_id, fields["name"])
        sync_choice = data.get("sync_to_xero")
        if sync_choice is not None and not isinstance(sync_choice, bool):
            raise ValueError("sync_to_xero must be true, false or null")
        contact = XeroContact(
            org_id=org_id,
            source="bize",
            sync_to_xero=sync_choice,
            is_customer=True,
            is_supplier=False,
            **fields,
        )
        self.db.add(contact)
        self.db.flush()
        self._emit(org_id, "crm_contact.created", "crm_contact", contact.id, _snapshot(contact), None, actor_id)
        self.db.commit()
        if self.effective_sync(contact):
            self._push(org_id, contact, actor_id=actor_id)
        return contact, self.describe(contact)

    def update_contact(
        self, org_id: UUID, contact_id: UUID, data: dict[str, Any], *, actor_id: UUID | None = None
    ) -> tuple[XeroContact, dict[str, Any], dict[str, Any]]:
        """Save edited details; send the changed ones to Xero when this contact syncs.
        Returns the contact, its Xero state, and the fields that changed."""
        contact = self._get(org_id, contact_id)
        fields = _clean_fields(data, require_name=False)
        if "addresses" in data:
            fields["addresses"] = _clean_addresses(data["addresses"], contact.addresses)
        if "name" in fields and fields["name"].casefold() != (contact.name or "").casefold():
            self._refuse_duplicate_name(org_id, fields["name"], exclude=contact.id)
        before = _snapshot(contact)
        changed = {key: value for key, value in fields.items() if _current(contact, key) != value}
        for key, value in changed.items():
            setattr(contact, key, value)
        if changed:
            contact.updated_at = utc_now()
            self._emit(
                org_id,
                "crm_contact.updated",
                "crm_contact",
                contact.id,
                _snapshot(contact),
                {key: {"before": before.get(key), "after": value} for key, value in changed.items()},
                actor_id,
            )
            if self.effective_sync(contact):
                # Marked before the send so a pull that lands mid-send keeps these edits.
                contact.xero_push_status = "pending"
        self.db.commit()
        if changed and self.effective_sync(contact):
            self._push(org_id, contact, fields=list(changed), actor_id=actor_id)
        return contact, self.describe(contact), changed

    def set_contact_sync(
        self, org_id: UUID, contact_id: UUID, choice: bool | None, *, actor_id: UUID | None = None
    ) -> tuple[XeroContact, dict[str, Any]]:
        """A Biz-E contact's own Xero sync choice; None follows the Sales default."""
        if choice is not None and not isinstance(choice, bool):
            raise ValueError("sync_to_xero must be true, false or null")
        contact = self._get(org_id, contact_id)
        if contact.source != "bize":
            raise ValueError("Contacts from Xero always stay in step with Xero")
        before = contact.sync_to_xero
        contact.sync_to_xero = choice
        if before != choice:
            self._emit(
                org_id,
                "crm_contact.xero_sync_changed",
                "crm_contact",
                contact.id,
                {"sync_to_xero": choice},
                {"sync_to_xero": {"before": before, "after": choice}},
                actor_id,
            )
        self.db.commit()
        if self.effective_sync(contact) and (not contact.xero_contact_id or contact.xero_push_status == "failed"):
            self._push(org_id, contact, actor_id=actor_id)
        return contact, self.describe(contact)

    def retry(self, org_id: UUID, contact_id: UUID, *, actor_id: UUID | None = None):
        contact = self._get(org_id, contact_id)
        if not self.effective_sync(contact):
            raise ValueError("Turn on Xero sync for this contact first")
        self._push(org_id, contact, actor_id=actor_id)
        return contact, self.describe(contact)

    # ------------------------------------------------------------------
    # The Xero connection
    # ------------------------------------------------------------------

    def connection(self, org_id: UUID) -> dict[str, Any]:
        tenant = self.tenant_repo.get_connected(org_id)
        token = self.token_repo.get(org_id) if tenant else None
        scopes = (token.scopes or "").split() if token else []
        # Tokens stored before scopes were recorded have none listed; Xero decides on the call.
        can_write = bool(tenant) and (not scopes or CONTACT_WRITE_SCOPE in scopes)
        return {
            "connected": bool(tenant),
            "tenant_name": tenant.xero_tenant_name if tenant else None,
            "can_write_contacts": can_write,
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _push(
        self, org_id: UUID, contact: XeroContact, *, fields: list[str] | None = None, actor_id: UUID | None = None
    ) -> bool:
        """Send the contact to Xero: create it, or send the given fields (all editable fields when
        none are given, as after a failed send). Records the outcome; never raises."""
        from app.features.crm.services.xero_api_client import (
            XeroAPIClient,
            XeroInsufficientScopeError,
            _extract_exception_error_message,
        )
        from app.features.crm.services.xero_oauth_service import XeroTokenExpiredError

        tenant = self.tenant_repo.get_connected(org_id)
        error: str | None = None
        result = None
        if tenant is None:
            error = "Xero is not connected. Connect Xero in Sales settings, then try again."
        elif not self.connection(org_id)["can_write_contacts"]:
            error = "The Xero connection only allows reading contacts. Reconnect Xero, then try again."
        else:
            payload = {key: getattr(contact, key) or "" for key in (fields or EDITABLE_FIELDS)}
            if fields is None or "addresses" in fields:
                payload["addresses"] = _addresses(contact.addresses)
            payload["name"] = contact.name
            try:
                client = XeroAPIClient(self.db, org_id)
                if contact.xero_contact_id:
                    result = client.update_contact(contact.xero_contact_id, payload)
                else:
                    result = client.create_contact(payload, idempotency_key=f"bize-contact-{contact.id}")
            except XeroInsufficientScopeError:
                error = "The Xero connection only allows reading contacts. Reconnect Xero, then try again."
            except XeroTokenExpiredError:
                error = "The Xero connection has expired. Reconnect Xero, then try again."
            except ValueError as exc:  # Xero's validation errors, e.g. a name already in use there
                error = f"Xero refused the contact: {exc}"
            except Exception as exc:  # noqa: BLE001 - recorded on the contact for a retry
                error = _extract_exception_error_message(exc) or "Xero could not be reached."
                logger.warning("crm_contact_xero_push_failed", org_id=str(org_id), contact_id=str(contact.id))

        if error is None and result is not None:
            if not contact.xero_contact_id:
                contact.xero_contact_id = str(result.contact_id)
                contact.xero_tenant_id = tenant.xero_tenant_id
            if getattr(result, "updated_date_utc", None):
                contact.xero_updated_at = result.updated_date_utc
            contact.xero_push_status = "synced"
            contact.xero_push_error = None
            contact.xero_pushed_at = utc_now()
            contact.last_synced_at = contact.xero_pushed_at
            event = "crm_contact.sent_to_xero"
        else:
            contact.xero_push_status = "failed"
            contact.xero_push_error = error
            event = "crm_contact.xero_send_failed"
        self._emit(
            org_id,
            event,
            "crm_contact",
            contact.id,
            {"xero_contact_id": contact.xero_contact_id, "error": contact.xero_push_error, "fields": fields},
            None,
            actor_id,
        )
        self.db.commit()
        return error is None

    def _config(self, org_id: UUID) -> SalesTraceabilityConfig | None:
        return self.db.query(SalesTraceabilityConfig).filter(SalesTraceabilityConfig.org_id == org_id).first()

    def _get(self, org_id: UUID, contact_id: UUID) -> XeroContact:
        contact = self.contact_repo.get_by_id(contact_id, org_id)
        if contact is None:
            logger.warning(
                "access_denied",
                reason="contact_id_not_found_or_cross_org",
                feature="crm",
                org_id=str(org_id),
                ref_kind="contact_id",
                ref_id=str(contact_id),
            )
            raise ContactNotFoundError("Customer not found")
        return contact

    def _refuse_duplicate_name(self, org_id: UUID, name: str, exclude: UUID | None = None) -> None:
        # Xero refuses two contacts with the same name, so Biz-E does too.
        query = self.db.query(XeroContact.id).filter(
            XeroContact.org_id == org_id, func.lower(XeroContact.name) == name.casefold()
        )
        if exclude is not None:
            query = query.filter(XeroContact.id != exclude)
        if query.first() is not None:
            raise ValueError(f"A contact called {name} already exists")

    def _emit(self, org_id, event_type, entity_type, entity_id, payload, diff, actor_id) -> None:
        EventWriter(self.db, org_id).emit(
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=payload,
            diff=diff,
            actor_id=actor_id,
        )


def _clean_fields(data: dict[str, Any], *, require_name: bool) -> dict[str, str | None]:
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object")
    unknown = set(data) - set(EDITABLE_FIELDS) - {"sync_to_xero", "addresses"}
    if unknown:
        raise ValueError("Unknown field(s): " + ", ".join(sorted(unknown)))
    fields: dict[str, str | None] = {}
    for key, limit in EDITABLE_FIELDS.items():
        if key not in data:
            continue
        value = data[key]
        if value is not None and not isinstance(value, str):
            raise ValueError(f"{key} must be text")
        value = (value or "").strip() or None
        if value is not None and len(value) > limit:
            raise ValueError(f"{key} must be at most {limit} characters")
        fields[key] = value
    if require_name or "name" in fields:
        if not fields.get("name"):
            raise ValueError("A contact needs a name")
    email = fields.get("email_address")
    if email and ("@" not in email or email.startswith("@") or email.endswith("@") or " " in email):
        raise ValueError("Enter an email address like name@example.com")
    return fields


def _addresses(raw) -> list[dict[str, Any]]:
    """Stored addresses in one shape: one per Xero type, every part present, POBOX first."""
    by_type = {str(item.get("type") or "").upper(): item for item in (raw or []) if isinstance(item, dict)}
    shaped = []
    for kind in ADDRESS_TYPES:
        if kind in by_type:
            item = by_type[kind]
            shaped.append({"type": kind, **{part: (item.get(part) or None) for part in ADDRESS_PARTS}})
    return shaped


def _clean_addresses(value: Any, existing) -> list[dict[str, Any]]:
    """Addresses sent from the page, merged over the stored ones: a type the page leaves out
    keeps its stored value, and parts the page does not edit (lines 3 and 4, attention to)
    are kept from the stored copy unless sent."""
    if not isinstance(value, list):
        raise ValueError("addresses must be a list")
    current = {item["type"]: item for item in _addresses(existing)}
    seen = set()
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("Each address must be an object")
        kind = str(item.get("type") or "").upper()
        if kind not in ADDRESS_TYPES:
            raise ValueError("Address type must be POBOX (postal) or STREET")
        if kind in seen:
            raise ValueError("Send at most one postal and one street address")
        seen.add(kind)
        unknown = set(item) - set(ADDRESS_PARTS) - {"type"}
        if unknown:
            raise ValueError("Unknown address field(s): " + ", ".join(sorted(unknown)))
        merged = dict(current.get(kind) or {"type": kind, **dict.fromkeys(ADDRESS_PARTS)})
        for part, limit in ADDRESS_PARTS.items():
            if part not in item:
                continue
            text = item[part]
            if text is not None and not isinstance(text, str):
                raise ValueError(f"Address {part} must be text")
            text = (text or "").strip() or None
            if text is not None and len(text) > limit:
                raise ValueError(f"Address {part} must be at most {limit} characters")
            merged[part] = text
        current[kind] = merged
    return [current[kind] for kind in ADDRESS_TYPES if kind in current]


def _current(contact: XeroContact, key: str):
    if key == "addresses":
        return _addresses(contact.addresses)
    return getattr(contact, key) or None


def _snapshot(contact: XeroContact) -> dict[str, Any]:
    return {key: _current(contact, key) for key in SYNCED_FIELDS}
