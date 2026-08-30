"""EntityEvent model — append-only event log row"""

import uuid

from sqlalchemy import BigInteger, Column, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.core.db.models.models import Base
from app.core.db.models.tenant_mixin import TenantScoped
from app.core.utils.time import utc_now


class EntityEvent(TenantScoped, Base):
    """Single row in the entity_events append-only log.

    Never deleted. Tombstone events (e.g. inventory_item.deleted) record deletions.
    payload stores the complete entity state AFTER this event — reconstructing state
    at time T is a single indexed lookup, not a replay chain.
    """

    __tablename__ = "entity_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Commit-ordered cursor for the /api/core/changes feed. The UUID PK is not ordered and
    # created_at is not unique, so neither gives a total order. EventWriter.emit() MUST set
    # this: COALESCE(MAX(seq),0)+1 for the org, allocated under a per-org advisory lock held
    # to commit (event_writer._next_feed_seq), so seq order == commit order per org with no
    # gaps.
    #
    # There is NO database default (migration entity_events_seq_noident_001 dropped the
    # old IDENTITY): a write that bypasses EventWriter fails on NOT NULL instead of silently
    # taking a stale value, and (org_id, seq) is UNIQUE (ix_entity_events_org_seq) so a
    # double-allocation cannot corrupt the feed order.
    seq = Column(BigInteger, nullable=False)

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
        default=utc_now,
        nullable=False,
    )

    organisation = relationship("Organisation", backref="entity_events")

    def __repr__(self) -> str:
        return f"<EntityEvent(id={self.id}, type={self.event_type}, entity={self.entity_type}/{self.entity_id})>"
