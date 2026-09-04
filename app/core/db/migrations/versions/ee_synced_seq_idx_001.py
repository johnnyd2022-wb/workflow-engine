"""Partial index for the /api/core/changes head query (synced entity types only).

Revision ID: ee_synced_seq_idx_001
Revises: merge_noident_execpage_001

changes_feed.get_changes runs, on every browser tab every ~3 seconds:

    SELECT COALESCE(MAX(seq), 0) FROM entity_events
    WHERE org_id = :org
      AND entity_type IN ('process','execution','execution_step','step','inventory_item')

ix_entity_events_org_seq is (org_id, seq). Postgres scans it backward for the org and
filters entity_type row-by-row until the newest *synced* row. user.login /
user.login_failed / org.* events are frequent and NOT synced types, so the scan removes
every trailing non-synced row -- a count that grows with login activity since the last
content event -- on every poll, per tab.

This partial index carries exactly the feed's filter, so the head query becomes an
index-only backward fetch of one row regardless of login volume. Additive, index-only, no
row rewrite, built CONCURRENTLY. No deploy precondition.

The predicate MUST stay in sync with changes_feed._SYNCED_ENTITY_TYPES -- a test
(tests/test_changes_feed.py::test_synced_types_match_the_partial_index) asserts it.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "ee_synced_seq_idx_001"
down_revision: str | None = "merge_noident_execpage_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None

_NAME = "ix_entity_events_org_seq_synced"
# Keep in sync with changes_feed._SYNCED_ENTITY_TYPES.
_SYNCED = ("process", "execution", "execution_step", "step", "inventory_item")
_PREDICATE = "entity_type IN (" + ", ".join(f"'{t}'" for t in _SYNCED) + ")"


def _drop_if_invalid(bind, name: str) -> None:
    from sqlalchemy import text

    invalid = bind.execute(
        text(
            "SELECT 1 FROM pg_class c JOIN pg_index i ON i.indexrelid = c.oid "
            "WHERE c.relname = :n AND NOT i.indisvalid"
        ),
        {"n": name},
    ).scalar()
    if invalid:
        op.drop_index(name, table_name="entity_events", if_exists=True, postgresql_concurrently=True)


def upgrade() -> None:
    from sqlalchemy import text

    with op.get_context().autocommit_block():
        _drop_if_invalid(op.get_bind(), _NAME)
        op.create_index(
            _NAME,
            "entity_events",
            ["org_id", "seq"],
            unique=False,
            if_not_exists=True,
            postgresql_concurrently=True,
            postgresql_where=text(_PREDICATE),
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(_NAME, table_name="entity_events", if_exists=True, postgresql_concurrently=True)
