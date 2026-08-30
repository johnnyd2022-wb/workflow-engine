"""Per-org cache of the /api/core/system-findings payload.

Revision ID: system_findings_cache_001
Revises: org_time_indexes_001

New table, no change to existing data. Reversible (downgrade drops the table).

Originally branched off core_hub_perf_indexes_001 alongside org_time_indexes_001 (both
merged to main independently, leaving two alembic heads). Re-parented onto
org_time_indexes_001 on 2026-08-29 to linearise the chain -- neither migration touches
the other's objects, so ordering is free.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "system_findings_cache_001"
down_revision: str | None = "org_time_indexes_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "system_findings_cache",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organisations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("stale", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("org_id", name="uq_system_findings_cache_org"),
    )
    op.create_index("ix_system_findings_cache_org_id", "system_findings_cache", ["org_id"])


def downgrade() -> None:
    op.drop_index("ix_system_findings_cache_org_id", table_name="system_findings_cache")
    op.drop_table("system_findings_cache")
