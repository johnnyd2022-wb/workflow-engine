"""Persist explicit production demand without reserving stock.

Revision ID: planner_demands_001
Revises: multiple_sites_001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "planner_demands_001"
down_revision = "multiple_sites_001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "planning_demands",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("reference", sa.String(200), nullable=False),
        sa.Column("source_output_id", UUID(as_uuid=True), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("unit", sa.String(50), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("quantity > 0 AND quantity <= 99999999999999.9999", name="ck_planning_demand_quantity"),
        sa.CheckConstraint("priority >= 0 AND priority <= 100", name="ck_planning_demand_priority"),
        sa.CheckConstraint("status IN ('open', 'cancelled', 'fulfilled')", name="ck_planning_demand_status"),
    )
    for name in ("org_id", "source_output_id", "due_date"):
        op.create_index(f"ix_planning_demands_{name}", "planning_demands", [name])


def downgrade():
    op.drop_table("planning_demands")
