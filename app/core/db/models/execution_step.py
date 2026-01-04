"""ExecutionStep model for tracking step execution state"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.core.db.models.models import Base


class ExecutionStepStatus(enum.Enum):
    """Execution step status enum"""

    PENDING = "pending"
    READY = "ready"  # Ready to execute (dependencies met)
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ExecutionStep(Base):
    """ExecutionStep model tracking the execution state of each step in an execution"""

    __tablename__ = "execution_steps"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    execution_id = Column(UUID(as_uuid=True), ForeignKey("executions.id"), nullable=False, index=True)
    step_id = Column(UUID(as_uuid=True), ForeignKey("steps.id"), nullable=False, index=True)
    step_number = Column(Integer, nullable=False)  # Denormalized for easier querying
    status = Column(Enum(ExecutionStepStatus, name="execution_step_status"), default=ExecutionStepStatus.PENDING, nullable=False)
    is_terminal_step = Column(Boolean, default=False, nullable=False)  # Deterministic terminal step detection
    # Actual input values used (immutable after completion)
    actual_inputs = Column(JSONB, nullable=True)  # Format: [{"name": "Aluminum Sheets", "quantity": 100, "unit": "kg", "inventory_item_id": "uuid"}, ...]
    # Actual outputs produced (immutable after completion)
    actual_outputs = Column(JSONB, nullable=True)  # Format: [{"name": "Verified Materials", "quantity": 145, "unit": "kg"}, ...]
    # Execution metadata (errors, notes, etc.)
    execution_data = Column(JSONB, nullable=True)  # For storing step execution details immutably
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    execution = relationship("Execution", back_populates="execution_steps")
    step = relationship("Step", back_populates="execution_steps")

    def __repr__(self):
        return f"<ExecutionStep(id={self.id}, execution_id={self.execution_id}, step_id={self.step_id}, status={self.status.value})>"

