"""Apply mapped Xero sales to labelled final-product inventory using FIFO."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.db.repositories.inventory_repo import InventoryRepository
from app.core.utils.inventory_quantity import parse_stored_quantity_to_decimal
from app.features.crm.models.product_mapping import ProductMapping
from app.features.crm.models.sales_fifo_allocation import SalesFifoAllocation
from app.features.crm.models.xero_invoice import XeroInvoice
from app.features.crm.models.xero_invoice_line_item import XeroInvoiceLineItem
from app.features.crm.repositories.sales_traceability_repo import SalesTraceabilityConfigRepository

_SALE_INVOICE_TYPE = "ACCREC"
_SALE_STATUSES = {"AUTHORISED", "PAID"}


class SalesTraceabilityService:
    """Keep local Xero sales and labelled inventory in a durable, reversible agreement."""

    def __init__(self, db: Session):
        self.db = db
        self.inventory = InventoryRepository(db)
        self.config_repo = SalesTraceabilityConfigRepository(db)

    def reconcile_org(self, org_id: UUID) -> dict[str, int]:
        """Backfill and incrementally maintain FIFO allocations for all synced sales.

        Reconciliation intentionally examines the local invoice snapshot, rather than
        only records returned by this Xero request. Adding a product mapping after an
        initial sync therefore becomes effective on the next ordinary sync, without a
        special historical-import path.
        """
        invoices = (
            self.db.query(XeroInvoice)
            .filter(XeroInvoice.org_id == org_id)
            .order_by(XeroInvoice.date.asc().nulls_last(), XeroInvoice.created_at.asc())
            .all()
        )
        summary = defaultdict(int)
        for invoice in invoices:
            for key, value in self._reconcile_invoice(org_id, invoice).items():
                summary[key] += value
        return dict(summary)

    def _reconcile_invoice(self, org_id: UUID, invoice: XeroInvoice) -> dict[str, int]:
        line_items = (
            self.db.query(XeroInvoiceLineItem)
            .filter(XeroInvoiceLineItem.org_id == org_id, XeroInvoiceLineItem.invoice_id == invoice.id)
            .order_by(XeroInvoiceLineItem.created_at.asc(), XeroInvoiceLineItem.id.asc())
            .all()
        )
        active_sale = (invoice.invoice_type or "").upper() == _SALE_INVOICE_TYPE and (
            invoice.status or ""
        ).upper() in _SALE_STATUSES
        if not active_sale:
            restored = self._reverse_invoice_allocations(org_id, invoice.xero_invoice_id)
            return {"reversed": restored} if restored else {}

        config = self.config_repo.get_for_org(org_id)
        if config is not None and config.matching_strategy != "fifo":
            return {"deferred": len(line_items)} if line_items else {}
        strict = True if config is None else bool(config.strict_mapping)
        mappings = (
            self.db.query(ProductMapping)
            .filter(ProductMapping.org_id == org_id, ProductMapping.is_active.is_(True))
            .all()
        )
        summary = defaultdict(int)
        for index, line in enumerate(line_items):
            line_key = (line.xero_line_item_id or f"position:{index + 1}").strip()
            match = self._find_mapping(line, mappings, strict)
            existing = self._line_allocations(org_id, invoice.xero_invoice_id, line_key)
            if match is None:
                # An existing allocation remains a historical fact even if somebody
                # later removes/edits its mapping. Do not silently put stock back.
                if not existing:
                    summary["unmapped"] += 1
                continue
            quantity = _positive_quantity(line.quantity)
            if quantity is None:
                if not existing:
                    summary["invalid_quantity"] += 1
                continue
            if self._matches_existing(existing, match, quantity):
                summary["already_allocated"] += 1
                continue
            if existing:
                self._reverse_allocations(existing)
            reference = _line_reference(invoice.xero_invoice_id, line_key)
            try:
                consumed = self.inventory.consume_final_product_fifo(
                    org_id,
                    match.biz_e_product_name,
                    quantity,
                    reference=reference,
                    source_output_id=match.biz_e_source_output_id,
                    commit=False,
                )
            except ValueError:
                # FIFO refuses partial consumption. Leave this line unallocated so a
                # later stock correction/replay can safely retry it in date order.
                summary["insufficient_stock"] += 1
                continue
            for row in consumed:
                self.db.add(
                    SalesFifoAllocation(
                        org_id=org_id,
                        xero_invoice_id=invoice.xero_invoice_id,
                        xero_line_key=line_key,
                        inventory_item_id=UUID(row["inventory_item_id"]),
                        product_mapping_id=match.id,
                        product_name=match.biz_e_product_name,
                        quantity=Decimal(row["quantity_consumed"]),
                        unit=row["unit"],
                    )
                )
            self.db.flush()
            summary["allocated"] += 1
        return dict(summary)

    def _line_allocations(self, org_id: UUID, invoice_id: str, line_key: str) -> list[SalesFifoAllocation]:
        return (
            self.db.query(SalesFifoAllocation)
            .filter(
                SalesFifoAllocation.org_id == org_id,
                SalesFifoAllocation.xero_invoice_id == invoice_id,
                SalesFifoAllocation.xero_line_key == line_key,
            )
            .order_by(SalesFifoAllocation.created_at.asc(), SalesFifoAllocation.id.asc())
            .all()
        )

    @staticmethod
    def _matches_existing(existing: list[SalesFifoAllocation], mapping: ProductMapping, quantity: Decimal) -> bool:
        return (
            bool(existing)
            and all(
                allocation.product_name == mapping.biz_e_product_name and allocation.product_mapping_id == mapping.id
                for allocation in existing
            )
            and sum((parse_stored_quantity_to_decimal(row.quantity) for row in existing), Decimal("0")) == quantity
        )

    def _reverse_invoice_allocations(self, org_id: UUID, invoice_id: str) -> int:
        allocations = (
            self.db.query(SalesFifoAllocation)
            .filter(SalesFifoAllocation.org_id == org_id, SalesFifoAllocation.xero_invoice_id == invoice_id)
            .order_by(SalesFifoAllocation.created_at.desc(), SalesFifoAllocation.id.desc())
            .all()
        )
        return self._reverse_allocations(allocations)

    def _reverse_allocations(self, allocations: list[SalesFifoAllocation]) -> int:
        for allocation in allocations:
            self.inventory.reverse_final_product_fifo_consumption(
                allocation.org_id,
                allocation.inventory_item_id,
                allocation.quantity,
                reference=_line_reference(allocation.xero_invoice_id, allocation.xero_line_key),
                commit=False,
            )
            self.db.delete(allocation)
        self.db.flush()
        return len(allocations)

    @staticmethod
    def _find_mapping(
        line: XeroInvoiceLineItem,
        mappings: list[ProductMapping],
        strict: bool,
    ) -> ProductMapping | None:
        values = [str(value).strip() for value in (line.description, line.item_code) if str(value or "").strip()]
        matches = []
        for mapping in mappings:
            pattern = mapping.xero_description_pattern.strip()
            if not pattern:
                continue
            exact = any(value.casefold() == pattern.casefold() for value in values)
            contains = any(pattern.casefold() in value.casefold() for value in values)
            if exact or (not strict and mapping.match_type in {"contains", "alias"} and contains):
                matches.append(mapping)
        return matches[0] if len(matches) == 1 else None


def _positive_quantity(raw: Any) -> Decimal | None:
    try:
        quantity = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return quantity if quantity.is_finite() and quantity > 0 else None


def _line_reference(invoice_id: str, line_key: str) -> str:
    return f"xero:{invoice_id}:{line_key}"
