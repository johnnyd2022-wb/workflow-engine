"""Persist observational material assessments without changing stock or forecasts."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "planner_material_forecasts_001"
down_revision = "planned_batches_001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "planning_material_assessments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("observations", JSONB(), nullable=False),
        sa.UniqueConstraint("org_id", "id", name="uq_planning_material_assessment_org_id"),
        sa.UniqueConstraint("org_id", "sequence", name="uq_planning_material_assessment_sequence"),
        sa.CheckConstraint("sequence > 0", name="ck_planning_material_assessment_sequence"),
    )
    op.create_table(
        "planning_material_batch_assessments",
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("assessment_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("batch_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("batch_revision", sa.Integer(), nullable=False),
        sa.Column("result", JSONB(), nullable=False),
        sa.ForeignKeyConstraint(["org_id", "assessment_id"], ["planning_material_assessments.org_id", "planning_material_assessments.id"], name="fk_planning_material_assessment_org"),
        sa.ForeignKeyConstraint(["org_id", "batch_id"], ["planning_batches.org_id", "planning_batches.id"], name="fk_planning_material_assessment_batch_org"),
        sa.CheckConstraint("batch_revision > 0", name="ck_planning_material_batch_revision"),
    )
    op.create_index("ix_planning_material_assessments_org", "planning_material_assessments", ["org_id"])
    op.create_index("ix_planning_material_batch_assessments_org_batch", "planning_material_batch_assessments", ["org_id", "batch_id"])


def downgrade():
    op.drop_table("planning_material_batch_assessments")
    op.drop_table("planning_material_assessments")
