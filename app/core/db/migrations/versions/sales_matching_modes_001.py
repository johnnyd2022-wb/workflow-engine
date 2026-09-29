"""Sales-matching modes: review status and pre-sold flag on sale allocations

Revision ID: sales_matching_modes_001
Revises: org_go_live_date_001
Create Date: 2026-09-25

Plan item 1.1. ``status`` is "confirmed" (the default: every existing allocation) or
"pending_review" (hybrid mode: waiting for the owner until ``review_due_at``, then
confirmed automatically). ``presold`` marks a sale filled from a batch made after the
invoice date, which is normal (producers sell ahead of bottling) and shown, not blocked.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "sales_matching_modes_001"
down_revision: Union[str, None] = "org_go_live_date_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "crm_sales_fifo_allocations"


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("status", sa.String(20), nullable=False, server_default="confirmed"))
    op.add_column(TABLE, sa.Column("presold", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column(TABLE, sa.Column("review_due_at", sa.TIMESTAMP(timezone=True), nullable=True))
    op.create_index("ix_crm_sales_fifo_allocations_pending", TABLE, ["org_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_crm_sales_fifo_allocations_pending", table_name=TABLE)
    op.drop_column(TABLE, "review_due_at")
    op.drop_column(TABLE, "presold")
    op.drop_column(TABLE, "status")
