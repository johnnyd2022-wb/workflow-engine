"""Historical material observations, separate from delivery promises and reservations."""

import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
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


class PlanningMaterialCommitment(TenantScoped, Base):
    """A soft hold of part of one lot for one planned batch (GL-P07 B2). Active until the batch
    starts (consumed), is cancelled, or its materials are checked again (released)."""

    __tablename__ = "planning_material_commitments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "batch_id"],
            ["planning_batches.org_id", "planning_batches.id"],
            name="fk_planning_commitment_org_batch",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["org_id", "inventory_item_id"],
            ["inventory_items.org_id", "inventory_items.id"],
            name="fk_planning_commitment_org_item",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["org_id", "assessment_id"],
            ["planning_material_assessments.org_id", "planning_material_assessments.id"],
            name="fk_planning_commitment_org_assessment",
            ondelete="CASCADE",
        ),
        CheckConstraint("quantity > 0", name="ck_planning_commitment_quantity"),
        CheckConstraint("status IN ('active','released','consumed')", name="ck_planning_commitment_status"),
        CheckConstraint("(status = 'active') = (closed_at IS NULL)", name="ck_planning_commitment_closed"),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    batch_id = Column(UUID(as_uuid=True), nullable=False)
    inventory_item_id = Column(UUID(as_uuid=True), nullable=False)
    assessment_id = Column(UUID(as_uuid=True), nullable=False)
    material = Column(String(255), nullable=False)
    quantity = Column(Numeric(18, 4), nullable=False)
    unit = Column(String(50), nullable=False)
    status = Column(String(20), nullable=False, default="active", server_default="active")
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    closed_at = Column(DateTime(timezone=True), nullable=True)
