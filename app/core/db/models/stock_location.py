"""Where stock is, and moves between places (plan 2.1).

An inventory item with no location is in the main licensed (Customs-controlled) area,
which is where everything was before locations existed.
"""

import uuid

from sqlalchemy import (
    TIMESTAMP,
    Boolean,
    Column,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID

from app.core.db.models.models import Base
from app.core.db.models.tenant_mixin import TenantScoped
from app.core.utils.time import utc_now


class StockLocation(TenantScoped, Base):
    __tablename__ = "stock_locations"
    __table_args__ = (
        UniqueConstraint("org_id", "name", name="uq_stock_locations_org_name"),
        UniqueConstraint("org_id", "id", name="uq_stock_locations_org_id"),
        UniqueConstraint("org_id", "site_id", "id", name="uq_stock_locations_org_site_id"),
        ForeignKeyConstraint(
            ["org_id", "site_id"], ["sites.org_id", "sites.id"], name="fk_stock_locations_org_site", ondelete="RESTRICT"
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(120), nullable=False)
    site_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    inside_licensed_area = Column(Boolean, nullable=False, default=False, server_default="false")
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=utc_now)


class StockTransfer(TenantScoped, Base):
    """Part of a lot moved to another location, as a new lot with the same lineage."""

    __tablename__ = "stock_transfers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    from_item_id = Column(UUID(as_uuid=True), ForeignKey("inventory_items.id", ondelete="RESTRICT"), nullable=False)
    to_item_id = Column(UUID(as_uuid=True), ForeignKey("inventory_items.id", ondelete="RESTRICT"), nullable=False)
    from_location_id = Column(UUID(as_uuid=True), ForeignKey("stock_locations.id"), nullable=True)
    to_location_id = Column(UUID(as_uuid=True), ForeignKey("stock_locations.id"), nullable=True)
    quantity = Column(Numeric(18, 4), nullable=False)
    unit = Column(String(50), nullable=False)
    # "out" = left the licensed area (an excise removal), "in" = came back, else "internal".
    direction = Column(String(10), nullable=False, default="internal", server_default="internal")
    occurred_on = Column(Date, nullable=False)
    note = Column(String(500), nullable=True)
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=utc_now)
