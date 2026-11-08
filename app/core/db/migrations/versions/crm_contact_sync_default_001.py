"""Sales default for sending contacts created in Biz-E to Xero."""

import sqlalchemy as sa
from alembic import op

revision = "crm_contact_sync_default_001"
down_revision = "crm_contacts_created_in_bize_001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "crm_sales_traceability_config",
        sa.Column("sync_contacts_to_xero", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade():
    op.drop_column("crm_sales_traceability_config", "sync_contacts_to_xero")
