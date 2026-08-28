"""Composite (org_id, <time> DESC) indexes for the three remaining org-scoped
time-ordered scans that only had single-column indexes.

Revision ID: org_time_indexes_001
Revises: core_hub_perf_indexes_001

Index-only, no data change, fully reversible. A schema-wide audit found the multi-tenant
tables are otherwise already well-covered (entity_events, crm_tasks, compliance_*,
process_versions, steps, inventory_movements(org,item,created) all have the composites
they need). These three did not:

  * audit_logs      -- AuditRepository.list: WHERE org_id [AND user_id/action/entity]
                       ORDER BY timestamp DESC LIMIT/OFFSET  (had only ix_audit_logs_org_id
                       + a separate ix_audit_logs_timestamp -> scan-all-org + sort)
  * inventory_movements -- InventoryRepository.movement_totals_since: WHERE org_id AND
                       created_at >= ?, and CompliantService's WHERE org_id + MAX(created_at)
                       / SUM group-by  (had (org_id, inventory_item_id, created_at) but no
                       (org_id, created_at))
  * inventory_wastage -- WastageRepository: WHERE org_id [AND inventory_item_id]
                       ORDER BY recorded_at DESC

At current data sizes a bitmap scan + in-memory sort is fine; these keep the plan
index-ordered as a tenant's history grows into the millions of rows. CAVEAT: local/CI
data is tiny -- the reversibility check proves the indexes build and drop cleanly, not
that the planner needs them yet.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "org_time_indexes_001"
down_revision: str | None = "core_hub_perf_indexes_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


_INDEXES = [
    ("ix_audit_logs_org_timestamp", "audit_logs", [sa.text("org_id"), sa.text('"timestamp" DESC')]),
    ("ix_inventory_movements_org_created", "inventory_movements", [sa.text("org_id"), sa.text("created_at DESC")]),
    ("ix_inventory_wastage_org_recorded", "inventory_wastage", [sa.text("org_id"), sa.text("recorded_at DESC")]),
]


def upgrade() -> None:
    for name, table, cols in _INDEXES:
        op.create_index(name, table, cols, unique=False, if_not_exists=True)


def downgrade() -> None:
    for name, table, _cols in reversed(_INDEXES):
        op.drop_index(name, table_name=table, if_exists=True)
