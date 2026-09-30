"""Explicit liquor licence premises/site links; legacy registrations stay unassigned."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "site_licensing_001"
down_revision = "customs_premises_001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("liquor_licences", sa.Column("site_id", UUID(as_uuid=True)))
    op.create_index("ix_liquor_licences_site_id", "liquor_licences", ["site_id"])
    op.create_foreign_key("fk_liquor_licence_site", "liquor_licences", "sites",
                          ["org_id", "site_id"], ["org_id", "id"], ondelete="RESTRICT")


def downgrade():
    op.drop_constraint("fk_liquor_licence_site", "liquor_licences", type_="foreignkey")
    op.drop_index("ix_liquor_licences_site_id", table_name="liquor_licences")
    op.drop_column("liquor_licences", "site_id")
