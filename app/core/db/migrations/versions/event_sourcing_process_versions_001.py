"""Add process_versions table and process_version_id on executions

Revision ID: event_sourcing_process_versions_001
Revises: event_sourcing_summaries_001
Create Date: 2026-05-13

process_versions: immutable snapshot of process + all steps at each version.
Answers "what procedure was being followed when Execution #4421 ran?"
process_version_id on executions: permanent link set at creation, never changed.
display_label on inventory_items: pre-computed human-readable label for sourcemap selectors.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "event_sourcing_proc_ver_001"
down_revision: Union[str, None] = "event_sourcing_summaries_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "process_versions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column(
            "process_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("processes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        # Full process + steps snapshot at this version
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("changed_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("change_summary", sa.String(500), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("process_id", "version_number", name="uq_process_versions_process_version"),
    )

    op.create_index(
        "ix_process_versions_process",
        "process_versions",
        ["process_id", sa.text("version_number DESC")],
    )
    op.create_index(
        "ix_process_versions_org",
        "process_versions",
        ["org_id", "created_at"],
    )

    # Link execution to the exact process version that was active when it started
    op.add_column(
        "executions",
        sa.Column(
            "process_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("process_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_executions_process_version", "executions", ["process_version_id"])

    # Pre-computed display label for sourcemap selectors (avoids JOIN at query time)
    op.add_column(
        "inventory_items",
        sa.Column("display_label", sa.String(255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("inventory_items", "display_label")
    op.drop_index("ix_executions_process_version", table_name="executions")
    op.drop_column("executions", "process_version_id")
    op.drop_index("ix_process_versions_org", table_name="process_versions")
    op.drop_index("ix_process_versions_process", table_name="process_versions")
    op.drop_table("process_versions")
