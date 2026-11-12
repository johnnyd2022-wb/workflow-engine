"""Opt-in litres basis for splitting costing pools across free outputs.

Revision ID: costing_split_001
Revises: costing_rules_001
"""

import sqlalchemy as sa
from alembic import op

revision = "costing_split_001"
down_revision = "costing_rules_001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "costing_settings",
        sa.Column("split_basis", sa.String(10), nullable=False, server_default="quantity"),
    )
    op.create_check_constraint(
        "ck_costing_settings_split_basis", "costing_settings", "split_basis IN ('quantity','litres')"
    )


def downgrade():
    op.drop_constraint("ck_costing_settings_split_basis", "costing_settings", type_="check")
    op.drop_column("costing_settings", "split_basis")
