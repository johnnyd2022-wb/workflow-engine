"""XeroInvoice — a Xero invoice synced into the CRM."""

import uuid
from datetime import datetime

from sqlalchemy import TIMESTAMP, Column, Date, ForeignKey, Index, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.core.db.models.models import Base


class XeroInvoice(Base):
    __tablename__ = "xero_invoices"
    __table_args__ = (
        UniqueConstraint("org_id", "xero_invoice_id", name="uq_xero_invoices_org_xero"),
        Index("ix_xero_invoices_contact_id", "contact_id"),
        Index("ix_xero_invoices_org_status", "org_id", "status"),
        Index("ix_xero_invoices_org_date", "org_id", "date"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True)
    xero_invoice_id = Column(String(100), nullable=False)
    xero_tenant_id = Column(String(100), nullable=False)
    # FK to our xero_contacts table (nullable — contact may not be synced yet)
    contact_id = Column(UUID(as_uuid=True), ForeignKey("xero_contacts.id", ondelete="SET NULL"), nullable=True)
    xero_contact_id = Column(String(100), nullable=True)
    invoice_number = Column(String(100), nullable=True)
    reference = Column(String(255), nullable=True)
    invoice_type = Column(String(20), nullable=True)  # ACCREC | ACCPAY
    status = Column(String(50), nullable=True)  # DRAFT | AUTHORISED | PAID | VOIDED | DELETED
    sub_total = Column(Numeric(18, 4), nullable=True)
    total_tax = Column(Numeric(18, 4), nullable=True)
    total = Column(Numeric(18, 4), nullable=True)
    amount_due = Column(Numeric(18, 4), nullable=True)
    amount_paid = Column(Numeric(18, 4), nullable=True)
    currency_code = Column(String(3), nullable=True, default="NZD")
    date = Column(Date, nullable=True)
    due_date = Column(Date, nullable=True)
    fully_paid_on_date = Column(Date, nullable=True)
    xero_updated_at = Column(TIMESTAMP(timezone=True), nullable=True)
    last_synced_at = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<XeroInvoice(id={self.id}, number={self.invoice_number!r}, status={self.status!r})>"
