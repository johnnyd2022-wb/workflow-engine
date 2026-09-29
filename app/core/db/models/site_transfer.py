"""Dispatch, receipt and confirmed transit loss facts, separate from shelf stock."""

import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.db.models.models import Base
from app.core.db.models.tenant_mixin import TenantScoped
from app.core.utils.time import utc_now


class SiteStockTransfer(TenantScoped, Base):
    __tablename__ = "site_stock_transfers"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_site_stock_transfers_org_id"),
        UniqueConstraint("org_id", "idempotency_key", name="uq_site_transfer_dispatch_key"),
        ForeignKeyConstraint(
            ["org_id", "created_by_user_id"], ["users.org_id", "users.id"], name="fk_site_transfer_actor"
        ),
        ForeignKeyConstraint(
            ["org_id", "source_item_id"],
            ["inventory_items.org_id", "inventory_items.id"],
            name="fk_site_transfer_source_item",
        ),
        ForeignKeyConstraint(
            ["org_id", "source_site_id"], ["sites.org_id", "sites.id"], name="fk_site_transfer_source_site"
        ),
        ForeignKeyConstraint(
            ["org_id", "destination_site_id"], ["sites.org_id", "sites.id"], name="fk_site_transfer_destination_site"
        ),
        ForeignKeyConstraint(
            ["org_id", "source_site_id", "source_location_id"],
            ["stock_locations.org_id", "stock_locations.site_id", "stock_locations.id"],
            name="fk_site_transfer_source_location",
        ),
        ForeignKeyConstraint(
            ["org_id", "destination_site_id", "destination_location_id"],
            ["stock_locations.org_id", "stock_locations.site_id", "stock_locations.id"],
            name="fk_site_transfer_destination_location",
        ),
        CheckConstraint(
            "quantity > 0 AND received_quantity >= 0 AND loss_quantity >= 0 AND received_quantity + loss_quantity <= quantity",
            name="ck_site_transfer_conservation",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_item_id = Column(UUID(as_uuid=True), nullable=False)
    source_site_id = Column(UUID(as_uuid=True), nullable=False)
    destination_site_id = Column(UUID(as_uuid=True), nullable=False)
    source_location_id = Column(UUID(as_uuid=True), nullable=True)
    destination_location_id = Column(UUID(as_uuid=True), nullable=True)
    quantity = Column(Numeric(18, 4), nullable=False)
    received_quantity = Column(Numeric(18, 4), nullable=False, default=0, server_default="0")
    loss_quantity = Column(Numeric(18, 4), nullable=False, default=0, server_default="0")
    unit = Column(String(50), nullable=False)
    carrier = Column(String(120), nullable=False)
    consignment_reference = Column(String(160), nullable=False)
    occurred_on = Column(Date, nullable=False)
    source_snapshot = Column(JSONB, nullable=False)
    decision_snapshot = Column(JSONB, nullable=False)
    idempotency_key = Column(String(128), nullable=False)
    request_hash = Column(String(64), nullable=False)
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class SiteStockReceipt(TenantScoped, Base):
    __tablename__ = "site_stock_receipts"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_site_stock_receipts_org_id"),
        UniqueConstraint("org_id", "idempotency_key", name="uq_site_transfer_receipt_key"),
        ForeignKeyConstraint(
            ["org_id", "created_by_user_id"], ["users.org_id", "users.id"], name="fk_site_receipt_actor"
        ),
        ForeignKeyConstraint(
            ["org_id", "transfer_id"],
            ["site_stock_transfers.org_id", "site_stock_transfers.id"],
            name="fk_site_stock_receipt_transfer",
        ),
        CheckConstraint(
            "quantity >= 0 AND damaged_quantity >= 0 AND short_quantity >= 0 AND quantity + damaged_quantity + short_quantity > 0",
            name="ck_site_receipt_quantities",
        ),
        CheckConstraint(
            "(damaged_quantity + short_quantity = 0) OR (loss_reason IS NOT NULL AND length(trim(loss_reason)) > 0)",
            name="ck_site_receipt_loss_reason",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    transfer_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    quantity = Column(Numeric(18, 4), nullable=False)
    damaged_quantity = Column(Numeric(18, 4), nullable=False, default=0, server_default="0")
    short_quantity = Column(Numeric(18, 4), nullable=False, default=0, server_default="0")
    loss_reason = Column(String(500), nullable=True)
    occurred_on = Column(Date, nullable=False)
    decision_snapshot = Column(JSONB, nullable=False)
    idempotency_key = Column(String(128), nullable=False)
    request_hash = Column(String(64), nullable=False)
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
