"""Add the Compliant NZ Alcohol compliance data model.

Revision ID: compliant_nz_alcohol_001
Revises: tenant_org_id_notnull_001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "compliant_nz_alcohol_001"
down_revision: str | None = "tenant_org_id_notnull_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "compliance_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organisations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("industry_module", sa.String(80), nullable=False, server_default="nz_alcohol"),
        sa.Column("council_name", sa.String(255)),
        sa.Column("trade_waste_consent_reference", sa.String(255)),
        sa.Column("settings", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("org_id", name="uq_compliance_profiles_org"),
    )
    op.create_index("ix_compliance_profiles_org_enabled", "compliance_profiles", ["org_id", "enabled"])
    op.create_table(
        "compliance_alcohol_product_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organisations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("inventory_name", sa.String(255), nullable=False),
        sa.Column("product_type", sa.String(40), nullable=False),
        sa.Column("abv_percent", sa.Numeric(7, 4), nullable=False),
        sa.Column("customs_product_code", sa.String(100)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("org_id", "inventory_name", name="uq_compliance_alcohol_product_org_name"),
    )
    op.create_index(
        "ix_compliance_alcohol_product_org_type", "compliance_alcohol_product_profiles", ["org_id", "product_type"]
    )
    op.create_table(
        "compliance_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organisations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("framework_slug", sa.String(80), nullable=False),
        sa.Column("control_id", sa.String(160), nullable=False),
        sa.Column("record_type", sa.String(40), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="complete"),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("period_start", sa.Date()),
        sa.Column("period_end", sa.Date()),
        sa.Column("due_date", sa.Date()),
        sa.Column("measured_value", sa.Numeric(18, 4)),
        sa.Column("limit_value", sa.Numeric(18, 4)),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("evidence_reference", sa.String(1024)),
        sa.Column("source_refs", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("details", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_compliance_records_org_framework", "compliance_records", ["org_id", "framework_slug"])
    op.create_index("ix_compliance_records_org_control_due", "compliance_records", ["org_id", "control_id", "due_date"])
    op.create_table(
        "compliance_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organisations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("framework_slug", sa.String(80), nullable=False),
        sa.Column("period_start", sa.Date()),
        sa.Column("period_end", sa.Date()),
        sa.Column(
            "generated_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column("checksum_sha256", sa.String(64), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_compliance_reports_org_framework_created", "compliance_reports", ["org_id", "framework_slug", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_compliance_reports_org_framework_created", table_name="compliance_reports")
    op.drop_table("compliance_reports")
    op.drop_index("ix_compliance_records_org_control_due", table_name="compliance_records")
    op.drop_index("ix_compliance_records_org_framework", table_name="compliance_records")
    op.drop_table("compliance_records")
    op.drop_index("ix_compliance_alcohol_product_org_type", table_name="compliance_alcohol_product_profiles")
    op.drop_table("compliance_alcohol_product_profiles")
    op.drop_index("ix_compliance_profiles_org_enabled", table_name="compliance_profiles")
    op.drop_table("compliance_profiles")
