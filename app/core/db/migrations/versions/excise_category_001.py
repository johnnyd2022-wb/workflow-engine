"""Excise product type on alcohol products, for the built-in Customs rate guide."""

import sqlalchemy as sa
from alembic import op

revision = "excise_category_001"
down_revision = "crm_contact_sync_default_001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "compliance_alcohol_product_profiles",
        sa.Column("excise_category", sa.String(40), nullable=True),
    )


def downgrade():
    op.drop_column("compliance_alcohol_product_profiles", "excise_category")
