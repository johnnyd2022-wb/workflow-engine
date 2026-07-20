"""Step (Sub-process) model for process steps"""

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.core.db.models.models import Base
from app.core.utils.time import utc_now


class Step(Base):
    """Step model representing a sub-process within a process"""

    __tablename__ = "steps"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    process_id = Column(UUID(as_uuid=True), ForeignKey("processes.id"), nullable=False, index=True)
    step_number = Column(Integer, nullable=False)  # User-defined order
    # Flexible ordering key (Option B): allows drag/drop without bulk renumbering.
    # Stored as NUMERIC for stable sorting; UI can set fractional positions for "insert between".
    position = Column(Numeric(50, 20), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(String(1000), nullable=True)
    # Inputs and outputs stored as JSONB array (not separate tables — inventory eager-load avoids N+1 via Step row).
    # Format: [{"name": "Aluminum Sheets", "quantity": 100, "unit": "kg", "requires_inventory_selection": true}, ...]
    inputs = Column(JSONB, nullable=False, default=list)
    outputs = Column(JSONB, nullable=False, default=list)
    # Execution prompts stored as JSONB array
    # Format: [{"label": "Botanical batch number", "type": "text", "unit": null, "required": true}, ...]
    execution_prompts = Column(JSONB, nullable=False, default=list)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    # Relationships
    process = relationship("Process", back_populates="steps")
    execution_steps = relationship("ExecutionStep", back_populates="step", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Step(id={self.id}, name={self.name}, step_number={self.step_number}, process_id={self.process_id})>"
