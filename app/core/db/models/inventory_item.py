"""InventoryItem model for inventory tracking"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Column, Date, DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.core.db.models.models import Base


class InventoryType(enum.Enum):
    """Inventory type enum"""

    RAW_MATERIAL = "raw_material"
    WORK_IN_PROGRESS = "work_in_progress"
    FINAL_PRODUCT = "final_product"


class InventoryItem(Base):
    """InventoryItem model for tracking raw materials, WIP, and final products.

    DB enforces UNIQUE (org_id, barcode) where barcode IS NOT NULL (see migration uq_inventory_org_barcode_001).
    On-hand quantity is NUMERIC(18,4) at rest; API layers serialize to strings. This column is the
    authoritative on-hand cache (not derived-only from movements). Quantity mutations are gated by
    app.core.domain.inventory_quantity_guard (ORM before_flush); bulk SQL bypasses that—avoid it.
    Append-only inventory_movements supplement audit/replay; drift vs SUM(movements) is possible if
    quantity is edited outside authorized paths—see scripts/inventory_quantity_drift_check.sql.
    """

    __tablename__ = "inventory_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    quantity = Column(Numeric(18, 4), nullable=False, server_default="0")
    unit = Column(String(50), nullable=False)  # kg, g, L, mL, units, pcs, etc.
    inventory_type = Column(String(50), nullable=False)  # raw_material, work_in_progress, final_product
    # Supplier information (for raw materials)
    supplier = Column(String(255), nullable=True)
    barcode = Column(String(255), nullable=True, index=True)  # Product identity; reused across stock entries
    purchase_date = Column(Date, nullable=True)
    supplier_batch_number = Column(String(255), nullable=True)
    expiry_date = Column(Date, nullable=True)
    # Traceability: link to execution/step that produced this (for WIP and final products)
    source_execution_id = Column(UUID(as_uuid=True), ForeignKey("executions.id"), nullable=True, index=True)
    source_execution_step_id = Column(UUID(as_uuid=True), ForeignKey("execution_steps.id"), nullable=True, index=True)
    source_output_id = Column(UUID(as_uuid=True), nullable=True, index=True)  # steps.outputs[].id (JSONB, no FK)
    source_step_name = Column(String(255), nullable=True)  # Denormalized for easier querying
    # Additional metadata (renamed from 'metadata' to avoid SQLAlchemy reserved name)
    extra_data = Column(JSONB, nullable=True)  # For storing additional flexible data
    # Pre-computed human-readable label for sourcemap selectors. The column was added by
    # migration event_sourcing_process_versions_001 and the repository reads/writes it
    # (_item_snapshot, _build_display_label), but the model never declared it — so loading
    # an item and reading item.display_label raised AttributeError and 500'd quantity
    # adjust and any other path that snapshots an item. Declared here to match the DB.
    display_label = Column(String(255), nullable=True)
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
