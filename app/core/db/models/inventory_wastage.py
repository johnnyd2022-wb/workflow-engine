"""InventoryWastage model for recording disposed/wasted inventory"""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.db.models.models import Base


class InventoryWastage(Base):
    """Record of inventory quantity written off as wastage. Deducts from inventory_items.quantity.

    inventory_movements records WASTAGE lines with signed quantities; this table keeps wastage-specific
    fields and human-readable audit alongside that ledger.
    """

    __tablename__ = "inventory_wastage"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False, index=True)
    inventory_item_id = Column(UUID(as_uuid=True), ForeignKey("inventory_items.id"), nullable=False, index=True)
    quantity_wasted = Column(String(50), nullable=False)  # Same precision as inventory quantity
    unit = Column(String(50), nullable=False)  # Denormalized from item at time of record
    recorded_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    recorded_by = Column(String(255), nullable=True)  # User identifier for audit
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    organisation = relationship("Organisation", backref="inventory_wastage_records")
    inventory_item = relationship("InventoryItem", backref="wastage_records")

    def __repr__(self):
        return f"<InventoryWastage(id={self.id}, item_id={self.inventory_item_id}, qty={self.quantity_wasted} {self.unit})>"
