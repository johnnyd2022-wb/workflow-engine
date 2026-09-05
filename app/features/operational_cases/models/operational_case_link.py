"""OperationalCaseLink — polymorphic links from a case to its source and evidence.

The original ``source`` link is written once at creation and is immutable; ``evidence``
links are append-only (see .agents/specs/operational_cases.md data model section).
"""

import uuid

import sqlalchemy as sa
from sqlalchemy import Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID

from app.core.db.models.models import Base
from app.core.db.models.tenant_mixin import TenantScoped
from app.core.utils.time import utc_now


class CaseLinkRelation:
    SOURCE = "source"
    EVIDENCE = "evidence"

    ALL = (SOURCE, EVIDENCE)


class OperationalCaseLink(TenantScoped, Base):
    __tablename__ = "operational_case_links"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["org_id", "case_id"],
            ["operational_cases.org_id", "operational_cases.id"],
            name="fk_ocl_case_org",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["org_id", "created_by"], ["users.org_id", "users.id"], name="fk_ocl_actor_org"),
        sa.CheckConstraint(f"relation IN {CaseLinkRelation.ALL}", name="ck_operational_case_links_relation"),
        sa.Index("ix_operational_case_links_case", "org_id", "case_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id = Column(UUID(as_uuid=True), ForeignKey("operational_cases.id", ondelete="CASCADE"), nullable=False)
    relation = Column(String(20), nullable=False)
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(UUID(as_uuid=True), nullable=False)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    def __repr__(self) -> str:
        return f"<OperationalCaseLink(case_id={self.case_id}, relation={self.relation})>"
