"""Organisation model for multi-tenant support"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Enum, String
from sqlalchemy.dialects.postgresql import UUID

from app.core.db.models.models import Base


class OrganisationStatus(enum.Enum):
    """Organisation status enum"""

    ACTIVE = "active"
    SUSPENDED = "suspended"


class Organisation(Base):
    """Organisation model representing a tenant"""

    __tablename__ = "organisations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False, unique=True)
    status = Column(
        Enum(OrganisationStatus, name="organisation_status"), default=OrganisationStatus.ACTIVE, nullable=False
    )
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<Organisation(id={self.id}, name={self.name}, status={self.status.value})>"
