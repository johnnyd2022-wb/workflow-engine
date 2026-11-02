"""Planning commits materials to batches (GL-P07 B2).

`planning_material_commitments`: a soft hold of a quantity of one lot for one planned batch, made
when materials are checked. `active` until the batch starts (`consumed`), is cancelled or is
re-checked (`released`). Other planned batches see the lot as committed; using it elsewhere
warns but isn't blocked.

Downgrade refuses while any commitment exists.

Revision ID: planning_commitments_001
Revises: step_timing_001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import UUID

revision = "planning_commitments_001"
down_revision = "step_timing_001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "planning_material_commitments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("batch_id", UUID(as_uuid=True), nullable=False),
        sa.Column("inventory_item_id", UUID(as_uuid=True), nullable=False),
        sa.Column("assessment_id", UUID(as_uuid=True), nullable=False),
        sa.Column("material", sa.String(255), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("unit", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["org_id", "batch_id"],
            ["planning_batches.org_id", "planning_batches.id"],
            name="fk_planning_commitment_org_batch",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "inventory_item_id"],
            ["inventory_items.org_id", "inventory_items.id"],
            name="fk_planning_commitment_org_item",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "assessment_id"],
            ["planning_material_assessments.org_id", "planning_material_assessments.id"],
            name="fk_planning_commitment_org_assessment",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("quantity > 0", name="ck_planning_commitment_quantity"),
        sa.CheckConstraint("status IN ('active','released','consumed')", name="ck_planning_commitment_status"),
        sa.CheckConstraint("(status = 'active') = (closed_at IS NULL)", name="ck_planning_commitment_closed"),
    )
    # What's held on a lot, and what a batch holds, are the two questions asked of it.
    op.create_index(
        "ix_planning_commitment_active_item",
        "planning_material_commitments",
        ["org_id", "inventory_item_id"],
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index("ix_planning_commitment_batch", "planning_material_commitments", ["org_id", "batch_id"])


def downgrade():
    if op.get_bind().execute(text("SELECT 1 FROM planning_material_commitments LIMIT 1")).first():
        raise RuntimeError("Planned batches have material commitments; downgrading would lose them")
    op.drop_table("planning_material_commitments")
