"""Process (Flow) model for workflow definitions"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.db.models.models import Base


class ProcessCategory(enum.Enum):
    """Process category enum"""

    MANUFACTURING = "manufacturing"
    CHEMICAL = "chemical"
    PACKAGING = "packaging"
    ASSEMBLY = "assembly"
    OTHER = "other"


class Process(Base):
    """Process model representing a reusable workflow definition (DAG)"""

    __tablename__ = "processes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(String(1000), nullable=True)
    category = Column(Enum(ProcessCategory, name="process_category"), nullable=True)
    is_draft = Column(Boolean, nullable=False, default=False, index=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    organisation = relationship("Organisation", backref="processes")
    steps = relationship(
        "Step",
        back_populates="process",
        order_by="Step.position,Step.step_number",
        cascade="all, delete-orphan",
    )
    executions = relationship("Execution", back_populates="process", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Process(id={self.id}, name={self.name}, org_id={self.org_id})>"
