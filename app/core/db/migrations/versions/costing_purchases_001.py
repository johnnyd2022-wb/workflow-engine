"""Xero purchases in (roadmap 8.1b, spec .agents/specs/live-cogs.md).

`xero_accounts` (Xero's chart of accounts, cached), `purchase_documents` and `purchase_lines`
(spend synced from Xero, in base currency excluding GST), and `xero_sync_jobs.purchases_synced`.
Additive: nothing existing changes except the one new column, which defaults to 0. Lines go with
their document (ON DELETE CASCADE). Everything but a line's decision columns is a re-syncable copy
of Xero, so the downgrade drops the tables, but refuses while a line carries a decision made in
Biz-E (its state, a not-stock part, a hand-set treatment): those can't be fetched again.

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
TIMESTAMPTZ = sa.DateTime(timezone=True)


def upgrade():
    op.create_table(
        "xero_accounts",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("org_id", UUID, sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("xero_account_id", sa.String(100), nullable=False),
        sa.Column("code", sa.String(50), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("type", sa.String(50), nullable=True),
        sa.Column("account_class", sa.String(20), nullable=True),
        sa.Column("status", sa.String(20), nullable=True),
        sa.Column("default_treatment", sa.String(20), nullable=True),
        sa.Column("last_synced_at", TIMESTAMPTZ, nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", TIMESTAMPTZ, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TIMESTAMPTZ, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("org_id", "id", name="uq_xero_accounts_org_id"),
        sa.UniqueConstraint("org_id", "xero_account_id", name="uq_xero_accounts_org_xero_account"),
        sa.CheckConstraint(
            "default_treatment IS NULL OR default_treatment IN ('stock','not_stock','duty','overhead')",
            name="ck_xero_accounts_default_treatment",
        ),
    )
    op.create_index("ix_xero_accounts_org_id", "xero_accounts", ["org_id"])
    op.create_index("ix_xero_accounts_org_code", "xero_accounts", ["org_id", "code"])

    op.create_table(
        "purchase_documents",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("org_id", UUID, sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("external_id", sa.String(100), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("payee_name", sa.String(255), nullable=True),
        sa.Column("xero_contact_id", sa.String(100), nullable=True),
        sa.Column("document_date", sa.Date(), nullable=False),
        sa.Column("reference", sa.String(255), nullable=True),
        sa.Column("currency_code", sa.String(3), nullable=False, server_default="NZD"),
        sa.Column("currency_rate", sa.Numeric(18, 8), nullable=False, server_default="1"),
        sa.Column("status", sa.String(10), nullable=False, server_default="active"),
        sa.Column("total_ex_tax", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("total_tax", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("external_updated_at", TIMESTAMPTZ, nullable=True),
        sa.Column("last_synced_at", TIMESTAMPTZ, nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", TIMESTAMPTZ, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TIMESTAMPTZ, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("org_id", "id", name="uq_purchase_documents_org_id"),
        sa.UniqueConstraint("org_id", "source", "external_id", name="uq_purchase_documents_source_external"),
        sa.CheckConstraint(
            "source IN ('xero_bank','xero_bill','xero_bill_credit','manual')", name="ck_purchase_documents_source"
        ),
        sa.CheckConstraint("kind IN ('spend','refund','bill','credit')", name="ck_purchase_documents_kind"),
        sa.CheckConstraint("status IN ('active','voided')", name="ck_purchase_documents_status"),
    )
    op.create_index("ix_purchase_documents_org_id", "purchase_documents", ["org_id"])
    op.create_index("ix_purchase_documents_org_date", "purchase_documents", ["org_id", "document_date"])

    op.create_table(
        "purchase_lines",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("org_id", UUID, sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("document_id", UUID, nullable=False),
        sa.Column("line_key", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("item_code", sa.String(100), nullable=True),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=True),
        sa.Column("unit_amount", sa.Numeric(18, 6), nullable=True),
        sa.Column("account_code", sa.String(50), nullable=True),
        sa.Column("account_name", sa.String(255), nullable=True),
        sa.Column("amount_ex_tax", sa.Numeric(18, 4), nullable=False),
        sa.Column("tax_amount", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("treatment", sa.String(20), nullable=False),
        sa.Column("treatment_rule_id", UUID, nullable=True),
        sa.Column("treatment_override", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("state", sa.String(20), nullable=False, server_default="open"),
        sa.Column("not_stock_amount", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("review_reason", sa.String(20), nullable=True),
        sa.Column("superseded_at", TIMESTAMPTZ, nullable=True),
        sa.Column("created_at", TIMESTAMPTZ, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TIMESTAMPTZ, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("org_id", "id", name="uq_purchase_lines_org_id"),
        sa.UniqueConstraint("org_id", "document_id", "line_key", name="uq_purchase_lines_document_key"),
        sa.ForeignKeyConstraint(
            ["org_id", "document_id"],
            ["purchase_documents.org_id", "purchase_documents.id"],
            name="fk_purchase_lines_document",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("treatment IN ('stock','not_stock','duty','overhead')", name="ck_purchase_lines_treatment"),
        sa.CheckConstraint(
            "state IN ('open','partly_recorded','recorded','skipped','not_stock')", name="ck_purchase_lines_state"
        ),
        sa.CheckConstraint(
            "review_reason IS NULL OR review_reason IN ('amount_changed','recoded','deleted_in_xero')",
            name="ck_purchase_lines_review_reason",
        ),
        sa.CheckConstraint(
            "abs(not_stock_amount) <= abs(amount_ex_tax) AND not_stock_amount * amount_ex_tax >= 0",
            name="ck_purchase_lines_not_stock_within_amount",
        ),
    )
    op.create_index("ix_purchase_lines_org_id", "purchase_lines", ["org_id"])
    op.create_index("ix_purchase_lines_document", "purchase_lines", ["org_id", "document_id"])
    op.create_index("ix_purchase_lines_org_treatment_state", "purchase_lines", ["org_id", "treatment", "state"])

    op.add_column("xero_sync_jobs", sa.Column("purchases_synced", sa.Integer(), nullable=False, server_default="0"))


def downgrade():
    decided = (
        op.get_bind()
        .execute(
            text(
                "SELECT 1 FROM purchase_lines WHERE state <> 'open' OR treatment_override"
                " OR not_stock_amount <> 0 LIMIT 1"
            )
        )
        .first()
    )
    if decided:
        raise RuntimeError("Purchase lines carry decisions made in Biz-E; downgrading would lose them")
    op.drop_column("xero_sync_jobs", "purchases_synced")
    op.drop_index("ix_purchase_lines_org_treatment_state", table_name="purchase_lines")
    op.drop_index("ix_purchase_lines_document", table_name="purchase_lines")
    op.drop_index("ix_purchase_lines_org_id", table_name="purchase_lines")
    op.drop_table("purchase_lines")
    op.drop_index("ix_purchase_documents_org_date", table_name="purchase_documents")
    op.drop_index("ix_purchase_documents_org_id", table_name="purchase_documents")
    op.drop_table("purchase_documents")
    op.drop_index("ix_xero_accounts_org_code", table_name="xero_accounts")
    op.drop_index("ix_xero_accounts_org_id", table_name="xero_accounts")
    op.drop_table("xero_accounts")
