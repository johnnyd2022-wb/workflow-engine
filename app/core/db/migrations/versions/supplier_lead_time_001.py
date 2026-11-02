"""How long a supplier takes to deliver (GL-P07 B2b).

`suppliers.lead_time_days`: days from ordering to the stock arriving. When a planned batch is
short of a material, its supplier's lead time turns the shortage into an "order by" date.
Optional; downgrade drops it only when no supplier has one.

Revision ID: supplier_lead_time_001
Revises: planning_commitments_001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

revision = "supplier_lead_time_001"
down_revision = "planning_commitments_001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("suppliers", sa.Column("lead_time_days", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "ck_suppliers_lead_time_days", "suppliers", "lead_time_days IS NULL OR lead_time_days BETWEEN 0 AND 365"
    )


def downgrade():
    if op.get_bind().execute(text("SELECT 1 FROM suppliers WHERE lead_time_days IS NOT NULL LIMIT 1")).first():
        raise RuntimeError("Suppliers have lead times recorded; downgrading would lose them")
    op.drop_constraint("ck_suppliers_lead_time_days", "suppliers", type_="check")
    op.drop_column("suppliers", "lead_time_days")
