"""What the planner changed by itself, and why (GL-P07 B4).

`planning_replan_events`: one row each time an automatic replan moves, adds or cancels a planned
batch, with the dates and a plain-words reason, so the board can say what moved. Additive; the
rows go with their batch. Downgrade refuses while any are recorded.

Revision ID: planning_replan_001
Revises: planning_demand_sources_001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

revision = "planning_replan_001"
down_revision = "planning_demand_sources_001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "planning_replan_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("demand_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("from_date", sa.Date(), nullable=True),
        sa.Column("to_date", sa.Date(), nullable=True),
        sa.Column("reason", sa.String(300), nullable=False),
        sa.Column("trigger", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("kind IN ('moved', 'added', 'cancelled')", name="ck_planning_replan_event_kind"),
        sa.ForeignKeyConstraint(
            ["org_id", "batch_id"],
            ["planning_batches.org_id", "planning_batches.id"],
            name="fk_planning_replan_event_batch",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_planning_replan_events_org_created", "planning_replan_events", ["org_id", "created_at"])


def downgrade():
    if op.get_bind().execute(text("SELECT 1 FROM planning_replan_events LIMIT 1")).first():
        raise RuntimeError("Replan history is recorded; downgrading would lose it")
    op.drop_index("ix_planning_replan_events_org_created", table_name="planning_replan_events")
    op.drop_table("planning_replan_events")
