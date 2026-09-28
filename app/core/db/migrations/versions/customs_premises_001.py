"""Customs licence register and dated site/location coverage (7.1c foundation)."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "customs_premises_001"
down_revision = "multiple_sites_001"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.create_table(
        "customs_licences",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("number", sa.String(100), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("legal_entity_reference", sa.String(100), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_until", sa.Date()),
        sa.Column("evidence_reference", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("org_id", "id", name="uq_customs_licence_org_id"),
        sa.UniqueConstraint("org_id", "number", name="uq_customs_licence_org_number"),
        sa.CheckConstraint("kind IN ('lma','oss','duty_free','export')", name="ck_customs_licence_kind"),
        sa.CheckConstraint("valid_until IS NULL OR valid_until >= valid_from", name="ck_customs_licence_dates"),
    )
    op.create_index("ix_customs_licences_org_id", "customs_licences", ["org_id"])
    op.create_table(
        "customs_coverage",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("licence_id", UUID(as_uuid=True), nullable=False),
        sa.Column("site_id", UUID(as_uuid=True), nullable=False),
        sa.Column("location_id", UUID(as_uuid=True)),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_until", sa.Date()),
        sa.Column("evidence_reference", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["org_id", "licence_id"],
            ["customs_licences.org_id", "customs_licences.id"],
            name="fk_customs_coverage_licence",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "site_id"], ["sites.org_id", "sites.id"], name="fk_customs_coverage_site", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "site_id", "location_id"],
            ["stock_locations.org_id", "stock_locations.site_id", "stock_locations.id"],
            name="fk_customs_coverage_location",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("valid_until IS NULL OR valid_until >= valid_from", name="ck_customs_coverage_dates"),
    )
    for field in ("org_id", "licence_id", "site_id"):
        op.create_index(f"ix_customs_coverage_{field}", "customs_coverage", [field])
    op.execute("""ALTER TABLE customs_coverage ADD CONSTRAINT ex_customs_coverage_main_dates
        EXCLUDE USING gist (org_id WITH =, site_id WITH =, daterange(valid_from, valid_until, '[]') WITH &&)
        WHERE (location_id IS NULL)""")
    op.execute("""ALTER TABLE customs_coverage ADD CONSTRAINT ex_customs_coverage_location_dates
        EXCLUDE USING gist (org_id WITH =, site_id WITH =, location_id WITH =,
            daterange(valid_from, valid_until, '[]') WITH &&) WHERE (location_id IS NOT NULL)""")


def downgrade():
    op.drop_table("customs_coverage")
    op.drop_table("customs_licences")
