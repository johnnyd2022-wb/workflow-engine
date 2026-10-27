"""Expand CRM task types; nullable until the explicit backfill revision.

Generated with Alembic autogenerate; unrelated existing schema drift removed.
"""
from alembic import op
import sqlalchemy as sa

revision = "tastings_tasks_001"
down_revision = "tastings_001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("crm_tasks", sa.Column("task_type", sa.String(20), nullable=True))
    op.alter_column("crm_tasks", "task_type", server_default="general")
    op.create_check_constraint("ck_crm_tasks_task_type", "crm_tasks", "task_type IN ('general', 'call', 'email', 'tasting')")


def downgrade():
    op.drop_constraint("ck_crm_tasks_task_type", "crm_tasks", type_="check")
    op.drop_column("crm_tasks", "task_type")
