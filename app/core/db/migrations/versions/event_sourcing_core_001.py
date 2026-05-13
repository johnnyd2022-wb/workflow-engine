"""Add entity_events table — core append-only event log

Revision ID: event_sourcing_core_001
Revises: wastage_reason_001
Create Date: 2026-05-13

Append-only table that records every mutation in the system with a full
entity-state snapshot. Never delete rows; tombstone events record deletions.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "event_sourcing_core_001"
down_revision: Union[str, None] = "wastage_reason_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "entity_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organisations.id"), nullable=False),
        # What happened
        sa.Column("event_type", sa.String(100), nullable=False),
        # What entity
        sa.Column("entity_type", sa.String(100), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        # Who did it
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("actor_type", sa.String(50), nullable=False, server_default="user"),
        sa.Column("actor_label", sa.String(255), nullable=True),
        # Full entity state AFTER this event
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        # Field-level diff (optional but useful for display)
        sa.Column("diff", postgresql.JSONB(), nullable=True),
        # Causal chain — the event that directly caused this one
        sa.Column("causation_id", postgresql.UUID(as_uuid=True), nullable=True),
        # Top-level HTTP request that triggered this chain (not a FK)
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=True),
        # Request context for audit display
        sa.Column("request_metadata", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # Self-referential FK for causation chain (added after table creation)
    op.create_foreign_key(
        "fk_entity_events_causation",
        "entity_events",
        "entity_events",
        ["causation_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Primary lookup: all events for an entity in order
    op.create_index(
        "ix_entity_events_org_entity",
        "entity_events",
        ["org_id", "entity_type", "entity_id", "created_at"],
    )

    # State reconstruction: entity at time T
    op.create_index(
        "ix_entity_events_entity_time",
        "entity_events",
        ["entity_id", sa.text("created_at DESC")],
    )

    # All events of a type in an org
    op.create_index(
        "ix_entity_events_type",
        "entity_events",
        ["org_id", "event_type", "created_at"],
    )

    # All actions by a user
    op.create_index(
        "ix_entity_events_actor",
        "entity_events",
        ["org_id", "actor_id", "created_at"],
    )

    # Causal chain traversal (partial — only non-null)
    op.create_index(
        "ix_entity_events_causation",
        "entity_events",
        ["causation_id"],
        postgresql_where=sa.text("causation_id IS NOT NULL"),
    )

    # All events in one HTTP request
    op.create_index(
        "ix_entity_events_correlation",
        "entity_events",
        ["correlation_id"],
        postgresql_where=sa.text("correlation_id IS NOT NULL"),
    )

    # Full org timeline (story view)
    op.create_index(
        "ix_entity_events_org_time",
        "entity_events",
        ["org_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_entity_events_org_time", table_name="entity_events")
    op.drop_index("ix_entity_events_correlation", table_name="entity_events")
    op.drop_index("ix_entity_events_causation", table_name="entity_events")
    op.drop_index("ix_entity_events_actor", table_name="entity_events")
    op.drop_index("ix_entity_events_type", table_name="entity_events")
    op.drop_index("ix_entity_events_entity_time", table_name="entity_events")
    op.drop_index("ix_entity_events_org_entity", table_name="entity_events")
    op.drop_constraint("fk_entity_events_causation", "entity_events", type_="foreignkey")
    op.drop_table("entity_events")
