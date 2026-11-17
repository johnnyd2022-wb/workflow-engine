"""A stock value snapshot is provisional until its month is closed (design review L1, live-cogs 8.1g).

Adds ``stock_value_snapshots.status`` (``provisional`` | ``closed``), ``closed_at`` and
``closed_by_user_id``. An automatic month-end snapshot freezes its quantities at the cutoff; its
valuation stays provisional (every read re-prices those quantities) until someone with
``costs.manage`` closes the month or it closes itself on the 20th of the next month. Closing writes
the valuation once.

Every snapshot that exists already was valued and held fixed when it was taken, so it becomes
``closed`` (``closed_at`` = when it was taken): nothing that exists moves. Additive; downgrade drops
only what this adds and refuses while any snapshot is provisional, because the code before this
change would read a provisional snapshot's stored figures as closed ones.

Revision ID: costing_stock_002
Revises: mcp_oauth_001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

revision = "costing_stock_002"
down_revision = "mcp_oauth_001"
branch_labels = None
depends_on = None

TABLE = "stock_value_snapshots"


def upgrade():
    op.add_column(TABLE, sa.Column("status", sa.String(12), nullable=False, server_default="closed"))
    op.add_column(TABLE, sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(TABLE, sa.Column("closed_by_user_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.execute(text(f"UPDATE {TABLE} SET closed_at = taken_at WHERE status = 'closed' AND closed_at IS NULL"))
    op.create_check_constraint("ck_stock_value_snapshots_status", TABLE, "status IN ('provisional','closed')")
    op.create_foreign_key(
        "fk_stock_value_snapshots_closed_by",
        TABLE,
        "users",
        ["org_id", "closed_by_user_id"],
        ["org_id", "id"],
        ondelete="SET NULL (closed_by_user_id)",
    )


def downgrade():
    bind = op.get_bind()
    if bind.execute(text(f"SELECT 1 FROM {TABLE} WHERE status = 'provisional' LIMIT 1")).first():
        raise RuntimeError(
            "stock_value_snapshots has provisional months; close them before downgrading, or the old code "
            "would read their provisional figures as closed ones"
        )
    op.drop_constraint("fk_stock_value_snapshots_closed_by", TABLE, type_="foreignkey")
    op.drop_constraint("ck_stock_value_snapshots_status", TABLE, type_="check")
    op.drop_column(TABLE, "closed_by_user_id")
    op.drop_column(TABLE, "closed_at")
    op.drop_column(TABLE, "status")
