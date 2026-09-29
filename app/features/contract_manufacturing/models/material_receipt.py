"""Immutable evidence for a customer-owned raw lot, distinct from purchase stock."""

import uuid

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKeyConstraint, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.db.models.models import Base
from app.core.db.models.tenant_mixin import TenantScoped
from app.core.utils.time import utc_now


class ContractMaterialReceipt(TenantScoped, Base):
    __tablename__ = "contract_material_receipts"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_material_receipt_quantity"),
        UniqueConstraint("org_id", "id", name="uq_material_receipt_org_id"),
        UniqueConstraint("org_id", "customer_id", "id", "inventory_item_id", name="uq_material_receipt_owner_lot"),
        UniqueConstraint("org_id", "idempotency_key", name="uq_material_receipt_key"),
        ForeignKeyConstraint(
            ["org_id", "customer_id"], ["contract_customers.org_id", "contract_customers.id"], ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["org_id", "inventory_item_id"],
            ["inventory_items.org_id", "inventory_items.id"],
            deferrable=True,
            initially="DEFERRED",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(["org_id", "received_by"], ["users.org_id", "users.id"], ondelete="RESTRICT"),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id = Column(UUID(as_uuid=True), nullable=False)
    inventory_item_id = Column(UUID(as_uuid=True), nullable=False)
    quantity = Column(Numeric(18, 4), nullable=False)
    unit = Column(String(50), nullable=False)
    evidence_reference = Column(String(255), nullable=False)
    stock_snapshot = Column(JSONB, nullable=False)
    idempotency_key = Column(String(128), nullable=False)
    request_hash = Column(String(64), nullable=False)
    received_by = Column(UUID(as_uuid=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
