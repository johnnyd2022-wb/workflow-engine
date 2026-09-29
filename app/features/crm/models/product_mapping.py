"""ProductMapping — links a Biz-e product name to a Xero invoice line item description pattern."""

import uuid

from sqlalchemy import TIMESTAMP, Boolean, Column, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.core.db.models.models import Base
from app.core.db.models.tenant_mixin import TenantScoped
from app.core.utils.time import utc_now


class ProductMapping(TenantScoped, Base):
    __tablename__ = "product_mappings"
    __table_args__ = (
        UniqueConstraint(
            "org_id", "biz_e_product_name", "xero_description_pattern", name="uq_product_mappings_org_biz_xero"
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    biz_e_source_output_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    biz_e_product_name = Column(String(500), nullable=False)
    xero_description_pattern = Column(String(500), nullable=False)
    match_type = Column(String(50), nullable=False, default="exact")  # exact | contains | alias
    is_active = Column(Boolean, nullable=False, default=True)
    # Stock units one invoice-line quantity takes: 6 for "Case of 6". Plan 1.2.
    units_per_line = Column(Integer, nullable=False, default=1, server_default="1")
    notes = Column(Text, nullable=True)
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    def __repr__(self) -> str:
        return (
            f"<ProductMapping(id={self.id}, biz_e={self.biz_e_product_name!r}, xero={self.xero_description_pattern!r})>"
        )
