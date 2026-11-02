"""Where planned demand comes from, and how much stock to keep (GL-P07 B3).

- `planning_demands.source`: 'manual' (typed in, as before), 'contract' (a confirmed contract
  order line) or 'forecast' (an accepted suggestion from sales history). `source_ref` names the
  contract line, so each line is demand once.
- `planning_stock_targets`: weeks of cover to keep for a product (a workflow output). The
  forecast turns it into suggested demand.

Downgrade refuses while any demand came from a contract or forecast, or any target is set.

Revision ID: planning_demand_sources_001
Revises: supplier_lead_time_001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import UUID

revision = "planning_demand_sources_001"
down_revision = "supplier_lead_time_001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("planning_demands", sa.Column("source", sa.String(20), nullable=False, server_default="manual"))
    op.add_column("planning_demands", sa.Column("source_ref", sa.String(100), nullable=True))
    op.create_check_constraint(
        "ck_planning_demand_source", "planning_demands", "source IN ('manual','contract','forecast')"
    )
    op.create_index(
        "uq_planning_demand_source_ref",
        "planning_demands",
        ["org_id", "source", "source_ref"],
        unique=True,
        postgresql_where=sa.text("source_ref IS NOT NULL"),
    )
    op.create_table(
        "planning_stock_targets",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_output_id", UUID(as_uuid=True), nullable=False),
        sa.Column("weeks_of_cover", sa.Numeric(6, 2), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("org_id", "source_output_id", name="uq_planning_stock_target_output"),
        sa.CheckConstraint("weeks_of_cover > 0 AND weeks_of_cover <= 104", name="ck_planning_stock_target_weeks"),
    )


def downgrade():
    bind = op.get_bind()
    used = bind.execute(
        text(
            "SELECT 1 FROM planning_demands WHERE source <> 'manual' "
            "UNION ALL SELECT 1 FROM planning_stock_targets LIMIT 1"
        )
    ).first()
    if used:
        raise RuntimeError("Demand from contracts or forecasts, or stock targets, exist; downgrading would lose them")
    op.drop_table("planning_stock_targets")
    op.drop_index("uq_planning_demand_source_ref", table_name="planning_demands")
    op.drop_constraint("ck_planning_demand_source", "planning_demands", type_="check")
    op.drop_column("planning_demands", "source_ref")
    op.drop_column("planning_demands", "source")
