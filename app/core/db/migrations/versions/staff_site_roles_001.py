"""Configure custom-role site grants; assignment remains closed pending route guards.

Merge the two actual prerequisite heads without rewriting applied migrations.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "staff_site_roles_001"
down_revision = ("contract_orders_001", "multiple_sites_001")
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("org_roles", sa.Column("site_access_mode", sa.String(20), nullable=False, server_default="all"))
    op.create_check_constraint("ck_org_roles_site_access_mode", "org_roles", "site_access_mode IN ('all','selected')")
    op.create_unique_constraint("uq_org_roles_org_id", "org_roles", ["org_id", "id"])
    op.create_table(
        "org_role_sites",
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("role_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("site_id", UUID(as_uuid=True), primary_key=True),
        sa.ForeignKeyConstraint(
            ["org_id", "role_id"],
            ["org_roles.org_id", "org_roles.id"],
            name="fk_org_role_sites_role",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "site_id"], ["sites.org_id", "sites.id"], name="fk_org_role_sites_site", ondelete="RESTRICT"
        ),
    )
    op.create_index("ix_org_role_sites_org_id", "org_role_sites", ["org_id"])


def downgrade():
    # Removing configured restrictions must never silently grant holders all sites.
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM users u JOIN org_roles r ON r.id=u.custom_role_id
                   WHERE r.site_access_mode <> 'all') THEN
            RAISE EXCEPTION 'Remove selected-site role assignments before downgrade';
        END IF;
    END $$""")
    op.drop_table("org_role_sites")
    op.drop_constraint("uq_org_roles_org_id", "org_roles", type_="unique")
    op.drop_constraint("ck_org_roles_site_access_mode", "org_roles", type_="check")
    op.drop_column("org_roles", "site_access_mode")
