"""XeroContact — a Xero Contact synced into the CRM."""

import uuid
from datetime import datetime

from sqlalchemy import TIMESTAMP, Boolean, Column, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.db.models.models import Base


class XeroContact(Base):
    __tablename__ = "xero_contacts"
    __table_args__ = (
        UniqueConstraint("org_id", "xero_contact_id", name="uq_xero_contacts_org_xero"),
        Index("ix_xero_contacts_org_name", "org_id", "name"),
        Index("ix_xero_contacts_org_email", "org_id", "email_address"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True)
    xero_contact_id = Column(String(100), nullable=False)
    xero_tenant_id = Column(String(100), nullable=False)
    name = Column(String(500), nullable=False)
    first_name = Column(String(255), nullable=True)
    last_name = Column(String(255), nullable=True)
    email_address = Column(String(255), nullable=True)
    phone_number = Column(String(50), nullable=True)
    addresses = Column(JSONB, nullable=True)
    tax_number = Column(String(50), nullable=True)
    account_number = Column(String(50), nullable=True)
    contact_status = Column(String(50), nullable=True)
    is_customer = Column(Boolean, nullable=False, default=True)
    is_supplier = Column(Boolean, nullable=False, default=False)
    xero_updated_at = Column(TIMESTAMP(timezone=True), nullable=True)
    last_synced_at = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<XeroContact(id={self.id}, name={self.name!r}, org_id={self.org_id})>"
