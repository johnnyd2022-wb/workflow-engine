"""OperationalCase — a durable owner/due-date/next-action record for an operational
exception, coordinating the response to a finding across its whole lifecycle.

See .agents/specs/operational_cases.md for the full A1 contract (lifecycle table,
source-identity rules, snapshot schema v1).
"""

import uuid

import sqlalchemy as sa
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.core.db.models.models import Base
from app.core.db.models.tenant_mixin import TenantScoped
from app.core.utils.time import utc_now


class CaseStatus:
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    VERIFIED = "verified"
    DISMISSED = "dismissed"

    ALL = (OPEN, ACKNOWLEDGED, IN_PROGRESS, RESOLVED, VERIFIED, DISMISSED)
    # "Active" for dedupe/attention purposes per spec: open/acknowledged/in_progress AND
    # resolved (awaiting verification). Only verified/dismissed are terminal.
    ACTIVE = (OPEN, ACKNOWLEDGED, IN_PROGRESS, RESOLVED)
    TERMINAL = (VERIFIED, DISMISSED)


class CaseSeverity:
    CRITICAL = "critical"
    ALL = (CRITICAL,)


class CaseCauseCategory:
    DATA_ENTRY = "data_entry"
    PROCESS_DEVIATION = "process_deviation"
    EQUIPMENT = "equipment"
    MATERIAL = "material"
    UNKNOWN = "unknown"
    OTHER = "other"

    ALL = (DATA_ENTRY, PROCESS_DEVIATION, EQUIPMENT, MATERIAL, UNKNOWN, OTHER)


class OperationalCase(TenantScoped, Base):
    """One row per operational case. ``version`` is bumped exactly once per accepted
    command (see OperationalCaseEvent's ``(org_id, case_id, case_version)`` uniqueness).
    """

    __tablename__ = "operational_cases"
    __table_args__ = (
        sa.UniqueConstraint("org_id", "id", name="uq_operational_cases_org_id_id"),
        sa.ForeignKeyConstraint(
            ["org_id", "previous_case_id"],
            ["operational_cases.org_id", "operational_cases.id"],
            name="fk_oc_predecessor_org",
        ),
        sa.ForeignKeyConstraint(["org_id", "owner_id"], ["users.org_id", "users.id"], name="fk_oc_owner_org"),
        sa.ForeignKeyConstraint(["org_id", "created_by"], ["users.org_id", "users.id"], name="fk_oc_creator_org"),
        sa.CheckConstraint(f"status IN {CaseStatus.ALL}", name="ck_operational_cases_status"),
        sa.CheckConstraint(f"severity IN {CaseSeverity.ALL}", name="ck_operational_cases_severity"),
        sa.Index("ix_operational_cases_org_status_due", "org_id", "status", "due_at"),
        sa.Index(
            "ix_operational_cases_org_severity_updated",
            "org_id",
            "severity",
            sa.text("updated_at DESC"),
            sa.text("id DESC"),
        ),
        # The last guard against a concurrent duplicate case for the same source: at most
        # one row with an "active" status (see CaseStatus.ACTIVE) per source identity.
        sa.Index(
            "uq_operational_cases_active_source",
            "org_id",
            "source_type",
            "check_id",
            "source_entity_type",
            "source_entity_id",
            unique=True,
            postgresql_where=sa.column("status").in_(CaseStatus.ACTIVE),
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(200), nullable=False)
    severity = Column(String(20), nullable=False, default=CaseSeverity.CRITICAL)

    # Source identity (A1: source_type='core_finding', check_id='untracked_items',
    # source_entity_type='inventory_item'). Never notification array position/name/date.
    source_type = Column(String(50), nullable=False)
    check_id = Column(String(100), nullable=False)
    source_entity_type = Column(String(50), nullable=False)
    source_entity_id = Column(UUID(as_uuid=True), nullable=False)

    # Immutable, allowlisted business-evidence snapshot (schema v1, <=16 KiB). Not
    # editable after creation -- see .agents/specs/operational_cases.md data model section.
    source_snapshot = Column(JSONB, nullable=False)

    status = Column(String(20), nullable=False, default=CaseStatus.OPEN)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    due_at = Column(DateTime(timezone=True), nullable=False)
    next_action = Column(String(2000), nullable=False)

    # Optimistic concurrency: bumped by exactly one per accepted command.
    version = Column(Integer, nullable=False, default=1)

    # Sole canonical predecessor relation (recurrence). Not duplicated in
    # operational_case_links.
    previous_case_id = Column(UUID(as_uuid=True), ForeignKey("operational_cases.id"), nullable=True)

    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    owner = relationship("User", foreign_keys=[owner_id])
    creator = relationship("User", foreign_keys=[created_by])
    previous_case = relationship("OperationalCase", remote_side=[id], foreign_keys=[previous_case_id], viewonly=True)

    def __repr__(self) -> str:
        return f"<OperationalCase(id={self.id}, org_id={self.org_id}, status={self.status})>"
