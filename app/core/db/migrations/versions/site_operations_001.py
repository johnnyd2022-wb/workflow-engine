"""Staged release of guarded operations at additional sites.

Revision ID: site_operations_001
Revises: multiple_sites_001
"""

import sqlalchemy as sa
from alembic import op

revision = "site_operations_001"
down_revision = "multiple_sites_001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("organisations", sa.Column("multiple_site_operations_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM organisations WHERE multiple_site_operations_enabled)
      THEN RAISE EXCEPTION 'Close additional-site operations before downgrade'; END IF;
    END $$""")
    op.drop_column("organisations", "multiple_site_operations_enabled")
