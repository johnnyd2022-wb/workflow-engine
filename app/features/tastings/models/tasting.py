"""Tasting events and a separate physical, duty-recorded sampling stock ledger."""

import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import backref, relationship

from app.core.db.models.models import Base
from app.core.db.models.tenant_mixin import TenantScoped
from app.core.utils.time import utc_now


class Tasting(TenantScoped, Base):
    __tablename__ = "tastings"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_tastings_org_id"),
        UniqueConstraint("task_id", name="uq_tastings_task"),
        ForeignKeyConstraint(
            ["org_id", "task_id"], ["crm_tasks.org_id", "crm_tasks.id"], name="fk_tasting_org_task", ondelete="RESTRICT"
        ),
        UniqueConstraint("org_id", "dispatch_key", name="uq_tastings_dispatch_key"),
        CheckConstraint("status IN ('planned','dispatched','completed','cancelled')", name="ck_tasting_status"),
        CheckConstraint("venue_type IN ('own','external')", name="ck_tasting_venue"),
        CheckConstraint("ends_at > starts_at", name="ck_tasting_times"),
        Index("ix_tastings_org_start", "org_id", "starts_at"),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id = Column(UUID(as_uuid=True), ForeignKey("crm_tasks.id", ondelete="RESTRICT"), nullable=False)
    title = Column(String(160), nullable=False)
    venue_name = Column(String(160), nullable=False)
    venue_address = Column(String(500), nullable=False)
    venue_type = Column(String(20), nullable=False)
    licence_reference = Column(String(160), nullable=True)
    starts_at = Column(DateTime(timezone=True), nullable=False)
    ends_at = Column(DateTime(timezone=True), nullable=False)
    rep_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    contact_id = Column(UUID(as_uuid=True), ForeignKey("xero_contacts.id", ondelete="RESTRICT"))
    status = Column(String(20), nullable=False, default="planned")
    notes = Column(Text, nullable=False, default="")
    dispatch_key = Column(String(100))
    dispatch_hash = Column(String(64))
    finalise_hash = Column(String(64))
    dispatched_on = Column(Date)
    outcome_notes = Column(Text, nullable=False, default="")
    samples_count = Column(Integer)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    dispatched_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"))
    finalised_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"))
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
    task = relationship("CRMTask", backref=backref("tasting", lazy="selectin"), uselist=False, foreign_keys=[task_id])


class TastingStockLot(TenantScoped, Base):
    __tablename__ = "tasting_stock_lots"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_tasting_stock_org_id"),
        ForeignKeyConstraint(
            ["org_id", "tasting_id"], ["tastings.org_id", "tastings.id"], name="fk_tasting_stock_event"
        ),
        ForeignKeyConstraint(
            ["org_id", "source_item_id"],
            ["inventory_items.org_id", "inventory_items.id"],
            name="fk_tasting_stock_source",
        ),
        CheckConstraint(
            "initial_volume_ml > 0 AND remaining_volume_ml >= 0 AND reserved_volume_ml >= 0 AND remaining_volume_ml <= initial_volume_ml AND reserved_volume_ml <= remaining_volume_ml",
            name="ck_tasting_stock_conservation",
        ),
        Index("ix_tasting_stock_org_removal", "org_id", "removed_on"),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tasting_id = Column(UUID(as_uuid=True), nullable=False)
    source_item_id = Column(UUID(as_uuid=True), nullable=False)
    purpose = Column(String(20), nullable=False, default="tasting", server_default="tasting")
    quantity = Column(Numeric(18, 4), nullable=False)
    unit = Column(String(50), nullable=False)
    initial_volume_ml = Column(Numeric(18, 4), nullable=False)
    remaining_volume_ml = Column(Numeric(18, 4), nullable=False)
    reserved_volume_ml = Column(Numeric(18, 4), nullable=False)
    removed_on = Column(Date, nullable=False)
    creates_removal = Column(Integer, nullable=False, default=1)
    snapshot = Column(JSONB, nullable=False)
    recorded_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class TastingAllocation(TenantScoped, Base):
    __tablename__ = "tasting_allocations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "tasting_id"], ["tastings.org_id", "tastings.id"], name="fk_tasting_allocation_event"
        ),
        ForeignKeyConstraint(
            ["org_id", "source_item_id"],
            ["inventory_items.org_id", "inventory_items.id"],
            name="fk_tasting_allocation_source",
        ),
        ForeignKeyConstraint(
            ["org_id", "source_pool_id"],
            ["tasting_stock_lots.org_id", "tasting_stock_lots.id"],
            name="fk_tasting_allocation_pool",
        ),
        ForeignKeyConstraint(
            ["org_id", "stock_lot_id"],
            ["tasting_stock_lots.org_id", "tasting_stock_lots.id"],
            name="fk_tasting_allocation_dispatched_pool",
        ),
        CheckConstraint(
            "(source_item_id IS NULL) <> (source_pool_id IS NULL)", name="ck_tasting_allocation_one_source"
        ),
        CheckConstraint(
            "quantity > 0 AND reserved_volume_ml >= 0 AND used_volume_ml >= 0 AND used_volume_ml <= reserved_volume_ml",
            name="ck_tasting_allocation_amount",
        ),
        Index("ix_tasting_allocation_org_event", "org_id", "tasting_id"),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tasting_id = Column(UUID(as_uuid=True), nullable=False)
    source_item_id = Column(UUID(as_uuid=True))
    source_pool_id = Column(UUID(as_uuid=True))
    stock_lot_id = Column(UUID(as_uuid=True))
    quantity = Column(Numeric(18, 4), nullable=False)
    reserved_volume_ml = Column(Numeric(18, 4), nullable=False, default=0)
    used_volume_ml = Column(Numeric(18, 4), nullable=False, default=0)
    state = Column(String(20), nullable=False, default="planned")
