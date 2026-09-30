"""Food registrations with explicit premises scope and isolated verification history."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "food_registrations_001"
down_revision = "site_licensing_001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "food_registrations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("reference", sa.String(100), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("programme", sa.String(10), nullable=False),
        sa.Column("registered_on", sa.Date(), nullable=False),
        sa.Column("registered_as", sa.String(10), nullable=False),
        sa.Column("valid_until", sa.Date()),
        sa.Column("evidence_reference", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("org_id", "id", name="uq_food_registration_org_id"),
        sa.UniqueConstraint("org_id", "reference", name="uq_food_registration_org_reference"),
        sa.CheckConstraint("programme IN ('np1','np2','np3','fcp')", name="ck_food_registration_programme"),
        sa.CheckConstraint("registered_as IN ('new','existing')", name="ck_food_registration_registered_as"),
        sa.CheckConstraint("valid_until IS NULL OR valid_until >= registered_on", name="ck_food_registration_dates"),
    )
    op.create_table(
        "food_registration_sites",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("registration_id", UUID(as_uuid=True), nullable=False),
        sa.Column("site_id", UUID(as_uuid=True), nullable=False),
        sa.Column("activity", sa.String(20), nullable=False),
        sa.Column("evidence_reference", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["org_id", "registration_id"],
            ["food_registrations.org_id", "food_registrations.id"],
            name="fk_food_registration_scope_registration",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "site_id"],
            ["sites.org_id", "sites.id"],
            name="fk_food_registration_scope_site",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("org_id", "registration_id", "site_id", "activity", name="uq_food_registration_scope"),
        sa.CheckConstraint("activity IN ('manufacturing','storage','selling')", name="ck_food_registration_activity"),
    )
    for table, fields in (
        ("food_registrations", ("org_id",)),
        ("food_registration_sites", ("org_id", "registration_id", "site_id")),
    ):
        for field in fields:
            op.create_index(f"ix_{table}_{field}", table, [field])
    op.add_column("compliance_verifications", sa.Column("food_registration_id", UUID(as_uuid=True)))
    op.create_index(
        "ix_compliance_verifications_food_registration_id", "compliance_verifications", ["food_registration_id"]
    )
    op.create_foreign_key(
        "fk_verification_food_registration",
        "compliance_verifications",
        "food_registrations",
        ["org_id", "food_registration_id"],
        ["org_id", "id"],
        ondelete="RESTRICT",
    )


def downgrade():
    op.drop_constraint("fk_verification_food_registration", "compliance_verifications", type_="foreignkey")
    op.drop_index("ix_compliance_verifications_food_registration_id", table_name="compliance_verifications")
    op.drop_column("compliance_verifications", "food_registration_id")
    op.drop_table("food_registration_sites")
    op.drop_table("food_registrations")
