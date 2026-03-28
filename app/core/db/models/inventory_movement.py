"""Append-only inventory movement ledger (event-sourced direction; on-hand = SUM(quantity))."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.core.db.models.models import Base


class InventoryMovementType(str, enum.Enum):
    """Movement kinds; quantity is signed in inventory item canonical unit."""

    WASTAGE = "WASTAGE"
    ADD = "ADD"
    ADJUSTMENT = "ADJUSTMENT"
    PRODUCTION = "PRODUCTION"


class InventoryMovement(Base):
    """Signed quantity change in canonical inventory unit; metadata holds cross-links (e.g. wastage id)."""

    __tablename__ = "inventory_movements"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False, index=True)
    inventory_item_id = Column(UUID(as_uuid=True), ForeignKey("inventory_items.id"), nullable=False, index=True)
    movement_type = Column("type", String(32), nullable=False, index=True)
    quantity = Column(Numeric(18, 4), nullable=False)
    unit = Column(String(50), nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False, index=True)
    # DB column name "metadata"; avoid Python name `metadata` (conflicts with declarative MetaData).
    movement_metadata = Column("metadata", JSONB, nullable=True)

    organisation = relationship("Organisation", backref="inventory_movements")
    inventory_item = relationship("InventoryItem", backref="inventory_movements")

    def __repr__(self) -> str:
        return f"<InventoryMovement(id={self.id}, type={self.movement_type}, qty={self.quantity} {self.unit}, item={self.inventory_item_id})>"
