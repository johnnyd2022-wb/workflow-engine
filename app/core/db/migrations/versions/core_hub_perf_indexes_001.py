"""Composite indexes for the /core hub overview + list pagination query patterns.

Revision ID: core_hub_perf_indexes_001
Revises: compliant_nz_alcohol_001

Index-only, no data change, fully reversible. See docs/core-load-performance-design.md.
The tables today carry only single-column ``org_id`` indexes; every hot /core query
filters by ``org_id`` and then sorts or filters on another column:

  * list_executions / list_inventory_items (keyset pagination) -> ORDER BY
    (org_id, created_at DESC, id DESC)
  * list_active_execution_summaries -> WHERE org_id AND status IN (...) ORDER BY
    updated_at DESC
  * list_processes / list_process_names -> WHERE org_id ORDER BY created_at DESC

At current data sizes a bitmap scan on ix_*_org_id + an in-memory sort is fine; these
exist so the plan stays index-only at commercial volume. CAVEAT (docs): local/CI data is
tiny, so the reversibility check proves the indexes build and drop cleanly, not that the
planner needs them yet -- that needs production-shaped volume.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "core_hub_perf_indexes_001"
down_revision: str | None = "compliant_nz_alcohol_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


_INDEXES = [
    (
        "ix_executions_org_created_id",
        "executions",
        [sa.text("org_id"), sa.text("created_at DESC"), sa.text("id DESC")],
    ),
    (
        "ix_executions_org_status_updated",
        "executions",
        [sa.text("org_id"), sa.text("status"), sa.text("updated_at DESC")],
    ),
    (
        "ix_inventory_items_org_created_id",
        "inventory_items",
        [sa.text("org_id"), sa.text("created_at DESC"), sa.text("id DESC")],
    ),
    (
        "ix_processes_org_created",
        "processes",
        [sa.text("org_id"), sa.text("created_at DESC")],
    ),
]


def upgrade() -> None:
    for name, table, cols in _INDEXES:
        op.create_index(name, table, cols, unique=False, if_not_exists=True)


def downgrade() -> None:
    for name, table, _cols in reversed(_INDEXES):
        op.drop_index(name, table_name=table, if_exists=True)
