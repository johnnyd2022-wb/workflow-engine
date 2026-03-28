"""Add api_idempotency_keys for idempotent POST /api/core/inventory/wastage

Revision ID: api_idempotency_keys_001
Revises: add_first_last_name_to_user_001
Create Date: 2026-03-28
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "api_idempotency_keys_001"
down_revision: Union[str, None] = "add_first_last_name_to_user_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    table_exists = "api_idempotency_keys" in insp.get_table_names()
    if not table_exists:
        op.create_table(
            "api_idempotency_keys",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organisations.id"), nullable=False, index=True),
            sa.Column("key", sa.String(128), nullable=False),
            sa.Column("payload_hash", sa.String(64), nullable=False),
            sa.Column("response_json", sa.Text(), nullable=False),
            sa.Column("http_status", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_unique_constraint(
            "uq_api_idempotency_org_key",
            "api_idempotency_keys",
            ["org_id", "key"],
        )


def downgrade() -> None:
    op.drop_constraint("uq_api_idempotency_org_key", "api_idempotency_keys", type_="unique")
    op.drop_table("api_idempotency_keys")
