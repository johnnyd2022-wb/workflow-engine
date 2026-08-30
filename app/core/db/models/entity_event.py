"""EntityEvent model — append-only event log row"""

import uuid

from sqlalchemy import BigInteger, Column, ForeignKey, Identity, String
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
    # created_at is not unique, so neither gives a total order. EventWriter.emit() sets this
    # explicitly per-org: COALESCE(MAX(seq),0)+1 under a per-org advisory lock held to
    # commit (event_writer._next_feed_seq), so seq order == commit order per org with no
    # gaps.
    #
    # The IDENTITY default is retained only as a transitional fallback so a worker still
    # running the previous release keeps inserting during a rolling deploy. It is NOT a
    # real backstop: its internal sequence stops advancing once emit() supplies seq
    # explicitly, so a later bypass insert could take a stale value. Once this release has
    # fully rolled out, a follow-up migration should DROP the IDENTITY (a bypass insert
    # then fails loudly on NOT NULL) and add UNIQUE (org_id, seq). Tracked in the MR !201
    # follow-up notes.
    seq = Column(BigInteger, Identity(always=False), nullable=False)

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
