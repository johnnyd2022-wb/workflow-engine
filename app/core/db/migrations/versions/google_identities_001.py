"""Bind Google subjects to existing tenant accounts.

Revision ID: google_identities_001
Revises: custom_roles_001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "google_identities_001"
down_revision = "custom_roles_001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "user_identities",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("email_at_link", sa.String(255), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("provider", "subject", name="uq_user_identity_provider_subject"),
        sa.UniqueConstraint("org_id", "user_id", "provider", name="uq_user_identity_user_provider"),
        sa.ForeignKeyConstraint(
            ["org_id", "user_id"], ["users.org_id", "users.id"], ondelete="CASCADE", name="fk_user_identity_account"
        ),
    )
    op.create_index("ix_user_identities_org_id", "user_identities", ["org_id"])


def downgrade():
    op.drop_table("user_identities")
