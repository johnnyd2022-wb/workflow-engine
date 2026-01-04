"""InventoryItem model for inventory tracking"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Column, Date, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.core.db.models.models import Base


class InventoryType(enum.Enum):
    """Inventory type enum"""

    RAW_MATERIAL = "raw_material"
    WORK_IN_PROGRESS = "work_in_progress"
    FINAL_PRODUCT = "final_product"


class InventoryItem(Base):
    """InventoryItem model for tracking raw materials, WIP, and final products"""

    __tablename__ = "inventory_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    quantity = Column(String(50), nullable=False)  # Store as string to preserve precision and unit info
    unit = Column(String(50), nullable=False)  # kg, g, L, mL, units, pcs, etc.
    inventory_type = Column(String(50), nullable=False)  # raw_material, work_in_progress, final_product
    # Supplier information (for raw materials)
    supplier = Column(String(255), nullable=True)
    purchase_date = Column(Date, nullable=True)
    supplier_batch_number = Column(String(255), nullable=True)
    expiry_date = Column(Date, nullable=True)
    # Traceability: link to execution/step that produced this (for WIP and final products)
    source_execution_id = Column(UUID(as_uuid=True), ForeignKey("executions.id"), nullable=True, index=True)
    source_execution_step_id = Column(UUID(as_uuid=True), ForeignKey("execution_steps.id"), nullable=True, index=True)
    source_step_name = Column(String(255), nullable=True)  # Denormalized for easier querying
    # Additional metadata (renamed from 'metadata' to avoid SQLAlchemy reserved name)
    extra_data = Column(JSONB, nullable=True)  # For storing additional flexible data
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    organisation = relationship("Organisation", backref="inventory_items")
    source_execution = relationship("Execution", foreign_keys=[source_execution_id], backref="produced_inventory")
    source_execution_step = relationship(
        "ExecutionStep", foreign_keys=[source_execution_step_id], backref="produced_inventory"
    )

    def __repr__(self):
        return f"<InventoryItem(id={self.id}, name={self.name}, quantity={self.quantity} {self.unit}, type={self.inventory_type})>"
