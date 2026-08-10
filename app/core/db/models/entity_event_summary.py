"""EntityEventSummary model — pre-computed per-entity read model for list views"""

from sqlalchemy import Column, String
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.db.models.models import Base
from app.core.db.models.tenant_mixin import TenantScoped
from app.core.utils.time import utc_now


class EntityEventSummary(TenantScoped, Base):
    """Pre-computed summary for a single entity, upserted atomically on every event write.

    Powers list-view card enrichment (inventory list, process list, executions list)
    without N+1 queries against entity_events. The summary JSONB shape is
    entity-type-specific — see EventWriter._upsert_summary() for each shape.

    quantity_history in inventory_item summaries is capped at 50 entries to prevent
    unbounded JSONB growth; full history remains in entity_events.

    org_id previously had no FK constraint (declared as a bare column) -- TenantScoped adds
    one (organisations.id, ON DELETE CASCADE). The column and its values are unchanged; the
    migration only adds a constraint on already-valid data, see the accompanying Alembic
    revision.
    """

    __tablename__ = "entity_event_summaries"

    entity_id = Column(UUID(as_uuid=True), primary_key=True)
    entity_type = Column(String(100), nullable=False)
    summary = Column(JSONB(), nullable=False)
    last_event_at = Column(
        __import__("sqlalchemy").TIMESTAMP(timezone=True),
        nullable=False,
    )
    last_event_type = Column(String(100), nullable=False)
    last_actor = Column(String(255), nullable=True)
    updated_at = Column(
        __import__("sqlalchemy").TIMESTAMP(timezone=True),
        default=utc_now,
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<EntityEventSummary(entity_id={self.entity_id}, type={self.entity_type})>"
