"""Add indexes for ready-date check scalability (>50k executions per org)

Revision ID: idx_ready_date_scale_001
Revises: idx_inventory_expiry_lookup_001
Create Date: 2026-03-07

Adds:
- idx_executions_org_completed: partial index on executions(org_id, id) WHERE completed_at IS NOT NULL
  (speeds up join/filter for output_ready_date check and similar queries).
- idx_steps_outputs_ready_gin: GIN index on steps.outputs (jsonb_path_ops) for jsonb_path_exists
  (speeds up DB-side ready_date pruning on step.outputs).
"""

from typing import Sequence, Union

from alembic import op

revision: str = "idx_ready_date_scale_001"
down_revision: Union[str, None] = "idx_inventory_expiry_lookup_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Partial index: completed executions by org (ready-date check joins here).
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_executions_org_completed
        ON executions (org_id, id)
        WHERE completed_at IS NOT NULL;
        """
    )
    # GIN index on steps.outputs for jsonb_path_exists (ready_date pruning).
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_steps_outputs_ready_gin
        ON steps USING gin (outputs jsonb_path_ops);
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_steps_outputs_ready_gin;")
    op.execute("DROP INDEX IF EXISTS idx_executions_org_completed;")
