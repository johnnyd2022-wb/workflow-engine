"""Step timing on the workflow: how long a step takes, and how long it then waits (GL-P07 B1).

- `steps.duration_minutes`: working time for one batch at this step.
- `steps.wait_minutes`: resting, settling or ageing after it, before the next step can start.

Both are optional; the planner asks for them per workflow until every step has them. A fixed
ready date on an output still adds its own wait, as before.

Downgrade drops them only when no step has a timing.

Revision ID: step_timing_001
Revises: stock_outings_001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

revision = "step_timing_001"
down_revision = "stock_outings_001"
branch_labels = None
depends_on = None

# A year in minutes, the planner's existing limit for a step (planning/batch_service.MAX_MINUTES).
_LIMIT = 525_600


def upgrade():
    for name in ("duration_minutes", "wait_minutes"):
        op.add_column("steps", sa.Column(name, sa.Integer(), nullable=True))
        op.create_check_constraint(f"ck_steps_{name}", "steps", f"{name} IS NULL OR {name} BETWEEN 0 AND {_LIMIT}")


def downgrade():
    used = (
        op.get_bind()
        .execute(text("SELECT 1 FROM steps WHERE duration_minutes IS NOT NULL OR wait_minutes IS NOT NULL LIMIT 1"))
        .first()
    )
    if used:
        raise RuntimeError("Workflow steps have timings recorded; downgrading would lose them")
    for name in ("wait_minutes", "duration_minutes"):
        op.drop_constraint(f"ck_steps_{name}", "steps", type_="check")
        op.drop_column("steps", name)
