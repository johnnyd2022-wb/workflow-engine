"""Durable per-batch allocations for Xero sales consumed through Core FIFO."""

import uuid

from sqlalchemy import TIMESTAMP, Boolean, Column, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

import app.features.crm.models.product_mapping  # noqa: F401 -- registers the "product_mappings" table this model points at
from app.core.db.models.models import Base
from app.core.db.models.tenant_mixin import TenantScoped
from app.core.utils.time import utc_now


class SalesFifoAllocation(TenantScoped, Base):
    """One labelled final-product batch consumed by one stable Xero invoice-line key."""

    __tablename__ = "crm_sales_fifo_allocations"
    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "xero_invoice_id",
            "xero_line_key",
            "inventory_item_id",
            name="uq_crm_sales_fifo_allocation_line_item",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    xero_invoice_id = Column(String(100), nullable=False, index=True)
    xero_line_key = Column(String(160), nullable=False)
    inventory_item_id = Column(
        UUID(as_uuid=True), ForeignKey("inventory_items.id", ondelete="RESTRICT"), nullable=False
    )
    product_mapping_id = Column(
        UUID(as_uuid=True), ForeignKey("product_mappings.id", ondelete="SET NULL"), nullable=True
    )
    product_name = Column(String(500), nullable=False)
    quantity = Column(Numeric(18, 4), nullable=False)
    unit = Column(String(50), nullable=False)
    # Plan 1.1: "confirmed" or "pending_review" (hybrid mode, until review_due_at).
    status = Column(String(20), nullable=False, default="confirmed", server_default="confirmed")
    # Filled from a batch made after the invoice date: a pre-sale, shown not blocked.
    presold = Column(Boolean, nullable=False, default=False, server_default="false")
    review_due_at = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=utc_now)

    def __repr__(self) -> str:
        return (
            f"<SalesFifoAllocation(invoice={self.xero_invoice_id!r}, "
            f"line={self.xero_line_key!r}, item={self.inventory_item_id})>"
        )
