"""Include operational-case events in the synced changes-feed partial index.

Revision ID: operational_cases_003
Revises: operational_cases_002

``operational_case`` became a browser-synced entity type in A1. PostgreSQL does not alter
partial-index predicates in place, so replace the existing concurrent index with the
complete feed predicate. This operation is additive to case data and reversible.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "operational_cases_003"
down_revision: str | None = "operational_cases_002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None

_NAME = "ix_entity_events_org_seq_synced"
_SYNCED = ("process", "execution", "execution_step", "step", "inventory_item", "operational_case")
_PREVIOUS_SYNCED = _SYNCED[:-1]


def _predicate(types: tuple[str, ...]) -> str:
    return "entity_type IN (" + ", ".join(f"'{entity_type}'" for entity_type in types) + ")"


def _replace_index(types: tuple[str, ...]) -> None:
    with op.get_context().autocommit_block():
        op.drop_index(_NAME, table_name="entity_events", if_exists=True, postgresql_concurrently=True)
        op.create_index(
            _NAME,
            "entity_events",
            ["org_id", "seq"],
            unique=False,
            postgresql_concurrently=True,
            postgresql_where=text(_predicate(types)),
        )


def upgrade() -> None:
    _replace_index(_SYNCED)


def downgrade() -> None:
    _replace_index(_PREVIOUS_SYNCED)
