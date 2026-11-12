"""Recording purchases into stock (roadmap 8.1c-1, spec .agents/specs/live-cogs.md).

`purchase_lines` gains `state`, `not_stock_amount`, `review_reason`; new `purchase_allocations`
(a purchase line paying for a lot's inflow; negative = refund). Additive. Downgrade refuses while
any allocation exists or any line has been acted on (people's decisions, with no other copy).

Revision ID: costing_allocations_001
Revises: costing_purchases_001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

revision = "costing_allocations_001"
down_revision = "costing_purchases_001"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)
TS = sa.DateTime(timezone=True)


def upgrade():
    op.add_column("purchase_lines", sa.Column("state", sa.String(20), nullable=False, server_default="open"))
    op.add_column(
        "purchase_lines", sa.Column("not_stock_amount", sa.Numeric(18, 4), nullable=False, server_default="0")
    )
    op.add_column("purchase_lines", sa.Column("review_reason", sa.String(20), nullable=True))
    op.create_check_constraint(
        "ck_purchase_lines_state",
        "purchase_lines",
        "state IN ('open','partly_recorded','recorded','skipped','not_stock')",
    )
    op.create_check_constraint(
        "ck_purchase_lines_review",
        "purchase_lines",
        "review_reason IS NULL OR review_reason IN ('amount_changed','recoded','deleted_in_xero')",
    )
    op.create_table(
        "purchase_allocations",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("org_id", UUID, sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("purchase_line_id", UUID, nullable=False),
        sa.Column("inventory_item_id", UUID, nullable=False),
        sa.Column("cost_flow_id", UUID, nullable=True),
        sa.Column("amount", sa.Numeric(18, 4), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default="active"),
        sa.Column("orphaned_by", sa.String(10), nullable=True),
        sa.Column("created_by_user_id", UUID, nullable=True),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("org_id", "id", name="uq_purchase_allocations_org_id"),
        sa.UniqueConstraint("org_id", "purchase_line_id", "inventory_item_id", name="uq_purchase_allocations_line_lot"),
        sa.ForeignKeyConstraint(
            ["org_id", "purchase_line_id"], ["purchase_lines.org_id", "purchase_lines.id"], name="fk_purchase_allocations_line"
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "inventory_item_id"],
            ["inventory_items.org_id", "inventory_items.id"],
            name="fk_purchase_allocations_item",
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "cost_flow_id"], ["cost_flows.org_id", "cost_flows.id"], name="fk_purchase_allocations_flow"
        ),
        sa.CheckConstraint("status IN ('active','orphaned')", name="ck_purchase_allocations_status"),
        sa.CheckConstraint(
            "(amount < 0 AND cost_flow_id IS NULL AND quantity = 0)"
            " OR (amount >= 0 AND cost_flow_id IS NOT NULL AND quantity > 0)",
            name="ck_purchase_allocations_shape",
        ),
    )
    op.create_index("ix_purchase_allocations_org_id", "purchase_allocations", ["org_id"])
    op.create_index("ix_purchase_allocations_item", "purchase_allocations", ["org_id", "inventory_item_id"])


def downgrade():
    bind = op.get_bind()
    if bind.execute(text("SELECT 1 FROM purchase_allocations LIMIT 1")).first():
        raise RuntimeError("purchase_allocations contains rows; downgrading would lose them")
    if bind.execute(
        text("SELECT 1 FROM purchase_lines WHERE state <> 'open' OR not_stock_amount <> 0 OR review_reason IS NOT NULL LIMIT 1")
    ).first():
        raise RuntimeError("purchase lines have been acted on; downgrading would lose that")
    op.drop_index("ix_purchase_allocations_item", table_name="purchase_allocations")
    op.drop_index("ix_purchase_allocations_org_id", table_name="purchase_allocations")
    op.drop_table("purchase_allocations")
    op.drop_constraint("ck_purchase_lines_review", "purchase_lines", type_="check")
    op.drop_constraint("ck_purchase_lines_state", "purchase_lines", type_="check")
    op.drop_column("purchase_lines", "review_reason")
    op.drop_column("purchase_lines", "not_stock_amount")
    op.drop_column("purchase_lines", "state")
