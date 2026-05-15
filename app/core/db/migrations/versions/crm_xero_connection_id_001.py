"""Add xero_connection_id to xero_tenants

Revision ID: crm_xero_connection_id_001
Revises: add_crm_xero_tables_001
Create Date: 2026-05-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "crm_xero_connection_id_001"
down_revision: str | None = "add_crm_xero_tables_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("xero_tenants", sa.Column("xero_connection_id", sa.String(100), nullable=True))


def downgrade() -> None:
    op.drop_column("xero_tenants", "xero_connection_id")
