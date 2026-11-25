"""Store pending Xero account selections separately from active connections."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "xero_pending_001"
down_revision = "mcp_oauth_002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "xero_pending_connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("connections", postgresql.JSONB(), nullable=False),
        sa.Column("credentials_encrypted", sa.Text(), nullable=False),
        sa.Column("token_expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.UniqueConstraint("org_id", name="uq_xero_pending_connections_org"),
        sa.ForeignKeyConstraint(
            ["org_id", "user_id"], ["users.org_id", "users.id"], name="fk_xero_pending_connections_user", ondelete="CASCADE"
        ),
    )
    op.create_index("ix_xero_pending_connections_org_id", "xero_pending_connections", ["org_id"])


def downgrade():
    op.drop_table("xero_pending_connections")
