"""OperationalCaseEvent — append-only timeline row, one per accepted case command.

``(org_id, case_id, case_version)`` is unique: exactly one event per version, which is
also the optimistic-concurrency guard's unit of work. ``entity_event_id`` ties this row to
the corresponding EventWriter-emitted ``entity_events`` row written in the same
transaction (see .agents/specs/operational_cases.md: "Case events reference the emitted
domain event; failure of either audit write rolls back the mutation.").
"""

import uuid

import sqlalchemy as sa
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.db.models.models import Base
from app.core.db.models.tenant_mixin import TenantScoped
from app.core.utils.time import utc_now


class OperationalCaseEvent(TenantScoped, Base):
    __tablename__ = "operational_case_events"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["org_id", "entity_event_id"], ["entity_events.org_id", "entity_events.id"], name="fk_oce_event_org"
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "case_id"],
            ["operational_cases.org_id", "operational_cases.id"],
            name="fk_oce_case_org",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["org_id", "actor_id"], ["users.org_id", "users.id"], name="fk_oce_actor_org"),
        sa.UniqueConstraint("org_id", "case_id", "case_version", name="uq_operational_case_events_case_version"),
        sa.Index(
            "ix_operational_case_events_case_version",
            "org_id",
            "case_id",
            sa.text("case_version DESC"),
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id = Column(UUID(as_uuid=True), ForeignKey("operational_cases.id", ondelete="CASCADE"), nullable=False)
    case_version = Column(Integer, nullable=False)
    event_type = Column(String(60), nullable=False)

    actor_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    # Recorded at event time so a later tombstoned/renamed user never rewrites history.
    actor_label = Column(String(255), nullable=True)

    occurred_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    payload = Column(JSONB, nullable=False)

    entity_event_id = Column(UUID(as_uuid=True), ForeignKey("entity_events.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    def __repr__(self) -> str:
        return f"<OperationalCaseEvent(case_id={self.case_id}, v={self.case_version}, type={self.event_type})>"
