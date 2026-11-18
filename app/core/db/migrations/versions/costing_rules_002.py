"""Purchase rules keep the payee and description as typed, beside the normalised matcher.

Revision ID: costing_rules_002
Revises: costing_split_001

Matching stays on the normalised ``payee_pattern`` / ``description_pattern`` (lower case, single
spaces); the new ``*_display`` columns only carry what the person typed, for showing back. Existing
rules have no typed form and keep showing the normalised one. Additive and reversible.
"""

import sqlalchemy as sa
from alembic import op

revision = "costing_rules_002"
down_revision = "costing_split_001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("purchase_rules", sa.Column("payee_display", sa.String(255), nullable=True))
    op.add_column("purchase_rules", sa.Column("description_display", sa.String(500), nullable=True))


def downgrade():
    op.drop_column("purchase_rules", "description_display")
    op.drop_column("purchase_rules", "payee_display")
