"""Xero accounts-receivable credit notes synced into the CRM."""

import uuid

from sqlalchemy import TIMESTAMP, Column, Date, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.db.models.models import Base
from app.core.db.models.tenant_mixin import TenantScoped
from app.core.utils.time import utc_now


class XeroCreditNote(TenantScoped, Base):
    __tablename__ = "xero_credit_notes"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_xero_credit_notes_org_id"),
        UniqueConstraint("org_id", "xero_credit_note_id", name="uq_xero_credit_notes_org_xero"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    xero_credit_note_id = Column(String(100), nullable=False)
    xero_tenant_id = Column(String(100), nullable=False)
    number = Column(String(100), nullable=True)
    contact = Column(String(255), nullable=True)
    date = Column(Date, nullable=True)
    status = Column(String(50), nullable=False)
    total = Column(Numeric(18, 4), nullable=False, default=0)
    currency = Column(String(3), nullable=False, default="NZD")
    allocated_invoice_ids = Column(JSONB, nullable=False, default=list)
    raw_fields = Column(JSONB, nullable=False, default=dict)
    xero_updated_at = Column(TIMESTAMP(timezone=True), nullable=True)
    last_synced_at = Column(TIMESTAMP(timezone=True), nullable=False, default=utc_now)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

