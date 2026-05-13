"""EntityEvent model — append-only event log row"""

import uuid
from datetime import datetime

from sqlalchemy import Column, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.core.db.models.models import Base


class EntityEvent(Base):
    """Single row in the entity_events append-only log.

    Never deleted. Tombstone events (e.g. inventory_item.deleted) record deletions.
    payload stores the complete entity state AFTER this event — reconstructing state
    at time T is a single indexed lookup, not a replay chain.
    """

    __tablename__ = "entity_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False, index=True)

    event_type = Column(String(100), nullable=False)
    entity_type = Column(String(100), nullable=False)
    entity_id = Column(UUID(as_uuid=True), nullable=False)

    actor_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    actor_type = Column(String(50), nullable=False, default="user")
    actor_label = Column(String(255), nullable=True)

    payload = Column(JSONB(), nullable=False)
    diff = Column(JSONB(), nullable=True)

    causation_id = Column(UUID(as_uuid=True), ForeignKey("entity_events.id", ondelete="SET NULL"), nullable=True)
    correlation_id = Column(UUID(as_uuid=True), nullable=True)
    request_metadata = Column(JSONB(), nullable=True)

    created_at = Column(
        "created_at",
        __import__("sqlalchemy").TIMESTAMP(timezone=True),
        default=datetime.utcnow,
        nullable=False,
    )

    organisation = relationship("Organisation", backref="entity_events")

    def __repr__(self) -> str:
        return f"<EntityEvent(id={self.id}, type={self.event_type}, entity={self.entity_type}/{self.entity_id})>"
