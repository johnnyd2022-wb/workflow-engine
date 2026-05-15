"""Add optional Biz-e source output id to product mappings.

Revision ID: crm_prod_mapping_outputid_001
Revises: crm_contact_terms_001
Create Date: 2026-05-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "crm_prod_mapping_outputid_001"
down_revision: str | None = "crm_contact_terms_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("product_mappings", sa.Column("biz_e_source_output_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index(
        "ix_product_mappings_org_source_output",
        "product_mappings",
        ["org_id", "biz_e_source_output_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_product_mappings_org_source_output", table_name="product_mappings")
    op.drop_column("product_mappings", "biz_e_source_output_id")
