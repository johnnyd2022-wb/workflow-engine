"""ProcessVersion model — immutable snapshot of a process and its steps"""

import uuid
from datetime import datetime

from sqlalchemy import Column, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.core.db.models.models import Base


class ProcessVersion(Base):
    """Immutable snapshot of a process and all its steps at a point in time.

    Created on every mutation to processes or steps. Answers the question:
    "What procedure was being followed when Execution #N ran?"

    version_number is auto-incremented per-process (not global).
    snapshot JSONB contains the full process + steps definition:
    {"id": ..., "name": ..., "steps": [{"id": ..., "step_number": ..., ...}]}
    """

    __tablename__ = "process_versions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False, index=True)
    process_id = Column(UUID(as_uuid=True), ForeignKey("processes.id", ondelete="CASCADE"), nullable=False)
    version_number = Column(Integer(), nullable=False)
    snapshot = Column(JSONB(), nullable=False)
    changed_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    change_summary = Column(String(500), nullable=True)
    created_at = Column(
        __import__("sqlalchemy").TIMESTAMP(timezone=True),
        default=datetime.utcnow,
        nullable=False,
    )

    __table_args__ = (UniqueConstraint("process_id", "version_number", name="uq_process_versions_process_version"),)

    process = relationship("Process", backref="versions")

    def __repr__(self) -> str:
        return f"<ProcessVersion(id={self.id}, process_id={self.process_id}, v{self.version_number})>"
