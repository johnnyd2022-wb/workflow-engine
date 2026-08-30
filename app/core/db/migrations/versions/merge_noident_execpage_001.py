"""Merge the two alembic heads left on main by !206 and !208.

Revision ID: merge_noident_execpage_001
Revises: entity_events_seq_noident_001, exec_completed_page_idx_001

!206 (exec_completed_page_idx_001 -- composite index on executions) and !208
(entity_events_seq_noident_001 -- drop entity_events.seq IDENTITY + UNIQUE index) both
branched off feat_subs_seq_merge_001 and both merged to main without either being rebased
onto the other, leaving `main` with two alembic heads ("Multiple head revisions for
'head'"). `alembic upgrade head` on main fails until this reunifies the graph.

The two branches touch disjoint schema -- executions vs entity_events -- so there is
nothing to reconcile. This is an empty merge revision: no upgrade/downgrade body, it only
re-unifies the DAG to a single head. It applies as a no-op from every state (fresh, or a
DB that already recorded either or both heads).

Note: entity_events_seq_noident_001 carries its own DEPLOY PRECONDITION (MR !205 must be
fully rolled out before it runs). This merge revision does not change that -- see that
migration's docstring.
"""

from collections.abc import Sequence

revision: str = "merge_noident_execpage_001"
down_revision: tuple[str, ...] | str | None = (
    "entity_events_seq_noident_001",
    "exec_completed_page_idx_001",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
