"""XeroSyncService — orchestrates contact and invoice sync from Xero."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from app.features.crm.repositories.xero_contact_repo import XeroContactRepository
from app.features.crm.repositories.xero_invoice_repo import XeroInvoiceRepository
from app.features.crm.repositories.xero_sync_job_repo import XeroSyncJobRepository
from app.features.crm.repositories.xero_tenant_repo import XeroTenantRepository
from app.features.crm.services.xero_api_client import XeroAPIClient
from app.features.crm.services.xero_oauth_service import XeroTokenExpiredError

logger = logging.getLogger(__name__)


@dataclass
class SyncResult:
    contacts_synced: int = 0
    invoices_synced: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return not self.errors

    @property
    def partial(self) -> bool:
        return bool(self.errors) and (self.contacts_synced > 0 or self.invoices_synced > 0)


class XeroSyncService:
    """Syncs Xero contacts and invoices into local CRM tables.

    Designed to be called synchronously in Phase 1. Celery-ready: no Flask
    context dependencies — only db, org_id, tenant_id.
    """

    def __init__(self, db: Session):
        self.db = db
        self.contact_repo = XeroContactRepository(db)
        self.invoice_repo = XeroInvoiceRepository(db)
        self.tenant_repo = XeroTenantRepository(db)
        self.sync_job_repo = XeroSyncJobRepository(db)

    def full_sync(self, org_id: UUID, triggered_by: str = "manual") -> SyncResult:
        """Run a full contacts + invoices sync."""
        tenant = self.tenant_repo.get_connected(org_id)
        if not tenant:
            raise ValueError("No connected Xero tenant for this org.")

        job = self.sync_job_repo.create(org_id, tenant.xero_tenant_id, "full", triggered_by)
        self.db.commit()

        result = SyncResult()
        api_client = XeroAPIClient(self.db, org_id)

        try:
            contacts_result = self._sync_contacts(api_client, org_id, tenant.xero_tenant_id, incremental=False)
            result.contacts_synced = contacts_result.contacts_synced
            result.errors.extend(contacts_result.errors)
        except XeroTokenExpiredError:
            raise
        except Exception as e:
            logger.exception("Contact sync failed for org %s", org_id)
            result.errors.append(f"Contact sync error: {e}")

        try:
            invoices_result = self._sync_invoices(api_client, org_id, tenant.xero_tenant_id, incremental=False)
            result.invoices_synced = invoices_result.invoices_synced
            result.errors.extend(invoices_result.errors)
        except XeroTokenExpiredError:
            raise
        except Exception as e:
            logger.exception("Invoice sync failed for org %s", org_id)
            result.errors.append(f"Invoice sync error: {e}")

        self._finalise_job(job.id, org_id, result)
        return result

    def incremental_sync(self, org_id: UUID, triggered_by: str = "manual") -> SyncResult:
        """Sync only records modified since last successful sync."""
        tenant = self.tenant_repo.get_connected(org_id)
        if not tenant:
            raise ValueError("No connected Xero tenant for this org.")

        modified_after = tenant.last_successful_sync_at
        job = self.sync_job_repo.create(org_id, tenant.xero_tenant_id, "full", triggered_by)
        self.db.commit()

        result = SyncResult()
        api_client = XeroAPIClient(self.db, org_id)

        try:
            r = self._sync_contacts(
                api_client, org_id, tenant.xero_tenant_id, incremental=True, modified_after=modified_after
            )
            result.contacts_synced = r.contacts_synced
            result.errors.extend(r.errors)
        except Exception as e:
            logger.exception("Incremental contact sync failed for org %s", org_id)
            result.errors.append(str(e))

        try:
            r = self._sync_invoices(
                api_client, org_id, tenant.xero_tenant_id, incremental=True, modified_after=modified_after
            )
            result.invoices_synced = r.invoices_synced
            result.errors.extend(r.errors)
        except Exception as e:
            logger.exception("Incremental invoice sync failed for org %s", org_id)
            result.errors.append(str(e))

        self._finalise_job(job.id, org_id, result)
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
        logger.info("Syncing %d contacts for org %s", len(contacts), org_id)

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
                            "city": getattr(a, "city", None),
                            "region": getattr(a, "region", None),
                            "postal_code": getattr(a, "postal_code", None),
                            "country": getattr(a, "country", None),
                        }
                    )

                xero_updated_at = None
                if xc.updated_date_utc:
                    xero_updated_at = xc.updated_date_utc

                self.contact_repo.upsert(
                    org_id=org_id,
                    xero_contact_id=str(xc.contact_id),
                    xero_tenant_id=tenant_id,
                    name=xc.name or "(No name)",
                    first_name=xc.first_name,
                    last_name=xc.last_name,
                    email_address=xc.email_address,
                    phone_number=phone_number,
                    addresses=addresses or None,
                    tax_number=getattr(xc, "tax_number", None),
                    account_number=xc.account_number,
                    contact_status=str(xc.contact_status) if xc.contact_status else None,
                    is_customer=bool(xc.is_customer),
                    is_supplier=bool(xc.is_supplier),
                    xero_updated_at=xero_updated_at,
                )
                result.contacts_synced += 1
            except Exception as e:
                logger.warning("Failed to sync contact %s: %s", getattr(xc, "contact_id", "?"), e)
                result.errors.append(f"contact {getattr(xc, 'contact_id', '?')}: {e}")

        # Flush after all contacts so FK lookups work for invoices
        self.db.flush()
        return result

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
    ) -> SyncResult:
        result = SyncResult()
        invoices = api_client.get_all_invoices(modified_after=modified_after if incremental else None)
        logger.info("Syncing %d invoices for org %s", len(invoices), org_id)

        for xi in invoices:
            try:
                xero_contact_id = str(xi.contact.contact_id) if xi.contact and xi.contact.contact_id else None
                contact = self.contact_repo.get_by_xero_id(xero_contact_id, org_id) if xero_contact_id else None

                inv = self.invoice_repo.upsert_invoice(
                    org_id=org_id,
                    xero_invoice_id=str(xi.invoice_id),
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
                    currency_code=str(xi.currency_code) if xi.currency_code else "NZD",
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
                result.invoices_synced += 1

            except Exception as e:
                logger.warning("Failed to sync invoice %s: %s", getattr(xi, "invoice_id", "?"), e)
                result.errors.append(f"invoice {getattr(xi, 'invoice_id', '?')}: {e}")

        self.db.flush()
        return result

    # ------------------------------------------------------------------
    # Finalise job record
    # ------------------------------------------------------------------

    def _finalise_job(self, job_id: UUID, org_id: UUID, result: SyncResult) -> None:
        if result.success:
            self.sync_job_repo.mark_completed(job_id, result.contacts_synced, result.invoices_synced)
            self.tenant_repo.update_last_sync(org_id, datetime.now(timezone.utc))
        elif result.partial:
            self.sync_job_repo.mark_partial(
                job_id,
                result.contacts_synced,
                result.invoices_synced,
                error_message=f"{len(result.errors)} error(s) during sync",
                error_details={"errors": result.errors},
            )
            self.tenant_repo.update_last_sync(org_id, datetime.now(timezone.utc))
        else:
            self.sync_job_repo.mark_failed(
                job_id,
                error_message=result.errors[0] if result.errors else "Unknown error",
                error_details={"errors": result.errors},
            )
        self.db.commit()
