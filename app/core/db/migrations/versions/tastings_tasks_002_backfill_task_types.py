"""Backfill existing typed tasks in bounded batches, then require a type.

Only same-org task/event pairs become tastings. Re-running the backfill is a no-op.
No task, event, allocation or removal record is deleted.
"""
from alembic import op
import sqlalchemy as sa

revision = "tastings_tasks_002"
down_revision = "tastings_tasks_001"
branch_labels = None
depends_on = None


def _backfill(db, query, value):
    count = 1000
    while count == 1000:
        rows = db.execute(sa.text(query), {"value": value, "batch_size": 1000}).fetchall()
        count = len(rows)


def upgrade():
    db = op.get_bind()
    _backfill(
        db,
        "WITH batch AS (SELECT task.id FROM crm_tasks task "
        "WHERE task.task_type IS NULL ORDER BY task.id LIMIT :batch_size) "
        "UPDATE crm_tasks task SET task_type = :value FROM batch "
        "WHERE task.id = batch.id RETURNING task.id",
        "general",
    )
    _backfill(
        db,
        "WITH batch AS (SELECT task.id FROM crm_tasks task "
        "WHERE task.task_type != 'tasting' AND EXISTS "
        "(SELECT 1 FROM tastings event WHERE event.task_id = task.id "
        "AND event.org_id = task.org_id) ORDER BY task.id LIMIT :batch_size) "
        "UPDATE crm_tasks task SET task_type = :value FROM batch "
        "WHERE task.id = batch.id RETURNING task.id",
        "tasting",
    )
    op.alter_column("crm_tasks", "task_type", existing_type=sa.String(20), nullable=False)


def downgrade():
    op.alter_column("crm_tasks", "task_type", existing_type=sa.String(20), nullable=True)
