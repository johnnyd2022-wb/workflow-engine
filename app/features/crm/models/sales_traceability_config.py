"""Org-level CRM sales traceability configuration."""

import uuid

from sqlalchemy import TIMESTAMP, Boolean, Column, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.core.db.models.models import Base
from app.core.utils.time import utc_now


class SalesTraceabilityConfig(Base):
    __tablename__ = "crm_sales_traceability_config"
    __table_args__ = (
        UniqueConstraint("org_id", name="uq_crm_sales_traceability_org"),
        Index("ix_crm_sales_traceability_org", "org_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    matching_strategy = Column(String(30), nullable=False, default="fifo")  # fifo | manual | hybrid
    matching_key = Column(String(30), nullable=False, default="batch_id")
    manual_review_days = Column(Integer, nullable=False, default=7)
    strict_mapping = Column(Boolean, nullable=False, default=True)
    task_done_archive_days = Column(Integer, nullable=False, default=7)
    revenue_baseline_target_mtd = Column(Numeric(12, 2), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    def __repr__(self) -> str:
        return f"<SalesTraceabilityConfig(org_id={self.org_id}, strategy={self.matching_strategy!r})>"
