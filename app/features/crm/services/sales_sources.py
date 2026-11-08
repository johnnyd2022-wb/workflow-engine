"""Sales lines from accounting software, in one shape whatever the source.

Reports that need "what was sold" (Sales -> Excise) read ``sale_lines()`` and never touch
a provider's tables. Xero is the only source today. To add another (MYOB, Hnry, ...),
write a class with ``name``, ``connected()`` and ``lines()`` that returns ``SaleLine``s
already mapped to Biz-E products in stock units, then add it to ``SALES_SOURCES``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Protocol
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.db.models.inventory_item import InventoryItem


@dataclass
class SaleLine:
    source: str
    sold_on: date
    reference: str  # invoice number, for drill-down
    product_name: str  # the Biz-E final product
    units: Decimal  # in the product's stock units: a "Case of 6" line of 2 is 12
    # Batches this line was matched to, with the units each gave. Units not covered
    # (sale before go-live, not yet matched) are units - sum(batches).
    batches: list[tuple[InventoryItem, Decimal]] = field(default_factory=list)


@dataclass
class UnmappedLine:
    source: str
    sold_on: date
    reference: str
    description: str
    quantity: Decimal | None


class SalesSource(Protocol):
    name: str
    label: str

    def connected(self, session: Session, org_id: UUID) -> bool: ...

    def lines(
        self, session: Session, org_id: UUID, start: date, end: date
    ) -> tuple[list[SaleLine], list[UnmappedLine]]: ...

    def first_sale(self, session: Session, org_id: UUID) -> date | None: ...


def _decimal(value) -> Decimal | None:
    try:
        d = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return d if d.is_finite() else None


class XeroSalesSource:
    """Authorised and paid Xero sales invoices (ACCREC), mapped through Sales -> Batch matching."""

    name = "xero"
    label = "Xero"

    def connected(self, session: Session, org_id: UUID) -> bool:
        from app.features.crm.models.xero_invoice import XeroInvoice
        from app.features.crm.models.xero_tenant import XeroTenant

        return (
            session.query(XeroTenant.id).filter(XeroTenant.org_id == org_id).first() is not None
            or session.query(XeroInvoice.id).filter(XeroInvoice.org_id == org_id).first() is not None
        )

    def _sales(self, session: Session, org_id: UUID):
        from app.features.crm.models.xero_invoice import XeroInvoice
        from app.features.crm.services.sales_traceability_service import _SALE_INVOICE_TYPE, _SALE_STATUSES

        return session.query(XeroInvoice).filter(
            XeroInvoice.org_id == org_id,
            XeroInvoice.invoice_type == _SALE_INVOICE_TYPE,
            XeroInvoice.status.in_(sorted(_SALE_STATUSES)),
            XeroInvoice.date.isnot(None),
        )

    def first_sale(self, session: Session, org_id: UUID) -> date | None:
        from app.features.crm.models.xero_invoice import XeroInvoice

        first = self._sales(session, org_id).order_by(XeroInvoice.date.asc()).first()
        return first.date if first else None

    def lines(
        self, session: Session, org_id: UUID, start: date, end: date
    ) -> tuple[list[SaleLine], list[UnmappedLine]]:
        from app.features.crm.models.product_mapping import ProductMapping
        from app.features.crm.models.sales_fifo_allocation import SalesFifoAllocation
        from app.features.crm.models.xero_invoice import XeroInvoice
        from app.features.crm.models.xero_invoice_line_item import XeroInvoiceLineItem
        from app.features.crm.repositories.sales_traceability_repo import SalesTraceabilityConfigRepository
        from app.features.crm.services.sales_traceability_service import SalesTraceabilityService

        invoices = (
            self._sales(session, org_id)
            .filter(XeroInvoice.date >= start, XeroInvoice.date < end)
            .order_by(XeroInvoice.date.asc(), XeroInvoice.created_at.asc())
            .all()
        )
        if not invoices:
            return [], []
        config = SalesTraceabilityConfigRepository(session).get_for_org(org_id)
        strict = True if config is None else bool(config.strict_mapping)
        mappings = (
            session.query(ProductMapping)
            .filter(ProductMapping.org_id == org_id, ProductMapping.is_active.is_(True))
            .all()
        )
        by_invoice: dict[UUID, list] = {}
        for line in (
            session.query(XeroInvoiceLineItem)
            .filter(
                XeroInvoiceLineItem.org_id == org_id,
                XeroInvoiceLineItem.invoice_id.in_([i.id for i in invoices]),
            )
            .order_by(XeroInvoiceLineItem.created_at.asc(), XeroInvoiceLineItem.id.asc())
            .all()
        ):
            by_invoice.setdefault(line.invoice_id, []).append(line)

        allocations: dict[tuple[str, str], list[SalesFifoAllocation]] = {}
        for a in (
            session.query(SalesFifoAllocation)
            .filter(
                SalesFifoAllocation.org_id == org_id,
                SalesFifoAllocation.xero_invoice_id.in_([i.xero_invoice_id for i in invoices]),
            )
            .all()
        ):
            allocations.setdefault((a.xero_invoice_id, a.xero_line_key), []).append(a)
        item_ids = {a.inventory_item_id for rows in allocations.values() for a in rows}
        items = (
            {
                i.id: i
                for i in session.query(InventoryItem)
                .filter(InventoryItem.org_id == org_id, InventoryItem.id.in_(item_ids))
                .all()
            }
            if item_ids
            else {}
        )

        out: list[SaleLine] = []
        unmapped: list[UnmappedLine] = []
        for invoice in invoices:
            reference = invoice.invoice_number or invoice.xero_invoice_id
            for index, line in enumerate(by_invoice.get(invoice.id, [])):
                quantity = _decimal(line.quantity)
                if quantity is None or quantity <= 0:
                    continue
                match = SalesTraceabilityService._find_mapping(line, mappings, strict)
                if match is None:
                    unmapped.append(
                        UnmappedLine(
                            self.name,
                            invoice.date,
                            reference,
                            (line.description or line.item_code or "").strip()[:200],
                            quantity,
                        )
                    )
                    continue
                # Same key reconcile uses, so batches line up with the line they came from.
                line_key = (line.xero_line_item_id or f"position:{index + 1}").strip()
                batches = [
                    (items[a.inventory_item_id], Decimal(str(a.quantity)))
                    for a in allocations.get((invoice.xero_invoice_id, line_key), [])
                    if a.inventory_item_id in items
                ]
                out.append(
                    SaleLine(
                        source=self.name,
                        sold_on=invoice.date,
                        reference=reference,
                        product_name=match.biz_e_product_name,
                        units=quantity * int(match.units_per_line or 1),
                        batches=batches,
                    )
                )
        return out, unmapped


SALES_SOURCES: dict[str, SalesSource] = {"xero": XeroSalesSource()}


def connected_sources(session: Session, org_id: UUID) -> list[SalesSource]:
    return [s for s in SALES_SOURCES.values() if s.connected(session, org_id)]


def sale_lines(session: Session, org_id: UUID, start: date, end: date) -> tuple[list[SaleLine], list[UnmappedLine]]:
    """Every connected source's sales dated in [start, end)."""
    lines: list[SaleLine] = []
    unmapped: list[UnmappedLine] = []
    for source in connected_sources(session, org_id):
        got, missing = source.lines(session, org_id, start, end)
        lines.extend(got)
        unmapped.extend(missing)
    return lines, unmapped


def first_sale(session: Session, org_id: UUID) -> date | None:
    dates = [d for s in connected_sources(session, org_id) if (d := s.first_sale(session, org_id))]
    return min(dates) if dates else None
