"""api_idempotency_keys for idempotent POST retries (e.g. inventory wastage).

Revision ID: api_idempotency_keys_001
Revises: add_first_last_name_to_user_001

Parallel branch with inventory_quantity_numeric_001; merge_inv_qty_api_idem_001 joins them.
Safe to run in CI: upgrade is idempotent if the table already exists.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "api_idempotency_keys_001"
down_revision: Union[str, None] = "add_first_last_name_to_user_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "api_idempotency_keys" in insp.get_table_names():
        return
    op.create_table(
        "api_idempotency_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("response_json", sa.Text(), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("org_id", "key", name="uq_api_idempotency_org_key"),
    )
    op.create_index("ix_api_idempotency_keys_org_id", "api_idempotency_keys", ["org_id"])
    op.create_index("ix_api_idempotency_keys_created_at", "api_idempotency_keys", ["created_at"])


def downgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "api_idempotency_keys" not in insp.get_table_names():
        return
    op.drop_index("ix_api_idempotency_keys_created_at", table_name="api_idempotency_keys")
    op.drop_index("ix_api_idempotency_keys_org_id", table_name="api_idempotency_keys")
    op.drop_table("api_idempotency_keys")
