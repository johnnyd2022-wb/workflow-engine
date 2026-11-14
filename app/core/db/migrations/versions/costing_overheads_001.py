"""Overheads into cost, opt-in (roadmap 8.1h, spec .agents/specs/live-cogs-overheads.md).

Revision ID: costing_overheads_001
Revises: costing_rules_002

Adds the per-org switch (``costing_settings.include_overheads``, off), the rates an org types
(``overhead_rates``) and the mark on a purchase line that says it is freight
(``purchase_lines.freight``). Additive and reversible; downgrade refuses while any rate or freight
mark exists, because those are typed by a person and have no other copy.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import UUID

revision = "costing_overheads_001"
down_revision = "costing_rules_002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "costing_settings",
        sa.Column("include_overheads", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "purchase_lines",
        sa.Column("freight", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "overhead_rates",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("org_id", UUID, sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("basis", sa.String(10), nullable=False),
        sa.Column("amount", sa.Numeric(18, 6), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by_user_id", UUID, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("org_id", "id", name="uq_overhead_rates_org_id"),
        sa.ForeignKeyConstraint(
            ["org_id", "created_by_user_id"],
            ["users.org_id", "users.id"],
            name="fk_overhead_rates_creator",
            ondelete="SET NULL (created_by_user_id)",
        ),
        sa.CheckConstraint("basis IN ('per_litre','per_batch')", name="ck_overhead_rates_basis"),
        sa.CheckConstraint("amount >= 0", name="ck_overhead_rates_amount"),
        sa.CheckConstraint("length(btrim(name)) BETWEEN 1 AND 80", name="ck_overhead_rates_name"),
    )
    op.create_index("ix_overhead_rates_org_id", "overhead_rates", ["org_id"])
    op.create_index(
        "uq_overhead_rates_name_basis_date",
        "overhead_rates",
        ["org_id", sa.text("lower(btrim(name))"), "basis", "effective_from"],
        unique=True,
    )


def downgrade():
    bind = op.get_bind()
    if bind.execute(text("SELECT 1 FROM overhead_rates LIMIT 1")).first():
        raise RuntimeError("overhead_rates contains rows; downgrading would lose them")
    if bind.execute(text("SELECT 1 FROM purchase_lines WHERE freight LIMIT 1")).first():
        raise RuntimeError("purchase_lines has freight marks; downgrading would lose them")
    op.drop_index("uq_overhead_rates_name_basis_date", table_name="overhead_rates")
    op.drop_index("ix_overhead_rates_org_id", table_name="overhead_rates", if_exists=True)
    op.drop_table("overhead_rates")
    op.drop_column("purchase_lines", "freight")
    op.drop_column("costing_settings", "include_overheads")
