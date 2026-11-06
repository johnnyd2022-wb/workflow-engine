"""Where planning demand comes from, and stock targets (GL-P07 B3).

Additive only:
- `planning_demands.source`: 'manual' (existing rows), 'contract' (a confirmed contract order
  line) or 'forecast' (a stock-target suggestion someone chose to plan).
- `planning_demands.source_ref`: the contract order line a demand mirrors, or the retry key of a
  forecast "Plan it". At most one demand per ref in an org (partial unique index).
- `planning_demands.source_note`: why a synced demand was left as it is (e.g. its batch started).
- `planning_stock_targets`: weeks of cover to keep of an output, optionally per site.

Downgrade refuses while any synced/forecast demand or stock target exists, so it never loses data.

Revision ID: planning_demand_sources_001
Revises: xero_credit_notes_001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

revision = "planning_demand_sources_001"
down_revision = "xero_credit_notes_001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "planning_demands",
        sa.Column("source", sa.String(20), nullable=False, server_default="manual"),
    )
    op.add_column("planning_demands", sa.Column("source_ref", sa.String(160), nullable=True))
    op.add_column("planning_demands", sa.Column("source_note", sa.String(300), nullable=True))
    op.create_check_constraint(
        "ck_planning_demand_source", "planning_demands", "source IN ('manual', 'contract', 'forecast')"
    )
    op.create_check_constraint(
        "ck_planning_demand_source_ref",
        "planning_demands",
        "(source = 'manual' AND source_ref IS NULL) OR (source <> 'manual' AND source_ref IS NOT NULL)",
    )
    op.create_index(
        "uq_planning_demand_source_ref",
        "planning_demands",
        ["org_id", "source_ref"],
        unique=True,
        postgresql_where=sa.text("source_ref IS NOT NULL"),
    )
    op.create_table(
        "planning_stock_targets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("source_output_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("site_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("weeks_of_cover", sa.Numeric(6, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("weeks_of_cover > 0 AND weeks_of_cover <= 104", name="ck_planning_stock_target_weeks"),
        sa.ForeignKeyConstraint(
            ["org_id", "site_id"], ["sites.org_id", "sites.id"], name="fk_planning_stock_target_org_site"
        ),
    )
    op.create_index("ix_planning_stock_targets_org_id", "planning_stock_targets", ["org_id"])
    # One target per output per site; NULL site (single-site business) is one more value.
    op.create_index(
        "uq_planning_stock_target_output_site",
        "planning_stock_targets",
        ["org_id", "source_output_id", sa.text("coalesce(site_id, '00000000-0000-0000-0000-000000000000'::uuid)")],
        unique=True,
    )


def downgrade():
    bind = op.get_bind()
    if bind.execute(text("SELECT 1 FROM planning_stock_targets LIMIT 1")).first():
        raise RuntimeError("Stock targets are recorded; downgrading would lose them")
    if bind.execute(text("SELECT 1 FROM planning_demands WHERE source <> 'manual' LIMIT 1")).first():
        raise RuntimeError("Contract or forecast demand is recorded; downgrading would lose where it came from")
    op.drop_index("uq_planning_stock_target_output_site", table_name="planning_stock_targets")
    op.drop_index("ix_planning_stock_targets_org_id", table_name="planning_stock_targets")
    op.drop_table("planning_stock_targets")
    op.drop_index("uq_planning_demand_source_ref", table_name="planning_demands")
    op.drop_constraint("ck_planning_demand_source_ref", "planning_demands", type_="check")
    op.drop_constraint("ck_planning_demand_source", "planning_demands", type_="check")
    op.drop_column("planning_demands", "source_note")
    op.drop_column("planning_demands", "source_ref")
    op.drop_column("planning_demands", "source")
