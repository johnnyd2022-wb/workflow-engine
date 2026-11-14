"""Stock value snapshots and the valued movements between them (roadmap 8.1g, spec .agents/specs/live-cogs.md).

`stock_value_snapshots` (a month-end or manual close, held fixed), `stock_value_lines` (the lots
and unfinished batches in it, as they stood) and `stock_value_movements` (what moved the value
between two snapshots, valued once when the later one is taken). Additive: nothing existing
changes. Lines and movements go with their snapshot (ON DELETE CASCADE); a lot or batch that is
later deleted only loses the link (the name stays as typed). Downgrade drops only what this adds
and refuses while any snapshot exists: a closed month can't be rebuilt, because it was valued
with the costs known when it was taken. Repo convention, as in costing_engine_001.

Revision ID: costing_stock_001
Revises: costing_rules_002
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

revision = "costing_stock_001"
down_revision = "costing_rules_002"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)


def _money(name, *, nullable=False):
    return sa.Column(name, sa.Numeric(18, 4), nullable=nullable, server_default=None if nullable else "0")


def upgrade():
    op.create_table(
        "stock_value_snapshots",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("org_id", UUID, sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("cutoff_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("taken_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("trigger", sa.String(15), nullable=False),
        sa.Column("taken_by_user_id", UUID, nullable=True),
        sa.Column("previous_snapshot_id", UUID, nullable=True),
        sa.Column("quantity_basis", sa.String(15), nullable=False, server_default="exact"),
        sa.Column("currency", sa.String(3), nullable=True),
        _money("total_value"),
        _money("raw_value"),
        _money("in_production_value"),
        _money("wip_value"),
        _money("finished_value"),
        _money("actual_value"),
        _money("estimated_value"),
        _money("partial_value"),
        sa.Column("unknown_lots", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("partial_lots", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lot_count", sa.Integer(), nullable=False, server_default="0"),
        _money("purchases_value", nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("org_id", "id", name="uq_stock_value_snapshots_org_id"),
        sa.ForeignKeyConstraint(
            ["org_id", "taken_by_user_id"],
            ["users.org_id", "users.id"],
            name="fk_stock_value_snapshots_user",
            ondelete="SET NULL (taken_by_user_id)",
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "previous_snapshot_id"],
            ["stock_value_snapshots.org_id", "stock_value_snapshots.id"],
            name="fk_stock_value_snapshots_previous",
            ondelete="SET NULL (previous_snapshot_id)",
        ),
        sa.CheckConstraint("kind IN ('month_end','manual')", name="ck_stock_value_snapshots_kind"),
        sa.CheckConstraint("trigger IN ('xero_sync','costing_read','manual')", name="ck_stock_value_snapshots_trigger"),
        sa.CheckConstraint("quantity_basis IN ('exact','reconstructed')", name="ck_stock_value_snapshots_basis"),
    )
    op.create_index("ix_stock_value_snapshots_org_id", "stock_value_snapshots", ["org_id"])
    op.create_index("ix_stock_value_snapshots_cutoff", "stock_value_snapshots", ["org_id", "cutoff_at"])
    op.create_index(
        "uq_stock_value_snapshots_month_end",
        "stock_value_snapshots",
        ["org_id", "as_of_date"],
        unique=True,
        postgresql_where=sa.text("kind = 'month_end'"),
    )

    op.create_table(
        "stock_value_lines",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("org_id", UUID, sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("snapshot_id", UUID, nullable=False),
        sa.Column("line_type", sa.String(15), nullable=False),
        sa.Column("inventory_item_id", UUID, nullable=True),
        sa.Column("execution_id", UUID, nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("unit", sa.String(50), nullable=True),
        sa.Column("batch", sa.String(255), nullable=True),
        sa.Column("category", sa.String(15), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("unit_cost", sa.Numeric(18, 6), nullable=True),
        sa.Column("known_unit_cost", sa.Numeric(18, 6), nullable=True),
        sa.Column("value", sa.Numeric(18, 4), nullable=True),
        sa.Column("status", sa.String(10), nullable=False),
        sa.UniqueConstraint("org_id", "id", name="uq_stock_value_lines_org_id"),
        sa.ForeignKeyConstraint(
            ["org_id", "snapshot_id"],
            ["stock_value_snapshots.org_id", "stock_value_snapshots.id"],
            name="fk_stock_value_lines_snapshot",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "inventory_item_id"],
            ["inventory_items.org_id", "inventory_items.id"],
            name="fk_stock_value_lines_item",
            ondelete="SET NULL (inventory_item_id)",
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "execution_id"],
            ["executions.org_id", "executions.id"],
            name="fk_stock_value_lines_execution",
            ondelete="SET NULL (execution_id)",
        ),
        sa.CheckConstraint("line_type IN ('lot','in_production')", name="ck_stock_value_lines_type"),
        sa.CheckConstraint(
            "category IN ('raw','in_production','wip','finished')", name="ck_stock_value_lines_category"
        ),
        sa.CheckConstraint("status IN ('actual','estimated','partial','unknown')", name="ck_stock_value_lines_status"),
    )
    op.create_index("ix_stock_value_lines_org_id", "stock_value_lines", ["org_id"])
    op.create_index("ix_stock_value_lines_snapshot", "stock_value_lines", ["org_id", "snapshot_id"])

    op.create_table(
        "stock_value_movements",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("org_id", UUID, sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("snapshot_id", UUID, nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("inventory_item_id", UUID, nullable=True),
        sa.Column("execution_id", UUID, nullable=True),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("unit_cost", sa.Numeric(18, 6), nullable=True),
        sa.Column("value", sa.Numeric(18, 4), nullable=False),
        sa.UniqueConstraint("org_id", "id", name="uq_stock_value_movements_org_id"),
        sa.ForeignKeyConstraint(
            ["org_id", "snapshot_id"],
            ["stock_value_snapshots.org_id", "stock_value_snapshots.id"],
            name="fk_stock_value_movements_snapshot",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "inventory_item_id"],
            ["inventory_items.org_id", "inventory_items.id"],
            name="fk_stock_value_movements_item",
            ondelete="SET NULL (inventory_item_id)",
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "execution_id"],
            ["executions.org_id", "executions.id"],
            name="fk_stock_value_movements_execution",
            ondelete="SET NULL (execution_id)",
        ),
        sa.CheckConstraint(
            "kind IN ('purchase','sale','sample','wastage','variance','transfer','production_loss',"
            "'revaluation','added_other','rounding')",
            name="ck_stock_value_movements_kind",
        ),
    )
    op.create_index("ix_stock_value_movements_org_id", "stock_value_movements", ["org_id"])
    op.create_index("ix_stock_value_movements_snapshot", "stock_value_movements", ["org_id", "snapshot_id", "kind"])


def downgrade():
    bind = op.get_bind()
    if bind.execute(text("SELECT 1 FROM stock_value_snapshots LIMIT 1")).first():
        raise RuntimeError(
            "stock_value_snapshots contains rows; downgrading would lose closed months that can't be rebuilt"
        )
    op.drop_index("ix_stock_value_movements_snapshot", table_name="stock_value_movements")
    op.drop_index("ix_stock_value_movements_org_id", table_name="stock_value_movements", if_exists=True)
    op.drop_table("stock_value_movements")
    op.drop_index("ix_stock_value_lines_snapshot", table_name="stock_value_lines")
    op.drop_index("ix_stock_value_lines_org_id", table_name="stock_value_lines", if_exists=True)
    op.drop_table("stock_value_lines")
    op.drop_index("uq_stock_value_snapshots_month_end", table_name="stock_value_snapshots")
    op.drop_index("ix_stock_value_snapshots_cutoff", table_name="stock_value_snapshots")
    op.drop_index("ix_stock_value_snapshots_org_id", table_name="stock_value_snapshots", if_exists=True)
    op.drop_table("stock_value_snapshots")
