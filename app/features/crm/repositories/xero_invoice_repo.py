"""Repository for XeroInvoice and XeroInvoiceLineItem records."""

import uuid
from datetime import date
from uuid import UUID

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.utils.time import utc_now
from app.features.crm.models.xero_invoice import XeroInvoice
from app.features.crm.models.xero_invoice_line_item import XeroInvoiceLineItem


class XeroInvoiceRepository:
    def __init__(self, db: Session):
        self.db = db

    def upsert_invoice(
        self,
        org_id: UUID,
        xero_invoice_id: str,
        xero_tenant_id: str,
        contact_id: UUID | None,
        **fields,
    ) -> XeroInvoice:
        inv = (
            self.db.query(XeroInvoice)
            .filter(
                XeroInvoice.org_id == org_id,
                XeroInvoice.xero_invoice_id == xero_invoice_id,
            )
            .first()
        )

        if inv:
            inv.xero_tenant_id = xero_tenant_id
            inv.contact_id = contact_id
            for k, v in fields.items():
                setattr(inv, k, v)
            inv.last_synced_at = utc_now()
            inv.updated_at = utc_now()
        else:
            inv = XeroInvoice(
                id=uuid.uuid4(),  # generate now so inv.id is available before flush
                org_id=org_id,
                xero_invoice_id=xero_invoice_id,
                xero_tenant_id=xero_tenant_id,
                contact_id=contact_id,
                last_synced_at=utc_now(),
                **fields,
            )
            self.db.add(inv)

        return inv

    def replace_line_items(self, invoice_id: UUID, org_id: UUID, line_items: list[dict]) -> None:
        self.db.query(XeroInvoiceLineItem).filter(XeroInvoiceLineItem.invoice_id == invoice_id).delete(
            synchronize_session=False
        )

        for item in line_items:
            li = XeroInvoiceLineItem(
                org_id=org_id,
                invoice_id=invoice_id,
                **item,
            )
            self.db.add(li)

    def mark_missing_as_deleted(self, org_id: UUID, xero_tenant_id: str, seen_xero_invoice_ids: set[str]) -> int:
        """During a full sync, mark local ACCREC invoices as DELETED if they are absent from Xero snapshot."""
        q = self.db.query(XeroInvoice).filter(
            XeroInvoice.org_id == org_id,
            XeroInvoice.xero_tenant_id == xero_tenant_id,
            XeroInvoice.invoice_type == "ACCREC",
            XeroInvoice.status.in_(["DRAFT", "SUBMITTED", "AUTHORISED", "PAID", "VOIDED"]),
        )
        if seen_xero_invoice_ids:
            q = q.filter(~XeroInvoice.xero_invoice_id.in_(list(seen_xero_invoice_ids)))

        now = utc_now()
        updated = q.update(
            {
                XeroInvoice.status: "DELETED",
                XeroInvoice.amount_due: 0,
                XeroInvoice.updated_at: now,
                XeroInvoice.last_synced_at: now,
            },
            synchronize_session=False,
        )
        return int(updated or 0)

    def get_by_id(self, invoice_id: UUID, org_id: UUID) -> XeroInvoice | None:
        return (
            self.db.query(XeroInvoice)
            .filter(
                XeroInvoice.id == invoice_id,
                XeroInvoice.org_id == org_id,
            )
            .first()
        )

    def list_for_contact(
        self,
        contact_id: UUID,
        org_id: UUID,
        page: int = 1,
        page_size: int = 25,
    ) -> tuple[list[XeroInvoice], int]:
        q = (
            self.db.query(XeroInvoice)
            .filter(XeroInvoice.contact_id == contact_id, XeroInvoice.org_id == org_id)
            .order_by(XeroInvoice.date.desc())
        )
        total = q.count()
        return q.offset((page - 1) * page_size).limit(page_size).all(), total

    def list_for_org(
        self,
        org_id: UUID,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        outstanding_only: bool = False,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[XeroInvoice], int]:
        q = self.db.query(XeroInvoice).filter(
            XeroInvoice.org_id == org_id,
            XeroInvoice.invoice_type == "ACCREC",
        )
        if start_date:
            q = q.filter(XeroInvoice.date >= start_date)
        if end_date:
            q = q.filter(XeroInvoice.date < end_date)
        if outstanding_only:
            q = q.filter(
                XeroInvoice.status == "AUTHORISED",
                XeroInvoice.amount_due > 0,
            )
        total = q.count()
        rows = (
            q.order_by(XeroInvoice.date.desc().nulls_last(), XeroInvoice.updated_at.desc().nulls_last())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return rows, total

    def get_line_items(self, invoice_id: UUID) -> list[XeroInvoiceLineItem]:
        return self.db.query(XeroInvoiceLineItem).filter(XeroInvoiceLineItem.invoice_id == invoice_id).all()

    def line_item_options_for_contact(self, contact_id: UUID, org_id: UUID) -> list[dict]:
        """Return distinct line item description/code combinations for a contact."""
        rows = (
            self.db.query(
                XeroInvoiceLineItem.description,
                XeroInvoiceLineItem.item_code,
            )
            .join(XeroInvoice, XeroInvoiceLineItem.invoice_id == XeroInvoice.id)
            .filter(
                XeroInvoice.org_id == org_id,
                XeroInvoice.contact_id == contact_id,
                XeroInvoiceLineItem.org_id == org_id,
                or_(
                    XeroInvoiceLineItem.description.isnot(None),
                    XeroInvoiceLineItem.item_code.isnot(None),
                ),
            )
            .group_by(XeroInvoiceLineItem.description, XeroInvoiceLineItem.item_code)
            .order_by(
                XeroInvoiceLineItem.description.asc().nulls_last(), XeroInvoiceLineItem.item_code.asc().nulls_last()
            )
            .all()
        )
        return [
            {
                "description": row.description,
                "item_code": row.item_code,
                "display_label": f"{row.description or 'No description'}{f' ({row.item_code})' if row.item_code else ''}",
            }
            for row in rows
            if row.description or row.item_code
        ]

    def line_item_options_for_org(self, org_id: UUID) -> list[dict]:
        rows = (
            self.db.query(
                XeroInvoiceLineItem.description,
                XeroInvoiceLineItem.item_code,
            )
            .join(XeroInvoice, XeroInvoiceLineItem.invoice_id == XeroInvoice.id)
            .filter(
                XeroInvoice.org_id == org_id,
                XeroInvoiceLineItem.org_id == org_id,
                or_(
                    XeroInvoiceLineItem.description.isnot(None),
                    XeroInvoiceLineItem.item_code.isnot(None),
                ),
            )
            .group_by(XeroInvoiceLineItem.description, XeroInvoiceLineItem.item_code)
            .order_by(
                XeroInvoiceLineItem.description.asc().nulls_last(), XeroInvoiceLineItem.item_code.asc().nulls_last()
            )
            .all()
        )
        return [
            {
                "description": row.description,
                "item_code": row.item_code,
                "display_label": f"{row.description or 'No description'}{f' ({row.item_code})' if row.item_code else ''}",
            }
            for row in rows
            if row.description or row.item_code
        ]

    def line_item_pricing_for_contact(
        self,
        contact_id: UUID,
        org_id: UUID,
        *,
        description: str | None = None,
        item_code: str | None = None,
    ) -> dict | None:
        q = (
            self.db.query(
                XeroInvoiceLineItem.description,
                XeroInvoiceLineItem.item_code,
                XeroInvoiceLineItem.unit_amount,
                XeroInvoiceLineItem.tax_type,
                XeroInvoiceLineItem.account_code,
                XeroInvoice.date,
            )
            .join(XeroInvoice, XeroInvoiceLineItem.invoice_id == XeroInvoice.id)
            .filter(
                XeroInvoice.org_id == org_id,
                XeroInvoice.contact_id == contact_id,
                XeroInvoiceLineItem.org_id == org_id,
            )
        )
        if description:
            q = q.filter(XeroInvoiceLineItem.description == description)
        if item_code:
            q = q.filter(XeroInvoiceLineItem.item_code == item_code)
        row = q.order_by(XeroInvoice.date.desc().nulls_last(), XeroInvoice.updated_at.desc().nulls_last()).first()
        if not row:
            return None
        return {
            "description": row.description,
            "item_code": row.item_code,
            "unit_amount": float(row.unit_amount) if row.unit_amount is not None else None,
            "tax_type": row.tax_type,
            "account_code": row.account_code,
            "source_invoice_date": row.date.isoformat() if row.date else None,
        }

    def inferred_due_day_for_contact(self, contact_id: UUID, org_id: UUID, sample_size: int = 50) -> int | None:
        rows = (
            self.db.query(XeroInvoice.due_date)
            .filter(
                XeroInvoice.org_id == org_id,
                XeroInvoice.contact_id == contact_id,
                XeroInvoice.invoice_type == "ACCREC",
                XeroInvoice.due_date.isnot(None),
            )
            .order_by(XeroInvoice.date.desc().nulls_last(), XeroInvoice.updated_at.desc().nulls_last())
            .limit(sample_size)
            .all()
        )
        days = [int(r.due_date.day) for r in rows if getattr(r, "due_date", None) is not None]
        if not days:
            return None
        from collections import Counter

        counter = Counter(days)
        return counter.most_common(1)[0][0]

    def sales_totals_for_period(self, org_id: UUID, start_date: date, end_date: date) -> dict:
        row = (
            self.db.query(
                func.sum(XeroInvoice.total).label("total"),
                func.count(XeroInvoice.id).label("invoice_count"),
            )
            .filter(
                XeroInvoice.org_id == org_id,
                XeroInvoice.invoice_type == "ACCREC",
                XeroInvoice.status.in_(["AUTHORISED", "PAID"]),
                XeroInvoice.date >= start_date,
                XeroInvoice.date < end_date,
            )
            .one()
        )
        return {"total": float(row.total or 0), "invoice_count": row.invoice_count or 0}

    def outstanding_receivables(self, org_id: UUID) -> dict:
        row = (
            self.db.query(
                func.sum(XeroInvoice.amount_due).label("total"),
                func.count(XeroInvoice.id).label("invoice_count"),
            )
            .filter(
                XeroInvoice.org_id == org_id,
                XeroInvoice.invoice_type == "ACCREC",
                XeroInvoice.status == "AUTHORISED",
                XeroInvoice.amount_due > 0,
            )
            .one()
        )
        return {"total": float(row.total or 0), "invoice_count": row.invoice_count or 0}

    def top_products(
        self,
        org_id: UUID,
        limit: int = 8,
        start_date: date | None = None,
        end_date: date | None = None,
        descending: bool = True,
    ) -> list[dict]:
        total_revenue_expr = func.sum(XeroInvoiceLineItem.line_amount)
        q = (
            self.db.query(
                XeroInvoiceLineItem.item_code,
                XeroInvoiceLineItem.description,
                func.sum(XeroInvoiceLineItem.quantity).label("total_qty"),
                total_revenue_expr.label("total_revenue"),
            )
            .join(XeroInvoice, XeroInvoiceLineItem.invoice_id == XeroInvoice.id)
            .filter(
                XeroInvoice.org_id == org_id,
                XeroInvoiceLineItem.org_id == org_id,
                XeroInvoice.invoice_type == "ACCREC",
                XeroInvoice.status.in_(["AUTHORISED", "PAID"]),
            )
        )
        if start_date:
            q = q.filter(XeroInvoice.date >= start_date)
        if end_date:
            q = q.filter(XeroInvoice.date < end_date)

        order_expr = total_revenue_expr.desc().nulls_last() if descending else total_revenue_expr.asc().nulls_last()
        rows = (
            q.group_by(XeroInvoiceLineItem.item_code, XeroInvoiceLineItem.description)
            .order_by(order_expr)
            .limit(limit)
            .all()
        )
        return [
            {
                "item_code": row.item_code,
                "description": row.description,
                "total_qty": float(row.total_qty or 0),
                "total_revenue": float(row.total_revenue or 0),
            }
            for row in rows
        ]

    def monthly_sales_totals(self, org_id: UUID, months: int = 12) -> list[dict]:
        """Return monthly invoice totals for AUTHORISED/PAID invoices (ACCREC only)."""
        rows = (
            self.db.query(
                func.date_trunc("month", XeroInvoice.date).label("month"),
                func.sum(XeroInvoice.total).label("total"),
                func.count(XeroInvoice.id).label("invoice_count"),
            )
            .filter(
                XeroInvoice.org_id == org_id,
                XeroInvoice.invoice_type == "ACCREC",
                XeroInvoice.status.in_(["AUTHORISED", "PAID"]),
                XeroInvoice.date.isnot(None),
            )
            .group_by(func.date_trunc("month", XeroInvoice.date))
            .order_by(func.date_trunc("month", XeroInvoice.date).desc())
            .limit(months)
            .all()
        )
        return [
            {
                "month": row.month.strftime("%Y-%m") if row.month else None,
                "total": float(row.total or 0),
                "invoice_count": row.invoice_count,
            }
            for row in rows
        ]

    def daily_sales_totals_for_period(self, org_id: UUID, start_date: date, end_date: date) -> list[dict]:
        """Return daily sales totals for AUTHORISED/PAID invoices (ACCREC only)."""
        rows = (
            self.db.query(
                XeroInvoice.date.label("day"),
                func.sum(XeroInvoice.total).label("total"),
                func.count(XeroInvoice.id).label("invoice_count"),
            )
            .filter(
                XeroInvoice.org_id == org_id,
                XeroInvoice.invoice_type == "ACCREC",
                XeroInvoice.status.in_(["AUTHORISED", "PAID"]),
                XeroInvoice.date.isnot(None),
                XeroInvoice.date >= start_date,
                XeroInvoice.date < end_date,
            )
            .group_by(XeroInvoice.date)
            .order_by(XeroInvoice.date.asc())
            .all()
        )
        return [
            {
                "day": row.day.isoformat() if row.day else None,
                "total": float(row.total or 0),
                "invoice_count": int(row.invoice_count or 0),
            }
            for row in rows
        ]

    def monthly_sales_totals_for_contact(
        self,
        contact_id: UUID,
        org_id: UUID,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[dict]:
        q = self.db.query(
            func.date_trunc("month", XeroInvoice.date).label("month"),
            func.sum(XeroInvoice.total).label("total"),
            func.count(XeroInvoice.id).label("invoice_count"),
        ).filter(
            XeroInvoice.org_id == org_id,
            XeroInvoice.contact_id == contact_id,
            XeroInvoice.invoice_type == "ACCREC",
            XeroInvoice.status.in_(["AUTHORISED", "PAID"]),
            XeroInvoice.date.isnot(None),
        )
        if start_date:
            q = q.filter(XeroInvoice.date >= start_date)
        if end_date:
            q = q.filter(XeroInvoice.date < end_date)
        rows = (
            q.group_by(func.date_trunc("month", XeroInvoice.date))
            .order_by(func.date_trunc("month", XeroInvoice.date).asc())
            .all()
        )
        return [
            {
                "month": row.month.strftime("%Y-%m") if row.month else None,
                "total": float(row.total or 0),
                "invoice_count": row.invoice_count,
            }
            for row in rows
        ]

    def top_products_for_contact(
        self,
        contact_id: UUID,
        org_id: UUID,
        limit: int = 8,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[dict]:
        q = (
            self.db.query(
                XeroInvoiceLineItem.item_code,
                XeroInvoiceLineItem.description,
                func.sum(XeroInvoiceLineItem.quantity).label("total_qty"),
                func.sum(XeroInvoiceLineItem.line_amount).label("total_revenue"),
            )
            .join(XeroInvoice, XeroInvoiceLineItem.invoice_id == XeroInvoice.id)
            .filter(
                XeroInvoice.org_id == org_id,
                XeroInvoice.contact_id == contact_id,
                XeroInvoiceLineItem.org_id == org_id,
                XeroInvoice.invoice_type == "ACCREC",
                XeroInvoice.status.in_(["AUTHORISED", "PAID"]),
            )
        )
        if start_date:
            q = q.filter(XeroInvoice.date >= start_date)
        if end_date:
            q = q.filter(XeroInvoice.date < end_date)
        rows = (
            q.group_by(XeroInvoiceLineItem.item_code, XeroInvoiceLineItem.description)
            .order_by(func.sum(XeroInvoiceLineItem.line_amount).desc().nulls_last())
            .limit(limit)
            .all()
        )
        return [
            {
                "item_code": row.item_code,
                "description": row.description,
                "total_qty": float(row.total_qty or 0),
                "total_revenue": float(row.total_revenue or 0),
            }
            for row in rows
        ]

    def customer_sales_breakdown(
        self,
        org_id: UUID,
        top_n: int = 20,
        start_date: date | None = None,
        end_date: date | None = None,
        descending: bool = True,
    ) -> list[dict]:
        """Per-contact sales totals."""
        from app.features.crm.models.xero_contact import XeroContact

        total_expr = func.sum(XeroInvoice.total)
        q = (
            self.db.query(
                XeroInvoice.contact_id,
                XeroContact.name.label("contact_name"),
                total_expr.label("total"),
                func.count(XeroInvoice.id).label("invoice_count"),
                func.max(XeroInvoice.date).label("last_invoice_date"),
            )
            .join(XeroContact, XeroInvoice.contact_id == XeroContact.id)
            .filter(
                XeroInvoice.org_id == org_id,
                XeroInvoice.invoice_type == "ACCREC",
                XeroInvoice.status.in_(["AUTHORISED", "PAID"]),
            )
        )
        if start_date:
            q = q.filter(XeroInvoice.date >= start_date)
        if end_date:
            q = q.filter(XeroInvoice.date < end_date)
        order_expr = total_expr.desc().nulls_last() if descending else total_expr.asc().nulls_last()
        rows = q.group_by(XeroInvoice.contact_id, XeroContact.name).order_by(order_expr).limit(top_n).all()
        return [
            {
                "contact_id": str(row.contact_id),
                "contact_name": row.contact_name,
                "total": float(row.total or 0),
                "invoice_count": row.invoice_count,
                "last_invoice_date": row.last_invoice_date.isoformat() if row.last_invoice_date else None,
            }
            for row in rows
        ]

    def top_customers_by_product(
        self,
        org_id: UUID,
        limit_products: int = 8,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[dict]:
        """Top customer per product (by line-item revenue)."""
        from app.features.crm.models.xero_contact import XeroContact

        q = (
            self.db.query(
                XeroInvoiceLineItem.item_code,
                XeroInvoiceLineItem.description,
                XeroInvoice.contact_id,
                XeroContact.name.label("contact_name"),
                func.sum(XeroInvoiceLineItem.line_amount).label("total_revenue"),
                func.sum(XeroInvoiceLineItem.quantity).label("total_qty"),
            )
            .join(XeroInvoice, XeroInvoiceLineItem.invoice_id == XeroInvoice.id)
            .join(XeroContact, XeroInvoice.contact_id == XeroContact.id)
            .filter(
                XeroInvoice.org_id == org_id,
                XeroInvoiceLineItem.org_id == org_id,
                XeroInvoice.invoice_type == "ACCREC",
                XeroInvoice.status.in_(["AUTHORISED", "PAID"]),
            )
        )
        if start_date:
            q = q.filter(XeroInvoice.date >= start_date)
        if end_date:
            q = q.filter(XeroInvoice.date < end_date)

        rows = (
            q.group_by(
                XeroInvoiceLineItem.item_code,
                XeroInvoiceLineItem.description,
                XeroInvoice.contact_id,
                XeroContact.name,
            )
            .order_by(
                XeroInvoiceLineItem.description.asc().nulls_last(),
                func.sum(XeroInvoiceLineItem.line_amount).desc().nulls_last(),
            )
            .all()
        )

        best_by_product: dict[tuple[str, str], dict] = {}
        for row in rows:
            key = (row.item_code or "", row.description or "")
            current = best_by_product.get(key)
            total = float(row.total_revenue or 0)
            if current is None or total > current["top_customer_revenue"]:
                best_by_product[key] = {
                    "item_code": row.item_code,
                    "description": row.description,
                    "top_customer_id": str(row.contact_id) if row.contact_id else None,
                    "top_customer_name": row.contact_name,
                    "top_customer_revenue": total,
                    "total_qty": float(row.total_qty or 0),
                }

        ranked = sorted(best_by_product.values(), key=lambda x: x["top_customer_revenue"], reverse=True)
        return ranked[:limit_products]

    def customer_product_breakdown(
        self,
        org_id: UUID,
        limit: int = 20,
        start_date: date | None = None,
        end_date: date | None = None,
        descending: bool = True,
    ) -> list[dict]:
        from app.features.crm.models.xero_contact import XeroContact

        revenue_expr = func.sum(XeroInvoiceLineItem.line_amount)
        q = (
            self.db.query(
                XeroInvoice.contact_id,
                XeroContact.name.label("contact_name"),
                XeroInvoiceLineItem.item_code,
                XeroInvoiceLineItem.description,
                func.sum(XeroInvoiceLineItem.quantity).label("total_qty"),
                revenue_expr.label("total_revenue"),
                func.count(func.distinct(XeroInvoice.id)).label("invoice_count"),
            )
            .join(XeroInvoice, XeroInvoiceLineItem.invoice_id == XeroInvoice.id)
            .join(XeroContact, XeroInvoice.contact_id == XeroContact.id)
            .filter(
                XeroInvoice.org_id == org_id,
                XeroInvoiceLineItem.org_id == org_id,
                XeroInvoice.invoice_type == "ACCREC",
                XeroInvoice.status.in_(["AUTHORISED", "PAID"]),
            )
        )
        if start_date:
            q = q.filter(XeroInvoice.date >= start_date)
        if end_date:
            q = q.filter(XeroInvoice.date < end_date)
        order_expr = revenue_expr.desc().nulls_last() if descending else revenue_expr.asc().nulls_last()
        rows = (
            q.group_by(
                XeroInvoice.contact_id,
                XeroContact.name,
                XeroInvoiceLineItem.item_code,
                XeroInvoiceLineItem.description,
            )
            .order_by(order_expr)
            .limit(limit)
            .all()
        )
        return [
            {
                "contact_id": str(row.contact_id) if row.contact_id else None,
                "contact_name": row.contact_name,
                "item_code": row.item_code,
                "description": row.description,
                "total_qty": float(row.total_qty or 0),
                "total_revenue": float(row.total_revenue or 0),
                "invoice_count": int(row.invoice_count or 0),
            }
            for row in rows
        ]

    def churn_risk_data(self, org_id: UUID) -> list[dict]:
        """Last purchase date + avg repeat interval per customer."""

        from app.features.crm.models.xero_contact import XeroContact

        rows = (
            self.db.query(
                XeroInvoice.contact_id,
                XeroContact.name.label("contact_name"),
                func.max(XeroInvoice.date).label("last_invoice_date"),
                func.min(XeroInvoice.date).label("first_invoice_date"),
                func.count(XeroInvoice.id).label("invoice_count"),
                func.sum(XeroInvoice.total).label("lifetime_value"),
            )
            .join(XeroContact, XeroInvoice.contact_id == XeroContact.id)
            .filter(
                XeroInvoice.org_id == org_id,
                XeroInvoice.invoice_type == "ACCREC",
                XeroInvoice.status.in_(["AUTHORISED", "PAID"]),
            )
            .group_by(XeroInvoice.contact_id, XeroContact.name)
            .having(func.count(XeroInvoice.id) >= 1)
            .order_by(func.max(XeroInvoice.date).asc())
            .all()
        )

        from datetime import date

        today = date.today()

        results = []
        for row in rows:
            days_since = (today - row.last_invoice_date).days if row.last_invoice_date else None
            count = row.invoice_count
            avg_days_between = None
            if count > 1 and row.first_invoice_date and row.last_invoice_date:
                span = (row.last_invoice_date - row.first_invoice_date).days
                avg_days_between = round(span / (count - 1)) if count > 1 else None

            risk_tier = "low"
            if days_since is not None and avg_days_between is not None:
                if days_since > avg_days_between * 2:
                    risk_tier = "high"
                elif days_since > avg_days_between * 1.5:
                    risk_tier = "medium"
            elif days_since is not None and days_since > 90:
                risk_tier = "high"
            elif days_since is not None and days_since > 45:
                risk_tier = "medium"

            results.append(
                {
                    "contact_id": str(row.contact_id),
                    "contact_name": row.contact_name,
                    "last_invoice_date": row.last_invoice_date.isoformat() if row.last_invoice_date else None,
                    "days_since_last_invoice": days_since,
                    "invoice_count": count,
                    "avg_days_between_purchases": avg_days_between,
                    "lifetime_value": float(row.lifetime_value or 0),
                    "risk_tier": risk_tier,
                }
            )

        return results

    def count_for_org(self, org_id: UUID) -> int:
        return self.db.query(XeroInvoice).filter(XeroInvoice.org_id == org_id).count()
