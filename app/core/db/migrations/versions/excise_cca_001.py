"""An excise entry per CCA licence once a business works at several sites (GL-P07 A5).

`excise_lodgements.licence_id` names the CCA licence an entry was lodged for; it is empty for a
single-site business, whose one entry covers its one licensed area. A period is unique per
licence (NULLS NOT DISTINCT, so the single-site rule is unchanged). The composite foreign key
keeps the licence inside the same organisation.

Downgrade refuses, rather than deleting anything, while any entry names a licence.

Revision ID: excise_cca_001
Revises: site_area_names_001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import UUID

revision = "excise_cca_001"
down_revision = "site_area_names_001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("excise_lodgements", sa.Column("licence_id", UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_excise_lodgements_org_licence",
        "excise_lodgements",
        "customs_licences",
        ["org_id", "licence_id"],
        ["org_id", "id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint("uq_excise_lodgements_org_period", "excise_lodgements", type_="unique")
    op.create_unique_constraint(
        "uq_excise_lodgements_org_licence_period",
        "excise_lodgements",
        ["org_id", "licence_id", "period_start"],
        postgresql_nulls_not_distinct=True,
    )


def downgrade():
    if op.get_bind().execute(text("SELECT 1 FROM excise_lodgements WHERE licence_id IS NOT NULL LIMIT 1")).first():
        raise RuntimeError("Excise entries have been lodged per CCA licence; downgrading would lose which CCA each is for")
    op.drop_constraint("uq_excise_lodgements_org_licence_period", "excise_lodgements", type_="unique")
    op.create_unique_constraint("uq_excise_lodgements_org_period", "excise_lodgements", ["org_id", "period_start"])
    op.drop_constraint("fk_excise_lodgements_org_licence", "excise_lodgements", type_="foreignkey")
    op.drop_column("excise_lodgements", "licence_id")
