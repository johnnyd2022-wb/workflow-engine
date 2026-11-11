"""Live cost engine facts (roadmap 8.1a, spec .agents/specs/live-cogs.md).

`cost_flows` (every quantity into or out of a lot), `lot_cost_entries` (typed or free prices)
and `costing_settings` (one row per org). Additive: nothing existing changes. Rows go with their
lot or execution (ON DELETE CASCADE). The flow history for existing lots is filled by
`uv run workflow costing backfill-flows`, not here. Downgrade drops only what this adds and
refuses while any costing row exists: typed prices and settings are user data, and flow history
can include reconciliations that the backfill deliberately cannot reconstruct. Repo convention,
as in planning_replan_001.

Revision ID: costing_engine_001
Revises: planning_replan_001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

revision = "costing_engine_001"
down_revision = "planning_replan_001"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade():
    # Lets a flow name a step of its own org *and* its own execution (composite FK below).
    # id is the primary key, so every existing row already satisfies it.
    op.create_unique_constraint(
        "uq_execution_steps_org_execution_id", "execution_steps", ["org_id", "execution_id", "id"]
    )
    op.create_table(
        "cost_flows",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("org_id", UUID, sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("inventory_item_id", UUID, nullable=False),
        sa.Column("direction", sa.String(3), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("execution_id", UUID, nullable=True),
        sa.Column("execution_step_id", UUID, nullable=True),
        sa.Column("step_number", sa.Integer(), nullable=True),
        sa.Column("source_output_id", UUID, nullable=True),
        sa.Column("source_key", sa.String(200), nullable=False),
        sa.Column("write_reason", sa.String(50), nullable=False),
        sa.Column("reconstructed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("org_id", "id", name="uq_cost_flows_org_id"),
        sa.UniqueConstraint("org_id", "source_key", name="uq_cost_flows_source_key"),
        sa.ForeignKeyConstraint(
            ["org_id", "inventory_item_id"],
            ["inventory_items.org_id", "inventory_items.id"],
            name="fk_cost_flows_item",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "execution_id"],
            ["executions.org_id", "executions.id"],
            name="fk_cost_flows_execution",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "execution_id", "execution_step_id"],
            ["execution_steps.org_id", "execution_steps.execution_id", "execution_steps.id"],
            name="fk_cost_flows_execution_step",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("quantity > 0", name="ck_cost_flows_quantity_positive"),
        sa.CheckConstraint(
            "execution_step_id IS NULL OR execution_id IS NOT NULL", name="ck_cost_flows_step_needs_execution"
        ),
        sa.CheckConstraint(
            "(direction = 'in' AND kind IN ('created','added','produced','transfer_in','reconciled_in'))"
            " OR (direction = 'out' AND kind = 'consumed')",
            name="ck_cost_flows_kind",
        ),
        sa.CheckConstraint(
            "kind NOT IN ('produced','reconciled_in','consumed')"
            " OR (execution_id IS NOT NULL AND execution_step_id IS NOT NULL AND step_number IS NOT NULL)",
            name="ck_cost_flows_execution_kinds",
        ),
    )
    op.create_index("ix_cost_flows_org_id", "cost_flows", ["org_id"])
    op.create_index("ix_cost_flows_item_direction", "cost_flows", ["org_id", "inventory_item_id", "direction"])
    op.create_index("ix_cost_flows_execution_step", "cost_flows", ["org_id", "execution_id", "step_number"])
    op.create_index("ix_cost_flows_execution_step_id", "cost_flows", ["execution_step_id"])

    op.create_table(
        "lot_cost_entries",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("org_id", UUID, sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("inventory_item_id", UUID, nullable=False),
        sa.Column("cost_flow_id", UUID, nullable=True),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("amount", sa.Numeric(18, 4), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by_user_id", UUID, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("org_id", "id", name="uq_lot_cost_entries_org_id"),
        sa.ForeignKeyConstraint(
            ["org_id", "inventory_item_id"],
            ["inventory_items.org_id", "inventory_items.id"],
            name="fk_lot_cost_entries_item",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "cost_flow_id"],
            ["cost_flows.org_id", "cost_flows.id"],
            name="fk_lot_cost_entries_flow",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "created_by_user_id"],
            ["users.org_id", "users.id"],
            name="fk_lot_cost_entries_creator",
            ondelete="SET NULL (created_by_user_id)",
        ),
        sa.CheckConstraint("kind IN ('manual','free')", name="ck_lot_cost_entries_kind"),
        sa.CheckConstraint("amount >= 0", name="ck_lot_cost_entries_amount"),
        sa.CheckConstraint("quantity > 0", name="ck_lot_cost_entries_quantity"),
        sa.CheckConstraint("kind <> 'free' OR amount = 0", name="ck_lot_cost_entries_free_zero"),
    )
    op.create_index("ix_lot_cost_entries_org_id", "lot_cost_entries", ["org_id"])
    op.create_index(
        "uq_lot_cost_entries_active_flow",
        "lot_cost_entries",
        ["org_id", "inventory_item_id", "cost_flow_id"],
        unique=True,
        postgresql_where=sa.text("is_active AND cost_flow_id IS NOT NULL"),
    )
    op.create_index(
        "uq_lot_cost_entries_active_whole_lot",
        "lot_cost_entries",
        ["org_id", "inventory_item_id"],
        unique=True,
        postgresql_where=sa.text("is_active AND cost_flow_id IS NULL"),
    )

    op.create_table(
        "costing_settings",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("org_id", UUID, sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("use_last_known_price", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("org_id", "id", name="uq_costing_settings_org_id"),
        sa.UniqueConstraint("org_id", name="uq_costing_settings_org"),
    )
    op.create_index("ix_costing_settings_org_id", "costing_settings", ["org_id"])


def downgrade():
    bind = op.get_bind()
    for table in ("cost_flows", "lot_cost_entries", "costing_settings"):
        if bind.execute(text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError(f"{table} contains rows; downgrading would lose them")
    op.drop_index("ix_costing_settings_org_id", table_name="costing_settings", if_exists=True)
    op.drop_table("costing_settings")
    op.drop_index("ix_lot_cost_entries_org_id", table_name="lot_cost_entries", if_exists=True)
    op.drop_index("uq_lot_cost_entries_active_whole_lot", table_name="lot_cost_entries")
    op.drop_index("uq_lot_cost_entries_active_flow", table_name="lot_cost_entries")
    op.drop_table("lot_cost_entries")
    op.drop_index("ix_cost_flows_org_id", table_name="cost_flows", if_exists=True)
    op.drop_index("ix_cost_flows_execution_step_id", table_name="cost_flows")
    op.drop_index("ix_cost_flows_execution_step", table_name="cost_flows")
    op.drop_index("ix_cost_flows_item_direction", table_name="cost_flows")
    op.drop_table("cost_flows")
    op.drop_constraint("uq_execution_steps_org_execution_id", "execution_steps", type_="unique")
