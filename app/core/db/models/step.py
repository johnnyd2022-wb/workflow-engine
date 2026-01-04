"""Step (Sub-process) model for process steps"""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.core.db.models.models import Base


class Step(Base):
    """Step model representing a sub-process within a process"""

    __tablename__ = "steps"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    process_id = Column(UUID(as_uuid=True), ForeignKey("processes.id"), nullable=False, index=True)
    step_number = Column(Integer, nullable=False)  # User-defined order
    name = Column(String(255), nullable=False)
    description = Column(String(1000), nullable=True)
    # Inputs and outputs stored as JSONB array
    # Format: [{"name": "Aluminum Sheets", "quantity": 100, "unit": "kg", "is_variable": true}, ...]
    inputs = Column(JSONB, nullable=False, default=list)
    outputs = Column(JSONB, nullable=False, default=list)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    process = relationship("Process", back_populates="steps")
    execution_steps = relationship("ExecutionStep", back_populates="step", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Step(id={self.id}, name={self.name}, step_number={self.step_number}, process_id={self.process_id})>"

