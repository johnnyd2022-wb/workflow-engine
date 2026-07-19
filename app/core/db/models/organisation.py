"""Organisation model for multi-tenant support"""

import enum
import uuid

from sqlalchemy import Column, DateTime, Enum, String
from sqlalchemy.dialects.postgresql import UUID

from app.core.db.models.models import Base
from app.core.utils.time import utc_now


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
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    def __repr__(self):
        return f"<Organisation(id={self.id}, name={self.name}, status={self.status.value})>"
