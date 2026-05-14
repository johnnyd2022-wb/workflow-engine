"""Repository for XeroInvoice and XeroInvoiceLineItem records."""

import uuid
from datetime import datetime
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

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
            inv.last_synced_at = datetime.utcnow()
            inv.updated_at = datetime.utcnow()
        else:
            inv = XeroInvoice(
                id=uuid.uuid4(),  # generate now so inv.id is available before flush
                org_id=org_id,
                xero_invoice_id=xero_invoice_id,
                xero_tenant_id=xero_tenant_id,
                contact_id=contact_id,
                last_synced_at=datetime.utcnow(),
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

    def get_line_items(self, invoice_id: UUID) -> list[XeroInvoiceLineItem]:
        return self.db.query(XeroInvoiceLineItem).filter(XeroInvoiceLineItem.invoice_id == invoice_id).all()

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

    def customer_sales_breakdown(self, org_id: UUID, top_n: int = 20) -> list[dict]:
        """Per-contact sales totals."""
        from app.features.crm.models.xero_contact import XeroContact

        rows = (
            self.db.query(
                XeroInvoice.contact_id,
                XeroContact.name.label("contact_name"),
                func.sum(XeroInvoice.total).label("total"),
                func.count(XeroInvoice.id).label("invoice_count"),
                func.max(XeroInvoice.date).label("last_invoice_date"),
            )
            .join(XeroContact, XeroInvoice.contact_id == XeroContact.id)
            .filter(
                XeroInvoice.org_id == org_id,
                XeroInvoice.invoice_type == "ACCREC",
                XeroInvoice.status.in_(["AUTHORISED", "PAID"]),
            )
            .group_by(XeroInvoice.contact_id, XeroContact.name)
            .order_by(func.sum(XeroInvoice.total).desc())
            .limit(top_n)
            .all()
        )
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
