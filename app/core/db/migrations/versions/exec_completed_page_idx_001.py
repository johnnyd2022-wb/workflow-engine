"""Composite index for the process-scoped completed-execution page query.

Revision ID: exec_completed_page_idx_001
Revises: feat_subs_seq_merge_001

Index-only, no data change, fully reversible.

!197 added a paged list of an individual process's completed runs:

    WHERE org_id = ? AND process_id = ? AND status = 'completed'
    ORDER BY created_at DESC, id DESC
    LIMIT 26

(execution_repo.list_executions with process_id + status + keyset cursor.)

The existing ix_executions_org_created_id (org_id, created_at DESC, id DESC) serves the
ORDER BY but not the process_id / status predicates, so at scale Postgres walks a lot of
an org's history filtering rows out to return 25; ix_executions_org_status_updated has the
status column but the wrong sort key (updated_at). This adds the covering shape so the
plan stays index-only. LiveSync re-runs the query while a Batches panel is open, so it is
worth the write cost.

`executions` is a hot table (execution create / step complete write it constantly), so
the index is built CONCURRENTLY inside an autocommit block -- a plain CREATE INDEX holds a
SHARE lock that blocks those writes for the whole build, which scales with production
history. CONCURRENTLY cannot run inside a transaction, hence autocommit_block().

A CONCURRENTLY build that is interrupted (cancelled / timed out) leaves an
``indisvalid = false`` index of the same name, and Alembic will not have stamped the
revision. So upgrade() first drops any *invalid* leftover of this name before (re)creating
-- otherwise a plain ``IF NOT EXISTS`` retry would skip creation and Alembic would then
record the revision as applied with no usable index. ``IF NOT EXISTS`` still covers the
"build succeeded but the stamp didn't" retry (a *valid* index is left in place).

CAVEAT (matches core_hub_perf_indexes_001): local/CI data is tiny, so the reversibility
check proves the index builds and drops cleanly, not that the planner needs it yet.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "exec_completed_page_idx_001"
down_revision: str | None = "feat_subs_seq_merge_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None

_NAME = "ix_executions_org_process_status_created_id"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        invalid_leftover = (
            op.get_bind()
            .execute(
                sa.text(
                    "SELECT 1 FROM pg_class c JOIN pg_index i ON i.indexrelid = c.oid "
                    "WHERE c.relname = :n AND NOT i.indisvalid"
                ),
                {"n": _NAME},
            )
            .scalar()
        )
        if invalid_leftover:
            op.drop_index(_NAME, table_name="executions", if_exists=True, postgresql_concurrently=True)

        op.create_index(
            _NAME,
            "executions",
            [
                sa.text("org_id"),
                sa.text("process_id"),
                sa.text("status"),
                sa.text("created_at DESC"),
                sa.text("id DESC"),
            ],
            unique=False,
            if_not_exists=True,
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(_NAME, table_name="executions", if_exists=True, postgresql_concurrently=True)
