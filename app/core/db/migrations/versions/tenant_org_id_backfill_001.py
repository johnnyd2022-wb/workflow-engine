"""Backfill org_id on steps, execution_steps, trusted_devices, two_factor_backup_codes from
their parent row (data edit only -- schema was already added in tenant_org_id_add_001, see
migration-safety skill: "backfills live in their own revision").

Revision ID: tenant_org_id_backfill_001
Revises: tenant_org_id_add_001
Create Date: 2026-08-09

Idempotent and re-runnable: every UPDATE is guarded by `WHERE org_id IS NULL`, so re-running
this revision (or applying it after a partial prior run) only touches rows still missing
org_id. Not chunked/batched -- these are dev/test-scale tables today (see the codebase's own
precedent in add_execution_step_tracking_fields.py, an unchunked single-UPDATE backfill); a
batched rewrite is straightforward to add later if row counts ever make one unconditional
UPDATE risky, without changing this revision's shape.

Backfill correctness: every steps.process_id and execution_steps.execution_id, and every
trusted_devices.user_id and two_factor_backup_codes.user_id, is NOT NULL and FK-enforced
today, so every row has exactly one parent to inherit org_id from -- no NULL/ambiguous cases
possible under the existing schema.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "tenant_org_id_backfill_001"
down_revision: str | None = "tenant_org_id_add_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, parent_table, fk_column_on_table) -- steps/execution_steps' parents carry org_id
# directly; trusted_devices/two_factor_backup_codes go through users.org_id.
_BACKFILLS = (
    ("steps", "processes", "process_id"),
    ("execution_steps", "executions", "execution_id"),
    ("trusted_devices", "users", "user_id"),
    ("two_factor_backup_codes", "users", "user_id"),
)


def upgrade() -> None:
    for table, parent_table, fk_column in _BACKFILLS:
        # table/parent_table/fk_column are SQL identifiers (table and column names), not
        # values -- bind params (:val) can't parameterise identifiers, only literals. All
        # three come from the hardcoded _BACKFILLS tuple above, never from request/user
        # input, so there's no injection surface despite the f-string shape. Not an N+1
        # either: this is a one-time migration over a fixed 4-table list, not a per-request
        # ORM query.
        op.execute(  # nosemgrep: raw-sql-fstring, raw-sql-fstring-no-args, sqlalchemy-query-in-for-loop, python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query, python.lang.security.audit.formatted-sql-query.formatted-sql-query
            f"""
            UPDATE {table} t
            SET org_id = p.org_id
            FROM {parent_table} p
            WHERE p.id = t.{fk_column}
              AND t.org_id IS NULL
            """
        )


def downgrade() -> None:
    # Data-only revision: reversing it means clearing what it set, mirroring upgrade()'s own
    # idempotency guard so a downgrade -> upgrade cycle backfills identically either way.
    for table, _parent_table, _fk_column in reversed(_BACKFILLS):
        # Same reasoning as upgrade() above: table is a hardcoded identifier, not user input.
        op.execute(f"UPDATE {table} SET org_id = NULL")  # nosemgrep: raw-sql-fstring, raw-sql-fstring-no-args, sqlalchemy-query-in-for-loop, python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query, python.lang.security.audit.formatted-sql-query.formatted-sql-query
