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
from app.features.crm.models.xero_contact import XeroContact
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
            # Plan 1.2: a "Case of 6" line takes 6 stock units per quantity.
            quantity = quantity * int(getattr(match, "units_per_line", None) or 1)
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
            except ValueError as exc:
                # FIFO refuses partial consumption, and counted stock moves in whole units.
                # Leave this line unallocated so a later stock correction/replay can safely
                # retry it in date order.
                summary["fractional_quantity" if "whole numbers" in str(exc) else "insufficient_stock"] += 1
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
        exact_matches = []
        contains_matches = []
        for mapping in mappings:
            pattern = mapping.xero_description_pattern.strip()
            if not pattern:
                continue
            exact = any(value.casefold() == pattern.casefold() for value in values)
            if exact and mapping.match_type in {"exact", "alias"}:
                exact_matches.append(mapping)
                continue
            if (
                not strict
                and mapping.match_type in {"contains", "alias"}
                and any(pattern.casefold() in value.casefold() for value in values)
            ):
                contains_matches.append(mapping)

        # A precise product rule must take precedence over a broad phrase such as
        # "Wildflower". Otherwise adding a partial rule would make existing exact
        # mappings ambiguous instead of extending coverage to price variants.
        if exact_matches:
            return exact_matches[0] if len(exact_matches) == 1 else None
        return contains_matches[0] if len(contains_matches) == 1 else None


def _positive_quantity(raw: Any) -> Decimal | None:
    try:
        quantity = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return quantity if quantity.is_finite() and quantity > 0 else None


def _line_reference(invoice_id: str, line_key: str) -> str:
    return f"xero:{invoice_id}:{line_key}"


def _contact_address(contact: XeroContact | None) -> str | None:
    """One line from the contact's recorded addresses, preferring the street address."""
    addresses = [a for a in (contact.addresses if contact else None) or [] if isinstance(a, dict)]
    addresses.sort(key=lambda a: {"STREET": 0, "POBOX": 1}.get(str(a.get("type") or "").upper(), 2))
    for address in addresses:
        parts = [
            str(address.get(key)).strip()
            for key in ("line1", "line2", "city", "region", "postal_code", "country")
            if address.get(key) and str(address.get(key)).strip()
        ]
        if parts:
            return ", ".join(parts)
    return None


def append_sales_to_dag(
    db: Session,
    org_id: UUID,
    inventory_item_ids: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return terminal sale nodes and exact inventory-batch allocation edges.

    Sales are deliberately virtual DAG nodes: the persisted fact remains the durable
    ``SalesFifoAllocation`` row, while a grouped node represents the customer-facing
    Xero invoice line. This keeps one sale visible even when FIFO fulfilled it from
    several labelled batches.
    """
    item_ids = []
    for item_id in inventory_item_ids:
        try:
            item_ids.append(UUID(str(item_id)))
        except (TypeError, ValueError):
            continue
    if not item_ids:
        return [], []

    allocations = (
        db.query(SalesFifoAllocation)
        .filter(
            SalesFifoAllocation.org_id == org_id,
            SalesFifoAllocation.inventory_item_id.in_(item_ids),
        )
        .all()
    )
    if not allocations:
        return [], []

    invoice_ids = {allocation.xero_invoice_id for allocation in allocations}
    invoices = (
        db.query(XeroInvoice).filter(XeroInvoice.org_id == org_id, XeroInvoice.xero_invoice_id.in_(invoice_ids)).all()
    )
    invoices_by_external_id = {invoice.xero_invoice_id: invoice for invoice in invoices}
    invoice_row_ids = [invoice.id for invoice in invoices]
    line_items = (
        db.query(XeroInvoiceLineItem)
        .filter(XeroInvoiceLineItem.org_id == org_id, XeroInvoiceLineItem.invoice_id.in_(invoice_row_ids))
        .order_by(XeroInvoiceLineItem.created_at.asc(), XeroInvoiceLineItem.id.asc())
        .all()
        if invoice_row_ids
        else []
    )
    lines_by_invoice_and_key: dict[tuple[str, str], XeroInvoiceLineItem] = {}
    lines_by_invoice: dict[UUID, list[XeroInvoiceLineItem]] = defaultdict(list)
    for line in line_items:
        lines_by_invoice[line.invoice_id].append(line)
    for invoice in invoices:
        for position, line in enumerate(lines_by_invoice.get(invoice.id, []), start=1):
            line_key = (line.xero_line_item_id or f"position:{position}").strip()
            lines_by_invoice_and_key[(invoice.xero_invoice_id, line_key)] = line

    contact_ids = {invoice.contact_id for invoice in invoices if invoice.contact_id}
    contacts_by_id = {
        contact.id: contact
        for contact in (
            db.query(XeroContact).filter(XeroContact.org_id == org_id, XeroContact.id.in_(contact_ids)).all()
            if contact_ids
            else []
        )
    }

    grouped: dict[tuple[str, str], list[SalesFifoAllocation]] = defaultdict(list)
    for allocation in allocations:
        grouped[(allocation.xero_invoice_id, allocation.xero_line_key)].append(allocation)

    sale_nodes: list[dict[str, Any]] = []
    sale_edges: list[dict[str, Any]] = []
    for (invoice_external_id, line_key), line_allocations in grouped.items():
        invoice = invoices_by_external_id.get(invoice_external_id)
        line = lines_by_invoice_and_key.get((invoice_external_id, line_key))
        contact = contacts_by_id.get(invoice.contact_id) if invoice and invoice.contact_id else None
        sale_id = f"sale:{invoice_external_id}:{line_key}"
        allocated_quantity = sum((Decimal(str(row.quantity)) for row in line_allocations), Decimal("0"))
        sale_nodes.append(
            {
                "id": sale_id,
                "node_type": "sale",
                "inventory_type": "sale",
                "name": (line.description if line and line.description else line_allocations[0].product_name),
                "quantity": str(line.quantity if line and line.quantity is not None else allocated_quantity),
                "unit": line_allocations[0].unit,
                "sale_date": invoice.date.isoformat() if invoice and invoice.date else None,
                "invoice_number": invoice.invoice_number if invoice else None,
                "invoice_status": invoice.status if invoice else None,
                "customer_name": contact.name if contact else None,
                # Profile details for recall mode, which contacts each unique customer once.
                "customer_id": str(contact.id) if contact else None,
                "customer_primary_contact": (
                    " ".join(part for part in (contact.first_name, contact.last_name) if part) or None
                    if contact
                    else None
                ),
                "customer_email": contact.email_address if contact else None,
                "customer_phone": contact.phone_number if contact else None,
                "customer_address": _contact_address(contact),
                "item_code": line.item_code if line else None,
                "xero_invoice_id": invoice_external_id,
                "xero_line_key": line_key,
            }
        )
        for allocation in line_allocations:
            sale_edges.append(
                {
                    "from_id": str(allocation.inventory_item_id),
                    "to_id": sale_id,
                    "execution_id": None,
                    "edge_type": "sale",
                    "quantity": str(allocation.quantity),
                }
            )
    return sale_nodes, sale_edges
