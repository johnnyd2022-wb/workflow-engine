"""Suppliers an organisation buys from, kept as a small address book in Core."""

import uuid

from sqlalchemy import TIMESTAMP, Column, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID

from app.core.db.models.models import Base
from app.core.db.models.tenant_mixin import TenantScoped
from app.core.utils.time import utc_now


class Supplier(TenantScoped, Base):
    __tablename__ = "suppliers"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    contact_name = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    email = Column(String(255), nullable=True)
    address = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


# A supplier is one entry per organisation, however it is capitalised.
Index("uq_suppliers_org_name_lower", Supplier.org_id, func.lower(Supplier.name), unique=True)
