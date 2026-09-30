"""Opt-in site register and additive operational tags (plan 7.1a/b foundations).

Revision ID: multiple_sites_001
Revises: custom_roles_001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "multiple_sites_001"
down_revision = "contract_portal_001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("organisations", sa.Column("multiple_sites_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table(
        "sites",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("address", sa.String(500)),
        sa.Column("kind", sa.String(30), nullable=False, server_default="manufacturing"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("org_id", "id", name="uq_sites_org_id"),
        sa.CheckConstraint("kind IN ('manufacturing','storage','retail','warehouse','event')", name="ck_sites_kind"),
        sa.CheckConstraint("NOT is_default OR is_active", name="ck_sites_default_active"),
    )
    op.create_index("uq_sites_org_name", "sites", ["org_id", sa.text("lower(name)")], unique=True)
    op.create_index("uq_sites_org_default", "sites", ["org_id"], unique=True, postgresql_where=sa.text("is_default"))
    op.execute("INSERT INTO sites (id, org_id, name, is_default) SELECT gen_random_uuid(), id, 'Main site', true FROM organisations")
    for table in ("stock_locations", "executions", "inventory_items"):
        op.add_column(table, sa.Column("site_id", UUID(as_uuid=True), nullable=True))
        op.create_foreign_key(f"fk_{table}_org_site", table, "sites", ["org_id", "site_id"], ["org_id", "id"], ondelete="RESTRICT")
        op.create_index(f"ix_{table}_site_id", table, ["site_id"])
    op.execute("UPDATE stock_locations AS row SET site_id = s.id FROM sites AS s WHERE row.org_id = s.org_id AND s.is_default")
    op.execute("UPDATE executions AS row SET site_id = s.id FROM sites AS s WHERE row.org_id = s.org_id AND s.is_default")
    op.execute("UPDATE inventory_items AS row SET site_id = s.id FROM sites AS s WHERE row.org_id = s.org_id AND s.is_default")
    # Also prevent cross-tenant or mismatched location tags, even for direct SQL.
    op.create_unique_constraint("uq_stock_locations_org_id", "stock_locations", ["org_id", "id"])
    op.create_unique_constraint("uq_stock_locations_org_site_id", "stock_locations", ["org_id", "site_id", "id"])
    op.create_foreign_key("fk_inventory_org_location", "inventory_items", "stock_locations", ["org_id", "location_id"], ["org_id", "id"])
    op.create_foreign_key("fk_inventory_site_location", "inventory_items", "stock_locations", ["org_id", "site_id", "location_id"], ["org_id", "site_id", "id"])


def downgrade():
    # This foundation contains only default-site operations. Do not discard later data.
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM organisations WHERE multiple_sites_enabled)
         OR EXISTS (SELECT 1 FROM sites WHERE NOT is_default)
      THEN RAISE EXCEPTION 'Disable multiple sites and remove additional site configuration before downgrade'; END IF;
    END $$""")
    op.drop_constraint("fk_inventory_site_location", "inventory_items", type_="foreignkey")
    op.drop_constraint("fk_inventory_org_location", "inventory_items", type_="foreignkey")
    op.drop_constraint("uq_stock_locations_org_site_id", "stock_locations", type_="unique")
    op.drop_constraint("uq_stock_locations_org_id", "stock_locations", type_="unique")
    for table in ("inventory_items", "executions", "stock_locations"):
        op.drop_index(f"ix_{table}_site_id", table_name=table)
        op.drop_constraint(f"fk_{table}_org_site", table, type_="foreignkey")
        op.drop_column(table, "site_id")
    op.drop_table("sites")
    op.drop_column("organisations", "multiple_sites_enabled")
