"""Add ON DELETE CASCADE to entity_events and entity_event_summaries org_id FKs

Revision ID: event_sourcing_org_cascade_001
Revises: event_sourcing_proc_ver_001
Create Date: 2026-05-14

Without CASCADE, deleting an organisation fails if any entity_events or
entity_event_summaries rows still reference it — both in test teardown and
in any future org-deletion flow.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "event_sourcing_org_cascade_001"
down_revision: Union[str, None] = "event_sourcing_proc_ver_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("entity_events_org_id_fkey", "entity_events", type_="foreignkey")
    op.create_foreign_key(
        "entity_events_org_id_fkey",
        "entity_events",
        "organisations",
        ["org_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.drop_constraint("entity_event_summaries_org_id_fkey", "entity_event_summaries", type_="foreignkey")
    op.create_foreign_key(
        "entity_event_summaries_org_id_fkey",
        "entity_event_summaries",
        "organisations",
        ["org_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("entity_events_org_id_fkey", "entity_events", type_="foreignkey")
    op.create_foreign_key(
        "entity_events_org_id_fkey",
        "entity_events",
        "organisations",
        ["org_id"],
        ["id"],
    )

    op.drop_constraint("entity_event_summaries_org_id_fkey", "entity_event_summaries", type_="foreignkey")
    op.create_foreign_key(
        "entity_event_summaries_org_id_fkey",
        "entity_event_summaries",
        "organisations",
        ["org_id"],
        ["id"],
    )
