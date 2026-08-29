"""Add feature_subscriptions: generic per-org product entitlement grants.

Revision ID: feature_subscriptions_001
Revises: system_findings_cache_001

New table. DESTRUCTIVE ON DOWNGRADE: `downgrade()` drops the table, which permanently
loses every entitlement grant once it is populated. There is no in-migration data
preservation. Before downgrading any environment that holds real grants:

    \\copy feature_subscriptions to 'feature_subscriptions.csv' csv header

To restore: re-run `upgrade`, then

    \\copy feature_subscriptions from 'feature_subscriptions.csv' csv header

`downgrade()` logs (warning level) the row count it is about to drop.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "feature_subscriptions_001"
down_revision: str | None = "system_findings_cache_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "feature_subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organisations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("feature_key", sa.String(80), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "granted_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("notes", sa.String(500), nullable=True),
        sa.UniqueConstraint("org_id", "feature_key", name="uq_feature_subscriptions_org_feature"),
    )
    op.create_index(
        "ix_feature_subscriptions_org_feature",
        "feature_subscriptions",
        ["org_id", "feature_key"],
    )


def downgrade() -> None:
    import logging

    bind = op.get_bind()
    # A migration runs in the alembic process, outside the app/request lifecycle;
    # app.observability.get_logger would drag the app config stack into env.py. Alembic's
    # own logger is the correct sink here.
    logger = logging.getLogger("alembic.runtime.migration")  # nosemgrep: no-stdlib-getlogger
    exists = bind.execute(sa.text("SELECT to_regclass('public.feature_subscriptions')")).scalar()
    if exists is None:
        logger.warning("feature_subscriptions_001.downgrade: table already absent, nothing to drop")
        return
    row_count = bind.execute(sa.text("SELECT count(*) FROM feature_subscriptions")).scalar()
    logger.warning(
        "feature_subscriptions_001.downgrade dropping feature_subscriptions table with %s entitlement row(s) "
        "-- this is irrecoverable except from a prior CSV export (see migration docstring)",
        row_count,
    )
    op.drop_index("ix_feature_subscriptions_org_feature", table_name="feature_subscriptions")
    op.drop_table("feature_subscriptions")
