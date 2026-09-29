"""Stocktakes (plan 2.6): counts, differences, and how each difference was resolved."""

import uuid

from sqlalchemy import TIMESTAMP, Boolean, Column, Date, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.core.db.models.models import Base
from app.core.db.models.tenant_mixin import TenantScoped
from app.core.utils.time import utc_now


class Stocktake(TenantScoped, Base):
    __tablename__ = "stocktakes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    counted_on = Column(Date, nullable=False)
    kind = Column(String(20), nullable=False, default="scheduled", server_default="scheduled")
    status = Column(String(20), nullable=False, default="counting", server_default="counting")
    note = Column(String(500), nullable=True)
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=utc_now)
    completed_at = Column(TIMESTAMP(timezone=True), nullable=True)


class StocktakeLine(TenantScoped, Base):
    __tablename__ = "stocktake_lines"
    __table_args__ = (UniqueConstraint("stocktake_id", "inventory_item_id", name="uq_stocktake_lines_item"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    stocktake_id = Column(UUID(as_uuid=True), ForeignKey("stocktakes.id", ondelete="CASCADE"), nullable=False)
    inventory_item_id = Column(
        UUID(as_uuid=True), ForeignKey("inventory_items.id", ondelete="RESTRICT"), nullable=False
    )
    expected_quantity = Column(Numeric(18, 4), nullable=False)
    counted_quantity = Column(Numeric(18, 4), nullable=True)
    unit = Column(String(50), nullable=False)
    status = Column(String(20), nullable=False, default="open", server_default="open")
    investigate_until = Column(Date, nullable=True)


class StocktakeResolution(TenantScoped, Base):
    __tablename__ = "stocktake_resolutions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    line_id = Column(UUID(as_uuid=True), ForeignKey("stocktake_lines.id", ondelete="CASCADE"), nullable=False)
    reason = Column(String(40), nullable=False)
    quantity = Column(Numeric(18, 4), nullable=False)
    location_id = Column(UUID(as_uuid=True), ForeignKey("stock_locations.id"), nullable=True)
    occurred_on = Column(Date, nullable=True)
    note = Column(String(500), nullable=True)
    dutiable = Column(Boolean, nullable=False, default=False, server_default="false")
    raise_with_customs = Column(Boolean, nullable=False, default=False, server_default="false")
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=utc_now)
