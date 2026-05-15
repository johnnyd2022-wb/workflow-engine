"""XeroTenant — tracks a connected Xero organisation per Biz-e org."""

import uuid
from datetime import datetime

from sqlalchemy import TIMESTAMP, Boolean, Column, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.core.db.models.models import Base


class XeroTenant(Base):
    __tablename__ = "xero_tenants"
    __table_args__ = (UniqueConstraint("org_id", "xero_tenant_id", name="uq_xero_tenants_org_xero"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True)
    xero_tenant_id = Column(String(100), nullable=False)
    xero_connection_id = Column(String(100), nullable=True)
    xero_tenant_name = Column(String(255), nullable=True)
    xero_tenant_type = Column(String(50), nullable=True)
    is_connected = Column(Boolean, nullable=False, default=True)
    connected_at = Column(TIMESTAMP(timezone=True), nullable=True)
    disconnected_at = Column(TIMESTAMP(timezone=True), nullable=True)
    last_successful_sync_at = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<XeroTenant(id={self.id}, org_id={self.org_id}, name={self.xero_tenant_name!r})>"
