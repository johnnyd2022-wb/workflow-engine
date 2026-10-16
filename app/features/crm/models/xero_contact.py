"""XeroContact — a sales contact: synced in from Xero, or created in Biz-E and optionally sent to Xero."""

import uuid

from sqlalchemy import TIMESTAMP, Boolean, CheckConstraint, Column, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.db.models.models import Base
from app.core.db.models.tenant_mixin import TenantScoped
from app.core.utils.time import utc_now


class XeroContact(TenantScoped, Base):
    __tablename__ = "xero_contacts"
    __table_args__ = (
        UniqueConstraint("org_id", "xero_contact_id", name="uq_xero_contacts_org_xero"),
        Index("ix_xero_contacts_org_name", "org_id", "name"),
        Index("ix_xero_contacts_org_email", "org_id", "email_address"),
        # Only a contact created in Biz-E may be without a Xero id (until it is sent to Xero).
        CheckConstraint("source = 'bize' OR xero_contact_id IS NOT NULL", name="ck_xero_contacts_xero_id_unless_bize"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    xero_contact_id = Column(String(100), nullable=True)
    xero_tenant_id = Column(String(100), nullable=True)
    # "xero": arrived from Xero. "bize": created in Biz-E; it reaches Xero only when its sync is on.
    source = Column(String(10), nullable=False, default="xero", server_default="xero")
    # Per-contact choice for a Biz-E contact: None follows the Sales default
    # (SalesTraceabilityConfig.sync_contacts_to_xero).
    sync_to_xero = Column(Boolean, nullable=True)
    # Outcome of the last send to Xero: "synced", or "failed" with the reason. A failed send
    # leaves local changes Xero has not seen, so the Xero pull does not overwrite them.
    xero_push_status = Column(String(20), nullable=True)
    xero_push_error = Column(Text, nullable=True)
    xero_pushed_at = Column(TIMESTAMP(timezone=True), nullable=True)
    name = Column(String(500), nullable=False)
    first_name = Column(String(255), nullable=True)
    last_name = Column(String(255), nullable=True)
    email_address = Column(String(255), nullable=True)
    phone_number = Column(String(50), nullable=True)
    addresses = Column(JSONB, nullable=True)
    payment_terms = Column(JSONB, nullable=True)
    tax_number = Column(String(50), nullable=True)
    account_number = Column(String(50), nullable=True)
    contact_status = Column(String(50), nullable=True)
    is_customer = Column(Boolean, nullable=False, default=True)
    is_supplier = Column(Boolean, nullable=False, default=False)
    xero_updated_at = Column(TIMESTAMP(timezone=True), nullable=True)
    last_synced_at = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    def __repr__(self) -> str:
        return f"<XeroContact(id={self.id}, name={self.name!r}, org_id={self.org_id})>"
