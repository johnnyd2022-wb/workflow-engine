"""Add payment_terms to xero_contacts

Revision ID: crm_contact_terms_001
Revises: crm_xero_connection_id_001
Create Date: 2026-05-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "crm_contact_terms_001"
down_revision: str | None = "crm_xero_connection_id_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("xero_contacts", sa.Column("payment_terms", postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column("xero_contacts", "payment_terms")
