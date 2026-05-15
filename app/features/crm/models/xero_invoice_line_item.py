"""XeroInvoiceLineItem — a single line on a Xero invoice."""

import uuid
from datetime import datetime

from sqlalchemy import TIMESTAMP, Column, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.db.models.models import Base


class XeroInvoiceLineItem(Base):
    __tablename__ = "xero_invoice_line_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True)
    invoice_id = Column(
        UUID(as_uuid=True), ForeignKey("xero_invoices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    xero_line_item_id = Column(String(100), nullable=True)
    description = Column(Text, nullable=True)
    item_code = Column(String(100), nullable=True)
    quantity = Column(Numeric(18, 4), nullable=True)
    unit_amount = Column(Numeric(18, 4), nullable=True)
    line_amount = Column(Numeric(18, 4), nullable=True)
    account_code = Column(String(50), nullable=True)
    tax_type = Column(String(50), nullable=True)
    tax_amount = Column(Numeric(18, 4), nullable=True)
    discount_rate = Column(Numeric(5, 2), nullable=True)
    tracking = Column(JSONB, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<XeroInvoiceLineItem(id={self.id}, invoice_id={self.invoice_id}, desc={self.description!r:.40})>"
