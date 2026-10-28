"""Stock area names are unique within a site, not across the whole organisation (GL-P07 A3).

Two sites can each have a "Dry store". Areas with no site (an organisation that never switched
on multiple sites) still clash with each other: NULLS NOT DISTINCT keeps the old rule for them.

Downgrade refuses, rather than renaming anything, while two sites share an area name.

Revision ID: site_area_names_001
Revises: multi_site_gates_001
"""

from alembic import op
from sqlalchemy import text

revision = "site_area_names_001"
down_revision = "multi_site_gates_001"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("uq_stock_locations_org_name", "stock_locations", type_="unique")
    op.create_unique_constraint(
        "uq_stock_locations_org_site_name",
        "stock_locations",
        ["org_id", "site_id", "name"],
        postgresql_nulls_not_distinct=True,
    )


def downgrade():
    shared = op.get_bind().execute(
        text("SELECT org_id, name FROM stock_locations GROUP BY org_id, name HAVING count(*) > 1 LIMIT 1")
    ).first()
    if shared is not None:
        raise RuntimeError(
            f"Stock area name {shared.name!r} is used at more than one site in organisation {shared.org_id}; "
            "rename one before downgrading"
        )
    op.drop_constraint("uq_stock_locations_org_site_name", "stock_locations", type_="unique")
    op.create_unique_constraint("uq_stock_locations_org_name", "stock_locations", ["org_id", "name"])
