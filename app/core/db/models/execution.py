"""Execution model for runtime process instances"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Enum, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.db.models.models import Base


class ExecutionStatus(enum.Enum):
    """Execution status enum"""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Execution(Base):
    """Execution model representing a runtime instance of a process"""

    __tablename__ = "executions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False, index=True)
    process_id = Column(UUID(as_uuid=True), ForeignKey("processes.id"), nullable=False, index=True)
    status = Column(Enum(ExecutionStatus, name="execution_status"), default=ExecutionStatus.PENDING, nullable=False)
    started_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    organisation = relationship("Organisation", backref="executions")
    process = relationship("Process", back_populates="executions")
    execution_steps = relationship("ExecutionStep", back_populates="execution", order_by="ExecutionStep.step_number", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Execution(id={self.id}, process_id={self.process_id}, status={self.status.value})>"

