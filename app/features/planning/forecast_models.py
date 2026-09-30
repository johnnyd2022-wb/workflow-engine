"""Historical material observations, separate from delivery promises and reservations."""

import uuid

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKeyConstraint, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.db.models.models import Base
from app.core.db.models.tenant_mixin import TenantScoped
from app.core.utils.time import utc_now


class PlanningMaterialAssessment(TenantScoped, Base):
    __tablename__ = "planning_material_assessments"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_planning_material_assessment_org_id"),
        UniqueConstraint("org_id", "sequence", name="uq_planning_material_assessment_sequence"),
        CheckConstraint("sequence > 0", name="ck_planning_material_assessment_sequence"),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sequence = Column(Integer, nullable=False)
    observed_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    observations = Column(JSONB, nullable=False)


class PlanningMaterialBatchAssessment(TenantScoped, Base):
    __tablename__ = "planning_material_batch_assessments"
    __table_args__ = (
        CheckConstraint("batch_revision > 0", name="ck_planning_material_batch_revision"),
        ForeignKeyConstraint(
            ["org_id", "assessment_id"],
            ["planning_material_assessments.org_id", "planning_material_assessments.id"],
            name="fk_planning_material_assessment_org",
        ),
        ForeignKeyConstraint(
            ["org_id", "batch_id"],
            ["planning_batches.org_id", "planning_batches.id"],
            name="fk_planning_material_assessment_batch_org",
        ),
    )
    assessment_id = Column(UUID(as_uuid=True), primary_key=True)
    batch_id = Column(UUID(as_uuid=True), primary_key=True)
    batch_revision = Column(Integer, nullable=False)
    result = Column(JSONB, nullable=False)
