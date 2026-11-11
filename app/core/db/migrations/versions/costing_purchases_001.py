"""Xero purchases in (roadmap 8.1b, spec .agents/specs/live-cogs.md "8.1b build contract").

`xero_accounts` (chart of accounts cache with a person-set treatment override),
`purchase_documents` / `purchase_lines` (Xero spend and receive money, ex GST, base currency),
`costing_settings.start_date` / `purchases_cursor`, and the purchases counters on
`xero_sync_jobs`. Additive. Downgrade refuses while an account override is recorded (a person's
decision with no other copy); purchase rows are re-fetchable from Xero.

Revision ID: costing_purchases_001
Revises: costing_engine_001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

revision = "costing_purchases_001"
down_revision = "costing_engine_001"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)
TS = sa.DateTime(timezone=True)


def upgrade():
    op.create_table(
        "xero_accounts",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("org_id", UUID, sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("xero_account_id", sa.String(100), nullable=False),
        sa.Column("code", sa.String(50), nullable=True),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("type", sa.String(50), nullable=True),
        sa.Column("account_class", sa.String(50), nullable=True),
        sa.Column("status", sa.String(50), nullable=True),
        sa.Column("default_treatment", sa.String(20), nullable=True),
        sa.Column("treatment_override", sa.String(20), nullable=True),
        sa.Column("last_synced_at", TS, nullable=True),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("org_id", "id", name="uq_xero_accounts_org_id"),
        sa.UniqueConstraint("org_id", "xero_account_id", name="uq_xero_accounts_org_xero"),
        sa.CheckConstraint(
            "treatment_override IS NULL OR treatment_override IN ('stock','not_stock','duty','overhead')",
            name="ck_xero_accounts_override",
        ),
    )
    op.create_table(
        "purchase_documents",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("org_id", UUID, sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("external_id", sa.String(100), nullable=False),
        sa.Column("xero_tenant_id", sa.String(100), nullable=True),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("payee_name", sa.String(255), nullable=True),
        sa.Column("xero_contact_id", sa.String(100), nullable=True),
        sa.Column("document_date", sa.Date(), nullable=True),
        sa.Column("reference", sa.String(255), nullable=True),
        sa.Column("currency_code", sa.String(3), nullable=True),
        sa.Column("currency_rate", sa.Numeric(18, 8), nullable=True),
        sa.Column("fx_status", sa.String(12), nullable=False, server_default="ok"),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("total_ex_tax", sa.Numeric(18, 4), nullable=True),
        sa.Column("total_tax", sa.Numeric(18, 4), nullable=True),
        sa.Column("bank_account_name", sa.String(255), nullable=True),
        sa.Column("is_reconciled", sa.Boolean(), nullable=True),
        sa.Column("external_updated_at", TS, nullable=True),
        sa.Column("last_synced_at", TS, nullable=True),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("org_id", "id", name="uq_purchase_documents_org_id"),
        sa.UniqueConstraint("org_id", "source", "external_id", name="uq_purchase_documents_external"),
        sa.CheckConstraint("source IN ('xero_bank')", name="ck_purchase_documents_source"),
        sa.CheckConstraint("kind IN ('spend','refund')", name="ck_purchase_documents_kind"),
        sa.CheckConstraint("status IN ('active','voided')", name="ck_purchase_documents_status"),
        sa.CheckConstraint("fx_status IN ('ok','needs_rate')", name="ck_purchase_documents_fx"),
    )
    op.create_index("ix_purchase_documents_org_date", "purchase_documents", ["org_id", "document_date"])
    op.create_table(
        "purchase_lines",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("org_id", UUID, sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("document_id", UUID, nullable=False),
        sa.Column("account_id", UUID, nullable=False),
        sa.Column("line_key", sa.String(120), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("description", sa.String(4000), nullable=True),
        sa.Column("item_code", sa.String(100), nullable=True),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=True),
        sa.Column("source_unit_amount", sa.Numeric(18, 4), nullable=True),
        sa.Column("account_code", sa.String(50), nullable=True),
        sa.Column("account_name", sa.String(255), nullable=True),
        sa.Column("amount_ex_tax", sa.Numeric(18, 4), nullable=True),
        sa.Column("tax_amount", sa.Numeric(18, 4), nullable=True),
        sa.Column("treatment", sa.String(20), nullable=False),
        sa.Column("superseded_at", TS, nullable=True),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("org_id", "id", name="uq_purchase_lines_org_id"),
        sa.ForeignKeyConstraint(
            ["org_id", "document_id"],
            ["purchase_documents.org_id", "purchase_documents.id"],
            name="fk_purchase_lines_document",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "account_id"], ["xero_accounts.org_id", "xero_accounts.id"], name="fk_purchase_lines_account"
        ),
        sa.CheckConstraint(
            "treatment IN ('stock','not_stock','duty','overhead')", name="ck_purchase_lines_treatment"
        ),
    )
    op.create_index(
        "uq_purchase_lines_live_key",
        "purchase_lines",
        ["org_id", "document_id", "line_key"],
        unique=True,
        postgresql_where=sa.text("superseded_at IS NULL"),
    )
    op.create_index("ix_purchase_lines_org_account", "purchase_lines", ["org_id", "account_id"])
    op.add_column("costing_settings", sa.Column("start_date", sa.Date(), nullable=True))
    op.add_column("costing_settings", sa.Column("purchases_cursor", TS, nullable=True))
    op.add_column("costing_settings", sa.Column("purchases_tenant_id", sa.String(100), nullable=True))
    op.add_column("costing_settings", sa.Column("base_currency", sa.String(3), nullable=True))
    op.add_column(
        "xero_sync_jobs", sa.Column("purchases_synced", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column("xero_sync_jobs", sa.Column("purchases_status", sa.String(20), nullable=True))


def downgrade():
    if op.get_bind().execute(text("SELECT 1 FROM xero_accounts WHERE treatment_override IS NOT NULL LIMIT 1")).first():
        raise RuntimeError("Account treatments have been set by people; downgrading would lose them")
    op.drop_column("xero_sync_jobs", "purchases_status")
    op.drop_column("xero_sync_jobs", "purchases_synced")
    op.drop_column("costing_settings", "base_currency")
    op.drop_column("costing_settings", "purchases_tenant_id")
    op.drop_column("costing_settings", "purchases_cursor")
    op.drop_column("costing_settings", "start_date")
    op.drop_index("ix_purchase_lines_org_account", table_name="purchase_lines")
    op.drop_index("uq_purchase_lines_live_key", table_name="purchase_lines")
    op.drop_table("purchase_lines")
    op.drop_index("ix_purchase_documents_org_date", table_name="purchase_documents")
    op.drop_table("purchase_documents")
    op.drop_table("xero_accounts")
