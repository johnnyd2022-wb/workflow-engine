"""Append-only inventory movement rows (audit/replay), not a standalone event-sourced projection."""

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
    """Signed quantity in the item's canonical storage unit (inventory_items.unit).

    This is an event log alongside mutable inventory_items.quantity—not sole source of truth until/unless
    you migrate to derived on-hand. Inserts must use canonical unit; record_wastage stores conversion
    provenance in movement_metadata when the client sent quantity_unit. WASTAGE rows from record_wastage
    use source_wastage_id -> inventory_wastage.id (unique when set) for deduplication.
    """

    __tablename__ = "inventory_movements"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False, index=True)
    inventory_item_id = Column(UUID(as_uuid=True), ForeignKey("inventory_items.id"), nullable=False, index=True)
    source_wastage_id = Column(
        UUID(as_uuid=True),
        ForeignKey("inventory_wastage.id", ondelete="RESTRICT"),
        nullable=True,
        unique=True,
    )
    movement_type = Column("type", String(32), nullable=False, index=True)
    quantity = Column(Numeric(18, 4), nullable=False)
    unit = Column(String(50), nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False, index=True)
    # DB column name "metadata"; avoid Python name `metadata` (conflicts with declarative MetaData).
    movement_metadata = Column("metadata", JSONB, nullable=True)

    organisation = relationship("Organisation", backref="inventory_movements")
    inventory_item = relationship("InventoryItem", backref="inventory_movements")
    source_wastage = relationship("InventoryWastage", foreign_keys=[source_wastage_id], backref="ledger_movement")

    def __repr__(self) -> str:
        return f"<InventoryMovement(id={self.id}, type={self.movement_type}, qty={self.quantity} {self.unit}, item={self.inventory_item_id})>"
