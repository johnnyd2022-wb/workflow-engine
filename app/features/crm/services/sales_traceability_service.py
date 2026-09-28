"""Apply mapped Xero sales to labelled final-product inventory using FIFO."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.db.models.inventory_item import InventoryItem
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
        confirmed = self._confirm_due_reviews(org_id)
        if confirmed:
            summary["auto_confirmed"] += confirmed
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

        # Plan 1.3: tracing starts at go-live. An earlier sale stays in sales reporting but
        # isn't matched to batches (the opening stocktake already reflects it); any match
        # made before the go-live date was set is undone.
        go_live = self._go_live_date(org_id)
        if go_live is not None and invoice.date is not None and invoice.date < go_live:
            restored = self._reverse_invoice_allocations(org_id, invoice.xero_invoice_id)
            summary = {"before_go_live": len(line_items)}
            if restored:
                summary["reversed"] = restored
            return summary

        config = self.config_repo.get_for_org(org_id)
        strategy = (config.matching_strategy if config is not None else "fifo") or "fifo"
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
            if strategy == "manual":
                # Plan 1.1: the owner picks the batch for each line (see assign_line).
                # A line already assigned keeps its batches unless its quantity changed.
                if existing:
                    self._reverse_allocations(existing)
                summary["awaiting_assignment"] += 1
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
            review = strategy == "hybrid" and (match.match_type or "exact") != "exact"
            created = [self._new_allocation(org_id, invoice, line_key, match, row) for row in consumed]
            presold = any(a.presold for a in created)
            for allocation in created:
                if strategy == "hybrid" and (review or presold):
                    allocation.status = "pending_review"
                    allocation.review_due_at = _now() + timedelta(days=self._review_days(config))
                self.db.add(allocation)
            self.db.flush()
            summary["allocated"] += 1
            if presold:
                summary["presold"] += 1
        return dict(summary)

    # --- plan 1.1: pre-sales, hybrid review, manual assignment ----------------------------

    def _new_allocation(self, org_id, invoice, line_key, match, row) -> SalesFifoAllocation:
        item_id = UUID(row["inventory_item_id"])
        return SalesFifoAllocation(
            org_id=org_id,
            xero_invoice_id=invoice.xero_invoice_id,
            xero_line_key=line_key,
            inventory_item_id=item_id,
            product_mapping_id=match.id,
            product_name=match.biz_e_product_name,
            quantity=Decimal(row["quantity_consumed"]),
            unit=row["unit"],
            presold=_is_presold(self.db, item_id, invoice.date),
        )

    @staticmethod
    def _review_days(config) -> int:
        try:
            return max(1, min(90, int(getattr(config, "manual_review_days", None) or 7)))
        except (TypeError, ValueError):
            return 7

    def _confirm_due_reviews(self, org_id: UUID) -> int:
        """Hybrid matches nobody changed within the review window confirm themselves."""
        due = (
            self.db.query(SalesFifoAllocation)
            .filter(
                SalesFifoAllocation.org_id == org_id,
                SalesFifoAllocation.status == "pending_review",
                SalesFifoAllocation.review_due_at <= _now(),
            )
            .all()
        )
        for allocation in due:
            allocation.status = "confirmed"
        if due:
            self.db.flush()
        return len({(a.xero_invoice_id, a.xero_line_key) for a in due})

    def _line_and_match(self, org_id: UUID, invoice_id: str, line_key: str):
        invoice = (
            self.db.query(XeroInvoice)
            .filter(XeroInvoice.org_id == org_id, XeroInvoice.xero_invoice_id == invoice_id)
            .one_or_none()
        )
        if invoice is None:
            raise ValueError("Invoice not found")
        lines = (
            self.db.query(XeroInvoiceLineItem)
            .filter(XeroInvoiceLineItem.org_id == org_id, XeroInvoiceLineItem.invoice_id == invoice.id)
            .order_by(XeroInvoiceLineItem.created_at.asc(), XeroInvoiceLineItem.id.asc())
            .all()
        )
        line = next(
            (ln for i, ln in enumerate(lines) if (ln.xero_line_item_id or f"position:{i + 1}").strip() == line_key),
            None,
        )
        if line is None:
            raise ValueError("Invoice line not found")
        config = self.config_repo.get_for_org(org_id)
        mappings = (
            self.db.query(ProductMapping)
            .filter(ProductMapping.org_id == org_id, ProductMapping.is_active.is_(True))
            .all()
        )
        match = self._find_mapping(line, mappings, True if config is None else bool(config.strict_mapping))
        if match is None:
            raise ValueError("This line isn't mapped to a product yet")
        quantity = _positive_quantity(line.quantity)
        if quantity is None:
            raise ValueError("This line has no quantity")
        return invoice, line, match, quantity * int(getattr(match, "units_per_line", None) or 1)

    def confirm_line(self, org_id: UUID, invoice_id: str, line_key: str) -> int:
        allocations = self._line_allocations(org_id, invoice_id, line_key)
        for allocation in allocations:
            allocation.status = "confirmed"
            allocation.review_due_at = None
        self.db.flush()
        return len(allocations)

    def assign_line(
        self, org_id: UUID, invoice_id: str, line_key: str, picks: list[dict], site_id: UUID | None = None
    ) -> list[SalesFifoAllocation]:
        """Put a sale line on the batches the owner chose (replacing any earlier match)."""
        invoice, _line, match, needed = self._line_and_match(org_id, invoice_id, line_key)
        parsed = []
        for pick in picks or []:
            try:
                item_id = UUID(str(pick.get("inventory_item_id")))
                qty = Decimal(str(pick.get("quantity")))
            except (InvalidOperation, ValueError, TypeError, AttributeError):
                raise ValueError("Each pick needs an inventory_item_id and a quantity") from None
            if qty > 0:
                parsed.append((item_id, qty))
        if not parsed:
            raise ValueError("Choose at least one batch")
        total = sum((q for _, q in parsed), Decimal("0"))
        if total != needed:
            raise ValueError(f"The batches must add up to {needed.normalize():f}; they add up to {total.normalize():f}")

        existing = self._line_allocations(org_id, invoice_id, line_key)
        if existing:
            self._reverse_allocations(existing)
        reference = _line_reference(invoice_id, line_key)
        created = []
        for item_id, qty in parsed:
            row = self.inventory.consume_final_product_lot(
                org_id, item_id, qty, reference=reference, commit=False, site_id=site_id
            )
            item = self.db.get(InventoryItem, item_id)
            if item is None or item.name != match.biz_e_product_name:
                raise ValueError(f"That batch isn't {match.biz_e_product_name}")
            allocation = self._new_allocation(org_id, invoice, line_key, match, row)
            self.db.add(allocation)
            created.append(allocation)
        self.db.flush()
        return created

    def lot_candidates(self, org_id: UUID, product_name: str, site_id: UUID | None = None) -> list[dict]:
        """Batches of ``product_name`` in stock, oldest first, for the owner to pick from."""
        from app.core.db.site_operations import resolve_site

        selected_site = resolve_site(self.db, org_id, site_id)
        items = self.db.query(InventoryItem).filter(
            InventoryItem.org_id == org_id,
            InventoryItem.name == product_name,
            InventoryItem.inventory_type == "final_product",
            InventoryItem.quantity > 0,
        )
        if selected_site is not None:
            items = items.filter(InventoryItem.site_id == selected_site)
        items = items.all()
        rows = []
        for i in items:
            made = _made_on(self.db, i)
            rows.append(
                {
                    "inventory_item_id": str(i.id),
                    "batch": i.supplier_batch_number or (i.extra_data or {}).get("batch_number"),
                    "available": f"{Decimal(str(i.quantity)).normalize():f}",
                    "unit": i.unit,
                    "made_on": made.isoformat() if made else None,
                }
            )
        return sorted(rows, key=lambda r: (r["made_on"] or "9999", r["batch"] or ""))

    def review_queue(self, org_id: UUID, limit: int = 200) -> dict:
        """Hybrid matches waiting for review, and (manual mode) lines waiting for a batch."""
        config = self.config_repo.get_for_org(org_id)
        strategy = (config.matching_strategy if config is not None else "fifo") or "fifo"
        pending = (
            self.db.query(SalesFifoAllocation)
            .filter(SalesFifoAllocation.org_id == org_id, SalesFifoAllocation.status == "pending_review")
            .order_by(SalesFifoAllocation.review_due_at.asc())
            .limit(limit)
            .all()
        )
        invoices = {
            inv.xero_invoice_id: inv
            for inv in self.db.query(XeroInvoice)
            .filter(
                XeroInvoice.org_id == org_id,
                XeroInvoice.xero_invoice_id.in_({a.xero_invoice_id for a in pending} or {""}),
            )
            .all()
        }
        grouped: dict = {}
        for a in pending:
            key = (a.xero_invoice_id, a.xero_line_key)
            inv = invoices.get(a.xero_invoice_id)
            entry = grouped.setdefault(
                key,
                {
                    "invoice_id": a.xero_invoice_id,
                    "line_key": a.xero_line_key,
                    "invoice_number": getattr(inv, "invoice_number", None),
                    "invoice_date": inv.date.isoformat() if inv is not None and inv.date else None,
                    "product_name": a.product_name,
                    "review_due_at": a.review_due_at.isoformat() if a.review_due_at else None,
                    "presold": False,
                    "batches": [],
                },
            )
            item = self.db.get(InventoryItem, a.inventory_item_id)
            entry["presold"] = entry["presold"] or bool(a.presold)
            entry["batches"].append(
                {
                    "inventory_item_id": str(a.inventory_item_id),
                    "batch": getattr(item, "supplier_batch_number", None),
                    "quantity": f"{Decimal(str(a.quantity)).normalize():f}",
                    "unit": a.unit,
                }
            )
        to_assign = self._lines_to_assign(org_id, limit) if strategy == "manual" else []
        return {"mode": strategy, "pending_review": list(grouped.values()), "to_assign": to_assign}

    def _lines_to_assign(self, org_id: UUID, limit: int) -> list[dict]:
        go_live = self._go_live_date(org_id)
        config = self.config_repo.get_for_org(org_id)
        strict = True if config is None else bool(config.strict_mapping)
        mappings = (
            self.db.query(ProductMapping)
            .filter(ProductMapping.org_id == org_id, ProductMapping.is_active.is_(True))
            .all()
        )
        allocated = {
            (a.xero_invoice_id, a.xero_line_key)
            for a in self.db.query(SalesFifoAllocation.xero_invoice_id, SalesFifoAllocation.xero_line_key)
            .filter(SalesFifoAllocation.org_id == org_id)
            .all()
        }
        out = []
        invoices = (
            self.db.query(XeroInvoice)
            .filter(XeroInvoice.org_id == org_id)
            .order_by(XeroInvoice.date.asc().nulls_last())
            .all()
        )
        # One query for every line, grouped by invoice (no per-invoice query in the loop).
        lines_by_invoice: dict = defaultdict(list)
        for line in (
            self.db.query(XeroInvoiceLineItem)
            .filter(XeroInvoiceLineItem.org_id == org_id)
            .order_by(XeroInvoiceLineItem.created_at.asc(), XeroInvoiceLineItem.id.asc())
            .all()
        ):
            lines_by_invoice[line.invoice_id].append(line)
        for inv in invoices:
            if (inv.invoice_type or "").upper() != _SALE_INVOICE_TYPE or (
                inv.status or ""
            ).upper() not in _SALE_STATUSES:
                continue
            if go_live is not None and inv.date is not None and inv.date < go_live:
                continue
            for index, line in enumerate(lines_by_invoice.get(inv.id, [])):
                key = (line.xero_line_item_id or f"position:{index + 1}").strip()
                if (inv.xero_invoice_id, key) in allocated:
                    continue
                match = self._find_mapping(line, mappings, strict)
                quantity = _positive_quantity(line.quantity)
                if match is None or quantity is None:
                    continue
                out.append(
                    {
                        "invoice_id": inv.xero_invoice_id,
                        "line_key": key,
                        "invoice_number": inv.invoice_number,
                        "invoice_date": inv.date.isoformat() if inv.date else None,
                        "description": line.description,
                        "product_name": match.biz_e_product_name,
                        "quantity": f"{(quantity * int(match.units_per_line or 1)).normalize():f}",
                    }
                )
                if len(out) >= limit:
                    return out
        return out
        return out

    def _go_live_date(self, org_id: UUID):
        cache = self.__dict__.setdefault("_go_live_cache", {})
        if org_id not in cache:
            from app.core.db.models.organisation import Organisation

            org = self.db.get(Organisation, org_id)
            cache[org_id] = getattr(org, "go_live_date", None)
        return cache[org_id]

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


def _now() -> datetime:
    return datetime.now(UTC)


def _made_on(db, item) -> date | None:
    """When a finished batch came into being: its producing step, else its bottling date."""
    step_id = getattr(item, "source_execution_step_id", None)
    if step_id is not None:
        from app.core.db.models.execution_step import ExecutionStep

        step = db.get(ExecutionStep, step_id)
        if step is not None and step.completed_at is not None:
            return step.completed_at.date()
    bottled = (getattr(item, "extra_data", None) or {}).get("bottled_on")
    if bottled:
        try:
            return date.fromisoformat(str(bottled))
        except ValueError:
            pass
    if getattr(item, "purchase_date", None):
        return item.purchase_date
    created = getattr(item, "created_at", None)
    return created.date() if created else None


def _is_presold(db, item_id: UUID, invoice_date: date | None) -> bool:
    """A sale filled from a batch made after the invoice date (plan 1.1)."""
    if invoice_date is None:
        return False
    item = db.get(InventoryItem, item_id)
    made = _made_on(db, item) if item is not None else None
    return made is not None and made > invoice_date


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
                # Plan 1.1: filled from a batch made after the invoice (a pre-sale), and
                # whether the owner still has to review the match (hybrid mode).
                "presold": any(bool(getattr(row, "presold", False)) for row in line_allocations),
                "match_status": (
                    "pending_review"
                    if any(getattr(row, "status", "confirmed") == "pending_review" for row in line_allocations)
                    else "confirmed"
                ),
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
