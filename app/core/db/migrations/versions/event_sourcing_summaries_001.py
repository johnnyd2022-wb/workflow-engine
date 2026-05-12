"""Add entity_event_summaries table — pre-computed read model for list views

Revision ID: event_sourcing_summaries_001
Revises: event_sourcing_core_001
Create Date: 2026-05-13

Upserted atomically (same transaction) on every event write. Powers list-view
card enrichment without N+1 queries against entity_events. Kept consistent
with entity_events via same-transaction upsert in EventWriter.emit().
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "event_sourcing_summaries_001"
down_revision: Union[str, None] = "event_sourcing_core_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "entity_event_summaries",
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("entity_type", sa.String(100), nullable=False),
        # JSONB summary shape is entity-type-specific (see event_writer.py)
        sa.Column("summary", postgresql.JSONB(), nullable=False),
        sa.Column("last_event_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("last_event_type", sa.String(100), nullable=False),
        sa.Column("last_actor", sa.String(255), nullable=True),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # List view: all summaries for org + type (inventory list, process list, etc.)
    op.create_index(
        "ix_entity_summaries_org_type",
        "entity_event_summaries",
        ["org_id", "entity_type"],
    )

    # Sort by most recently active
    op.create_index(
        "ix_entity_summaries_last_event",
        "entity_event_summaries",
        ["org_id", "entity_type", sa.text("last_event_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_entity_summaries_last_event", table_name="entity_event_summaries")
    op.drop_index("ix_entity_summaries_org_type", table_name="entity_event_summaries")
    op.drop_table("entity_event_summaries")
