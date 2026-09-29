"""Alcohol-specific product attributes required for reconciliation across product types."""

import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.core.db.models.models import Base
from app.core.utils.time import utc_now


class AlcoholProductProfile(Base):
    __tablename__ = "compliance_alcohol_product_profiles"
    __table_args__ = (
        UniqueConstraint("org_id", "inventory_name", name="uq_compliance_alcohol_product_org_name"),
        Index("ix_compliance_alcohol_product_org_type", "org_id", "product_type"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    inventory_name = Column(String(255), nullable=False)
    product_type = Column(String(40), nullable=False)
    # Fallback only (plan 2.1): the batch's final-step ABV is the source when recorded.
    abv_percent = Column(Numeric(7, 4), nullable=True)
    # Pack size for litres of alcohol, e.g. 700 for a 700 mL bottle.
    pack_volume_ml = Column(Numeric(10, 2), nullable=True)
    customs_product_code = Column(String(100), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
