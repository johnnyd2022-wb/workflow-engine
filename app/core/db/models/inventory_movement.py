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
    """Signed quantity change in the item's canonical storage unit (same as inventory_items.unit).

    Hybrid model: inventory_items.quantity is the hot path (cached on-hand); this table is append-only
    audit/replay. Quantities MUST be in that canonical unit only (convert before insert). WASTAGE rows
    from record_wastage are deduped by source_wastage_id -> inventory_wastage.id (unique when set).
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
