"""Design review S3: per-org switch for apps Biz-E hasn't verified.

Revision ID: mcp_oauth_002
Revises: costing_stock_002

Adds ``mcp_org_settings.allow_unverified_clients`` (boolean, NOT NULL, default false). Every
existing organisation becomes "verified apps only", which is the point of the finding: an
unverified client (anyone can register one under any name) can no longer be approved, and its
existing grants get 403 until an admin opts in. Nothing is revoked.

Reversible. Downgrade drops the column; it refuses while any organisation has turned the setting
on, because an administrator chose that and nothing else keeps a copy.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

revision = "mcp_oauth_002"
down_revision = "costing_stock_002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "mcp_org_settings",
        sa.Column("allow_unverified_clients", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade():
    bind = op.get_bind()
    if bind.execute(text("SELECT 1 FROM mcp_org_settings WHERE allow_unverified_clients LIMIT 1")).first():
        raise RuntimeError(
            "mcp_org_settings.allow_unverified_clients is on for an organisation; downgrading would lose it"
        )
    op.drop_column("mcp_org_settings", "allow_unverified_clients")
