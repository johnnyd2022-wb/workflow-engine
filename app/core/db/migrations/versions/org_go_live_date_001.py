"""Organisation go-live date

Revision ID: org_go_live_date_001
Revises: product_mapping_pack_size_001
Create Date: 2026-09-25

Plan item 1.3: a producer starts with a go-live stocktake instead of rebuilding past
production. Traceability starts on this date; Xero sales dated before it still show in
sales reporting but aren't matched to batches.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "org_go_live_date_001"
down_revision: Union[str, None] = "product_mapping_pack_size_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("organisations", sa.Column("go_live_date", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("organisations", "go_live_date")
