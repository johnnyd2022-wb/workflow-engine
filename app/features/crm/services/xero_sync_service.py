"""XeroSyncService — orchestrates contact and invoice sync from Xero."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.backend.event_writer import EventWriter
from app.features.crm.models.xero_contact import XeroContact
from app.features.crm.repositories.xero_contact_repo import XeroContactRepository
from app.features.crm.repositories.xero_credit_note_repo import XeroCreditNoteRepository
from app.features.crm.repositories.xero_invoice_repo import XeroInvoiceRepository
from app.features.crm.repositories.xero_sync_job_repo import XeroSyncJobRepository
from app.features.crm.repositories.xero_tenant_repo import XeroTenantRepository
from app.features.crm.services.contact_service import SYNCED_FIELDS
from app.features.crm.services.xero_api_client import XeroAPIClient
from app.features.crm.services.xero_oauth_service import XeroTokenExpiredError
from app.observability import get_logger, start_span

logger = get_logger(__name__)

# An incremental sync asks Xero for records modified after the previous sync's start, less this
# margin for clock differences between us and Xero. Pulling a record twice is harmless: contact
# and invoice upserts and FIFO matching are idempotent. Missing one is not.
RESUME_OVERLAP = timedelta(minutes=5)


@dataclass
class SyncResult:
    contacts_synced: int = 0
    invoices_synced: int = 0
    credit_notes_synced: int = 0
    sales_allocated: int = 0
    sales_unmapped: int = 0
    sales_insufficient_stock: int = 0
    purchases_synced: int = 0
    purchases_status: str | None = None  # live-cogs 8.1b: synced | not_enabled | needs_reconnect | failed
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return not self.errors

    @property
    def partial(self) -> bool:
        return bool(self.errors) and (
            self.contacts_synced > 0
            or self.invoices_synced > 0
            or self.credit_notes_synced > 0
            or self.purchases_synced > 0
            or self.purchases_status in ("failed", "synced")
        )


class XeroSyncService:
    """Syncs Xero contacts and invoices into local CRM tables.

    Designed to be called synchronously in Phase 1. Celery-ready: no Flask
    context dependencies — only db, org_id, tenant_id.
    """

    def __init__(self, db: Session):
        self.db = db
        self.contact_repo = XeroContactRepository(db)
        self.invoice_repo = XeroInvoiceRepository(db)
        self.credit_note_repo = XeroCreditNoteRepository(db)
        self.tenant_repo = XeroTenantRepository(db)
        self.sync_job_repo = XeroSyncJobRepository(db)

    def full_sync(self, org_id: UUID, triggered_by: str = "manual") -> SyncResult:
        """Run a full contacts + invoices sync."""
        with start_span(
            "xero.sync",
            attributes={"org_id": str(org_id), "sync_type": "full", "triggered_by": triggered_by},
        ):
            tenant = self.tenant_repo.get_connected(org_id)
            if not tenant:
                raise ValueError("No connected Xero tenant for this org.")

            started_at = datetime.now(UTC)
            job = self.sync_job_repo.create(org_id, tenant.xero_tenant_id, "full", triggered_by)
            self.db.commit()

            result = SyncResult()
            api_client = XeroAPIClient(self.db, org_id)

            try:
                with start_span(
                    "xero.sync.contacts",
                    attributes={"org_id": str(org_id), "sync_type": "full"},
                ):
                    contacts_result = self._sync_contacts(api_client, org_id, tenant.xero_tenant_id, incremental=False)
                result.contacts_synced = contacts_result.contacts_synced
                result.errors.extend(contacts_result.errors)
            except XeroTokenExpiredError:
                raise
            except Exception as e:
                logger.exception("xero_contact_sync_failed", org_id=str(org_id))
                result.errors.append(f"Contact sync error: {e}")

            try:
                with start_span(
                    "xero.sync.invoices",
                    attributes={"org_id": str(org_id), "sync_type": "full"},
                ):
                    invoices_result = self._sync_invoices(
                        api_client, org_id, tenant.xero_tenant_id, sync_job_id=job.id, incremental=False
                    )
                result.invoices_synced = invoices_result.invoices_synced
                result.sales_allocated = invoices_result.sales_allocated
                result.sales_unmapped = invoices_result.sales_unmapped
                result.sales_insufficient_stock = invoices_result.sales_insufficient_stock
                result.errors.extend(invoices_result.errors)
            except XeroTokenExpiredError:
                raise
            except Exception as e:
                logger.exception("xero_invoice_sync_failed", org_id=str(org_id))
                result.errors.append(f"Invoice sync error: {e}")

            try:
                with start_span("xero.sync.credit_notes", attributes={"org_id": str(org_id), "sync_type": "full"}):
                    credit_result = self._sync_credit_notes(
                        api_client, org_id, tenant.xero_tenant_id, incremental=False
                    )
                result.credit_notes_synced = credit_result.credit_notes_synced
                result.errors.extend(credit_result.errors)
            except XeroTokenExpiredError:
                raise
            except Exception as e:
                logger.exception("xero_credit_note_sync_failed", org_id=str(org_id))
                result.errors.append(f"Credit note sync error: {e}")

            self._run_purchases(api_client, org_id, tenant.xero_tenant_id, result, started_at=started_at)
            self._record_purchases(job.id, org_id, result)
            self._finalise_job(job.id, org_id, result, started_at=started_at)
            return result

    def incremental_sync(self, org_id: UUID, triggered_by: str = "manual") -> SyncResult:
        """Sync only records modified since last successful sync."""
        with start_span(
            "xero.sync",
            attributes={"org_id": str(org_id), "sync_type": "incremental", "triggered_by": triggered_by},
        ):
            tenant = self.tenant_repo.get_connected(org_id)
            if not tenant:
                raise ValueError("No connected Xero tenant for this org.")

            modified_after = tenant.last_successful_sync_at
            started_at = datetime.now(UTC)
            job = self.sync_job_repo.create(org_id, tenant.xero_tenant_id, "incremental", triggered_by)
            self.db.commit()

            result = SyncResult()
            api_client = XeroAPIClient(self.db, org_id)

            try:
                with start_span(
                    "xero.sync.contacts",
                    attributes={"org_id": str(org_id), "sync_type": "incremental"},
                ):
                    r = self._sync_contacts(
                        api_client, org_id, tenant.xero_tenant_id, incremental=True, modified_after=modified_after
                    )
                result.contacts_synced = r.contacts_synced
                result.errors.extend(r.errors)
            except Exception as e:
                logger.exception("xero_incremental_contact_sync_failed", org_id=str(org_id))
                result.errors.append(str(e))

            try:
                with start_span(
                    "xero.sync.credit_notes", attributes={"org_id": str(org_id), "sync_type": "incremental"}
                ):
                    r = self._sync_credit_notes(
                        api_client,
                        org_id,
                        tenant.xero_tenant_id,
                        incremental=True,
                        modified_after=modified_after,
                    )
                result.credit_notes_synced = r.credit_notes_synced
                result.errors.extend(r.errors)
            except Exception as e:
                logger.exception("xero_incremental_credit_note_sync_failed", org_id=str(org_id))
                result.errors.append(str(e))

            try:
                with start_span(
                    "xero.sync.invoices",
                    attributes={"org_id": str(org_id), "sync_type": "incremental"},
                ):
                    r = self._sync_invoices(
                        api_client,
                        org_id,
                        tenant.xero_tenant_id,
                        sync_job_id=job.id,
                        incremental=True,
                        modified_after=modified_after,
                    )
                result.invoices_synced = r.invoices_synced
                result.sales_allocated = r.sales_allocated
                result.sales_unmapped = r.sales_unmapped
                result.sales_insufficient_stock = r.sales_insufficient_stock
                result.errors.extend(r.errors)
            except Exception as e:
                logger.exception("xero_incremental_invoice_sync_failed", org_id=str(org_id))
                result.errors.append(str(e))

            self._run_purchases(api_client, org_id, tenant.xero_tenant_id, result, started_at=started_at)
            self._record_purchases(job.id, org_id, result)
            self._finalise_job(job.id, org_id, result, started_at=started_at)
            return result

    # ------------------------------------------------------------------
    # Internal: contacts
    # ------------------------------------------------------------------

    def _sync_contacts(
        self,
        api_client: XeroAPIClient,
        org_id: UUID,
        tenant_id: str,
        incremental: bool = False,
        modified_after: datetime | None = None,
    ) -> SyncResult:
        result = SyncResult()
        contacts = api_client.get_all_contacts(modified_after=modified_after if incremental else None)
        logger.info("xero_contacts_sync_started", org_id=str(org_id), contacts_count=len(contacts))

        for xc in contacts:
            try:
                phones = xc.phones or []
                phone_number = next(
                    (p.phone_number for p in phones if getattr(p, "phone_type", None) == "DEFAULT" and p.phone_number),
                    None,
                )

                addresses = []
                for a in xc.addresses or []:
                    addresses.append(
                        {
                            "type": getattr(a, "address_type", None),
                            "line1": getattr(a, "address_line1", None),
                            "line2": getattr(a, "address_line2", None),
                            "line3": getattr(a, "address_line3", None),
                            "line4": getattr(a, "address_line4", None),
                            "attention_to": getattr(a, "attention_to", None),
                            "city": getattr(a, "city", None),
                            "region": getattr(a, "region", None),
                            "postal_code": getattr(a, "postal_code", None),
                            "country": getattr(a, "country", None),
                        }
                    )

                payment_terms = _serialise_xero_payment_terms(getattr(xc, "payment_terms", None))

                xero_updated_at = None
                if xc.updated_date_utc:
                    xero_updated_at = xc.updated_date_utc

                xero_contact_id = str(xc.contact_id)
                name = xc.name or "(No name)"
                fields = {
                    "first_name": xc.first_name,
                    "last_name": xc.last_name,
                    "email_address": xc.email_address,
                    "phone_number": phone_number,
                    "addresses": addresses or None,
                    "payment_terms": payment_terms,
                    "tax_number": getattr(xc, "tax_number", None),
                    "account_number": xc.account_number,
                    "contact_status": str(xc.contact_status) if xc.contact_status else None,
                    "is_customer": bool(xc.is_customer),
                    "is_supplier": bool(xc.is_supplier),
                    "xero_updated_at": xero_updated_at,
                }
                # Each record in its own savepoint: one the database rejects rolls back alone
                # instead of failing every record after it, and the invoice sync with them.
                with self.db.begin_nested():
                    existing = self.contact_repo.get_by_xero_id(xero_contact_id, org_id)
                    if existing is None:
                        existing = self._link_contact_made_in_bize(org_id, name, xero_contact_id, tenant_id)
                    if existing is not None and existing.xero_push_status in ("pending", "failed"):
                        # Biz-E holds edits Xero has not seen yet; keep them until a send succeeds.
                        for key in SYNCED_FIELDS:
                            fields.pop(key, None)
                        name = existing.name
                    self.contact_repo.upsert(
                        org_id=org_id,
                        xero_contact_id=xero_contact_id,
                        xero_tenant_id=tenant_id,
                        name=name,
                        **fields,
                    )
                    self.db.flush()
                result.contacts_synced += 1
            except Exception as e:
                logger.warning(
                    "xero_contact_sync_record_failed",
                    contact_id=str(getattr(xc, "contact_id", "?")),
                    error=str(e),
                )
                result.errors.append(f"contact {getattr(xc, 'contact_id', '?')}: {e}")

        # Flush after all contacts so FK lookups work for invoices
        self.db.flush()
        return result

    def _link_contact_made_in_bize(self, org_id: UUID, name: str, xero_contact_id: str, tenant_id: str):
        """A Biz-E contact not yet sent to Xero that someone also made in Xero by hand: link the
        two by name (Xero names are unique) instead of pulling in a second copy. Only an exact,
        unambiguous match links; anything else arrives as a new contact."""
        matches = (
            self.db.query(XeroContact)
            .filter(
                XeroContact.org_id == org_id,
                XeroContact.source == "bize",
                XeroContact.xero_contact_id.is_(None),
                func.lower(XeroContact.name) == name.casefold(),
            )
            .limit(2)
            .all()
        )
        if len(matches) != 1:
            return None
        contact = matches[0]
        contact.xero_contact_id = xero_contact_id
        contact.xero_tenant_id = tenant_id
        # The upsert that follows looks the contact up by its Xero id; flush so it finds this row.
        self.db.flush()
        logger.info("xero_contact_linked_by_name", org_id=str(org_id), contact_id=str(contact.id))
        return contact

    # ------------------------------------------------------------------
    # Internal: invoices
    # ------------------------------------------------------------------

    def _sync_invoices(
        self,
        api_client: XeroAPIClient,
        org_id: UUID,
        tenant_id: str,
        incremental: bool = False,
        modified_after: datetime | None = None,
        *,
        sync_job_id: UUID | None = None,
    ) -> SyncResult:
        result = SyncResult()
        invoices = api_client.get_all_invoices(modified_after=modified_after if incremental else None)
        logger.info("xero_invoices_sync_started", org_id=str(org_id), invoices_count=len(invoices))
        seen_invoice_ids: set[str] = set()

        for xi in invoices:
            try:
                xero_invoice_id = str(xi.invoice_id)
                seen_invoice_ids.add(xero_invoice_id)
                xero_contact_id = str(xi.contact.contact_id) if xi.contact and xi.contact.contact_id else None
                # The invoice and its line items in one savepoint: saved whole or not at all, and
                # a record the database rejects doesn't fail the rest of the sync.
                with self.db.begin_nested():
                    contact = self.contact_repo.get_by_xero_id(xero_contact_id, org_id) if xero_contact_id else None

                    inv = self.invoice_repo.upsert_invoice(
                        org_id=org_id,
                        xero_invoice_id=xero_invoice_id,
                        xero_tenant_id=tenant_id,
                        contact_id=contact.id if contact else None,
                        xero_contact_id=xero_contact_id,
                        invoice_number=xi.invoice_number,
                        reference=xi.reference,
                        invoice_type=str(xi.type) if xi.type else None,
                        status=str(xi.status) if xi.status else None,
                        sub_total=xi.sub_total,
                        total_tax=xi.total_tax,
                        total=xi.total,
                        amount_due=xi.amount_due,
                        amount_paid=xi.amount_paid,
                        currency_code=xi.currency_code.value if xi.currency_code else "NZD",
                        date=xi.date,
                        due_date=xi.due_date,
                        fully_paid_on_date=xi.fully_paid_on_date,
                        xero_updated_at=xi.updated_date_utc,
                    )

                    # Replace line items (idempotent — delete all then recreate)
                    line_items = []
                    for li in xi.line_items or []:
                        tracking = None
                        if li.tracking:
                            tracking = [{"name": t.name, "option": t.option} for t in li.tracking]

                        line_items.append(
                            {
                                "xero_line_item_id": str(li.line_item_id) if li.line_item_id else None,
                                "description": li.description,
                                "item_code": li.item_code,
                                "quantity": li.quantity,
                                "unit_amount": li.unit_amount,
                                "line_amount": li.line_amount,
                                "account_code": li.account_code,
                                "tax_type": li.tax_type,
                                "tax_amount": li.tax_amount,
                                "discount_rate": li.discount_rate,
                                "tracking": tracking,
                            }
                        )

                    self.invoice_repo.replace_line_items(inv.id, org_id, line_items)
                    self.db.flush()
                result.invoices_synced += 1

            except Exception as e:
                logger.warning(
                    "xero_invoice_sync_record_failed",
                    invoice_id=str(getattr(xi, "invoice_id", "?")),
                    error=str(e),
                )
                result.errors.append(f"invoice {getattr(xi, 'invoice_id', '?')}: {e}")

        if not incremental:
            deleted_count = self.invoice_repo.mark_missing_as_deleted(org_id, tenant_id, seen_invoice_ids)
            if deleted_count:
                logger.info("xero_sync_marked_deleted", org_id=str(org_id), deleted_count=deleted_count)

        self.db.flush()
        from app.features.crm.services.sales_traceability_service import SalesTraceabilityService

        allocation_summary = SalesTraceabilityService(self.db).reconcile_org(org_id, sync_job_id=sync_job_id)
        result.sales_allocated = allocation_summary.get("allocated", 0)
        result.sales_unmapped = allocation_summary.get("unmapped", 0)
        result.sales_insufficient_stock = allocation_summary.get("insufficient_stock", 0)
        return result

    def _sync_credit_notes(
        self,
        api_client: XeroAPIClient,
        org_id: UUID,
        tenant_id: str,
        incremental: bool = False,
        modified_after: datetime | None = None,
    ) -> SyncResult:
        from app.features.crm.models.product_mapping import ProductMapping
        from app.features.crm.repositories.sales_traceability_repo import SalesTraceabilityConfigRepository
        from app.features.crm.services.sales_traceability_service import SalesTraceabilityService

        result = SyncResult()
        credit_notes = api_client.fetch_all_credit_notes(modified_after=modified_after if incremental else None)
        logger.info("xero_credit_notes_sync_started", org_id=str(org_id), credit_notes_count=len(credit_notes))
        seen_ids: set[str] = set()
        config = SalesTraceabilityConfigRepository(self.db).get_for_org(org_id)
        strict = True if config is None else bool(config.strict_mapping)
        mappings = (
            self.db.query(ProductMapping)
            .filter(ProductMapping.org_id == org_id, ProductMapping.is_active.is_(True))
            .order_by(ProductMapping.id.asc())
            .all()
        )

        for remote in credit_notes:
            remote_id = getattr(remote, "credit_note_id", None)
            if not remote_id:
                result.errors.append("credit note missing CreditNoteID")
                continue
            xero_id = str(remote_id)
            seen_ids.add(xero_id)
            try:
                with self.db.begin_nested():
                    currency = getattr(remote, "currency_code", None)
                    currency = getattr(currency, "value", currency) or "NZD"
                    status = getattr(remote, "status", "")
                    status = str(getattr(status, "value", status) or "").upper()
                    note = self.credit_note_repo.upsert(
                        org_id,
                        tenant_id,
                        xero_id,
                        number=getattr(remote, "credit_note_number", None),
                        contact=getattr(getattr(remote, "contact", None), "name", None),
                        date=getattr(remote, "date", None),
                        status=status,
                        total=getattr(remote, "total", None) or 0,
                        currency=str(currency)[:3],
                        allocated_invoice_ids=_allocated_invoice_ids(remote),
                        raw_fields=_credit_note_raw_fields(remote),
                        xero_updated_at=getattr(remote, "updated_date_utc", None),
                    )
                    self.db.flush()
                    line_values = []
                    for index, remote_line in enumerate(getattr(remote, "line_items", None) or [], start=1):
                        remote_line_id = getattr(remote_line, "line_item_id", None)
                        key = str(remote_line_id) if remote_line_id else f"line-{index:04d}"
                        mapping = SalesTraceabilityService._find_mapping(
                            SimpleNamespace(
                                description=getattr(remote_line, "description", None),
                                item_code=getattr(remote_line, "item_code", None),
                            ),
                            mappings,
                            strict,
                        )
                        line_values.append(
                            {
                                "line_key": key,
                                "item_code": getattr(remote_line, "item_code", None),
                                "description": getattr(remote_line, "description", None),
                                "quantity": getattr(remote_line, "quantity", None),
                                "unit_amount": getattr(remote_line, "unit_amount", None),
                                "line_amount": getattr(remote_line, "line_amount", None),
                                "product_mapping_id": mapping.id if mapping else None,
                            }
                        )
                    self.credit_note_repo.upsert_lines(org_id, note.id, line_values)
                    self.db.flush()
                result.credit_notes_synced += 1
            except Exception as e:
                logger.warning("xero_credit_note_sync_record_failed", credit_note_id=xero_id, error=str(e))
                result.errors.append(f"credit note {xero_id}: {e}")

        if not incremental:
            deleted = self.credit_note_repo.mark_missing_as_deleted(org_id, tenant_id, seen_ids)
            if deleted:
                logger.info("xero_sync_credit_notes_marked_deleted", org_id=str(org_id), deleted_count=deleted)
        self.db.flush()
        return result

    # ------------------------------------------------------------------
    # Finalise job record
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Internal: purchases (live-cogs 8.1b)
    # ------------------------------------------------------------------

    PURCHASE_SCOPES = frozenset({"accounting.banktransactions.read", "accounting.settings.read"})

    def _run_purchases(
        self, api_client: XeroAPIClient, org_id: UUID, tenant_id: str, result: SyncResult, *, started_at
    ) -> None:
        """Spec 8.1b "Unit of work and failure". Never breaks sales: not entitled or not
        consented is a status, not an error; any other failure rolls back only this phase's
        savepoint (account cache included) and leaves its cursor where it was."""
        from app.core.security.entitlements import org_has_feature
        from app.features.costing import FEATURE_KEY
        from app.features.costing.models import CostingSettings
        from app.features.costing.purchase_sources import nz_today, sync_accounts, upsert_bank_transactions
        from app.features.crm.repositories.xero_token_repo import XeroTokenRepository
        from app.features.crm.services import xero_api_client as client_module

        if not org_has_feature(self.db, org_id, FEATURE_KEY):
            result.purchases_status = "not_enabled"
            return
        settings = self._costing_settings_for_update(org_id, CostingSettings)
        if settings.start_date is None:  # the activation anchor: persisted before anything can fail
            settings.start_date = nz_today()
        self.db.commit()

        token = XeroTokenRepository(self.db).get(org_id)
        granted = (token.scopes or "").split() if token is not None else []
        if granted and not self.PURCHASE_SCOPES <= set(granted):
            result.purchases_status = "needs_reconnect"
            return
        try:
            with start_span("xero.sync.purchases", attributes={"org_id": str(org_id)}):
                with self.db.begin_nested():
                    settings = self._costing_settings_for_update(org_id, CostingSettings)
                    bootstrap = settings.purchases_cursor is None or settings.purchases_tenant_id != tenant_id
                    base_currency = api_client.get_base_currency()
                    accounts = sync_accounts(self.db, org_id, api_client.get_accounts())
                    transactions = api_client.get_bank_transactions(
                        modified_after=None if bootstrap else settings.purchases_cursor,
                        from_date=settings.start_date if bootstrap else None,
                    )
                    stats = upsert_bank_transactions(
                        self.db,
                        org_id,
                        transactions,
                        accounts=accounts,
                        base_currency=base_currency,
                        start_date=settings.start_date,
                        xero_tenant_id=tenant_id,
                    )
                    settings.base_currency = base_currency
                    settings.purchases_tenant_id = tenant_id
                    settings.purchases_cursor = started_at - RESUME_OVERLAP
            result.purchases_synced = stats["documents"]
            result.purchases_status = "synced"
        except XeroTokenExpiredError:
            raise
        except Exception as e:
            # The savepoint has already undone only this phase; the sales work done earlier in
            # this sync is still pending and must not be rolled back with it.
            if client_module._is_insufficient_scope(e):
                result.purchases_status = "needs_reconnect"
                return
            logger.exception("xero_purchases_sync_failed", org_id=str(org_id))
            result.purchases_status = "failed"
            result.errors.append(f"Purchases sync error: {e}")

    def _costing_settings_for_update(self, org_id: UUID, model):
        from uuid import uuid4

        from sqlalchemy.dialects.postgresql import insert

        self.db.execute(
            insert(model.__table__)
            .values(id=uuid4(), org_id=org_id, use_last_known_price=True)
            .on_conflict_do_nothing(index_elements=["org_id"])
        )
        return self.db.query(model).filter(model.org_id == org_id).with_for_update().one()

    def _record_purchases(self, job_id: UUID, org_id: UUID, result: SyncResult) -> None:
        """Put the purchases fields on the job; ``_finalise_job`` commits them with the rest."""
        from app.features.crm.models.xero_sync_job import XeroSyncJob

        job = self.db.query(XeroSyncJob).filter(XeroSyncJob.org_id == org_id, XeroSyncJob.id == job_id).one_or_none()
        if job is not None:
            job.purchases_synced = result.purchases_synced
            job.purchases_status = result.purchases_status
            self.db.flush()

    def _finalise_job(self, job_id: UUID, org_id: UUID, result: SyncResult, *, started_at: datetime) -> None:
        status = "failed"
        if result.success:
            self.sync_job_repo.mark_completed(
                job_id,
                org_id,
                result.contacts_synced,
                result.invoices_synced,
                result.credit_notes_synced,
            )
            # Resume from before this sync fetched anything: a Xero edit made while it ran must be
            # in the next incremental sync, not skipped until somebody runs a full one.
            self.tenant_repo.update_last_sync(org_id, started_at - RESUME_OVERLAP)
            status = "completed"
        elif result.partial:
            self.sync_job_repo.mark_partial(
                job_id,
                org_id,
                result.contacts_synced,
                result.invoices_synced,
                error_message=f"{len(result.errors)} error(s) during sync",
                error_details={"errors": result.errors},
                credit_notes_synced=result.credit_notes_synced,
            )
            # The resume point stays put, so the records that failed are retried next time
            # instead of being skipped until somebody edits them in Xero again.
            status = "partial"
        else:
            self.sync_job_repo.mark_failed(
                job_id,
                org_id,
                error_message=result.errors[0] if result.errors else "Unknown error",
                error_details={"errors": result.errors},
            )
        self._emit_sync_event(job_id=job_id, org_id=org_id, status=status, result=result)
        self.db.commit()

    def _emit_sync_event(self, *, job_id: UUID, org_id: UUID, status: str, result: SyncResult) -> None:
        event_type = "crm_xero.sync_completed" if status == "completed" else "crm_xero.sync_failed"
        payload: dict[str, Any] = {
            "sync_job_id": str(job_id),
            "status": status,
            "contacts_synced": int(result.contacts_synced or 0),
            "invoices_synced": int(result.invoices_synced or 0),
            "credit_notes_synced": int(result.credit_notes_synced or 0),
            "sales_allocated": int(result.sales_allocated or 0),
            "sales_unmapped": int(result.sales_unmapped or 0),
            "sales_insufficient_stock": int(result.sales_insufficient_stock or 0),
            "errors_count": len(result.errors),
        }
        if result.errors:
            payload["errors"] = result.errors[:5]
        EventWriter(self.db, org_id).emit(
            event_type=event_type,
            entity_type="xero_sync_job",
            entity_id=job_id,
            payload=payload,
            correlation_id=job_id,
        )


def _serialise_xero_payment_terms(raw) -> dict | None:
    """Normalise Xero contact payment terms into JSON-serialisable dict."""
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


def _allocated_invoice_ids(credit_note) -> list[str]:
    ids = set()
    for allocation in getattr(credit_note, "allocations", None) or []:
        invoice = getattr(allocation, "invoice", None)
        invoice_id = getattr(invoice, "invoice_id", None) or getattr(allocation, "invoice_id", None)
        if invoice_id:
            ids.add(str(invoice_id))
    return sorted(ids)


def _credit_note_raw_fields(credit_note) -> dict:
    """Retain a small support snapshot, never the whole SDK object or contact payload."""
    type_value = getattr(credit_note, "type", None)
    status_value = getattr(credit_note, "status", None)
    updated = getattr(credit_note, "updated_date_utc", None)
    return {
        "type": str(getattr(type_value, "value", type_value)) if type_value is not None else None,
        "status": str(getattr(status_value, "value", status_value)) if status_value is not None else None,
        "sub_total": str(getattr(credit_note, "sub_total", "")) or None,
        "total_tax": str(getattr(credit_note, "total_tax", "")) or None,
        "updated_date_utc": updated.isoformat() if hasattr(updated, "isoformat") else None,
    }
