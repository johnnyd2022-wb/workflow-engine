"""Add CRM and Xero integration tables

Revision ID: add_crm_xero_tables_001
Revises: event_sourcing_org_cascade_001
Create Date: 2026-05-14

Creates all tables required for the Xero OAuth2 integration and lightweight CRM:
  xero_tenants, xero_oauth_tokens, xero_contacts, xero_invoices,
  xero_invoice_line_items, xero_sync_jobs, product_mappings, crm_notes, crm_tasks
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "add_crm_xero_tables_001"
down_revision: Union[str, None] = "event_sourcing_org_cascade_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- xero_tenants ---
    op.create_table(
        "xero_tenants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("xero_tenant_id", sa.String(100), nullable=False),
        sa.Column("xero_tenant_name", sa.String(255), nullable=True),
        sa.Column("xero_tenant_type", sa.String(50), nullable=True),
        sa.Column("is_connected", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("connected_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("disconnected_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_successful_sync_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_xero_tenants_org_id", "xero_tenants", ["org_id"])
    op.create_unique_constraint("uq_xero_tenants_org_xero", "xero_tenants", ["org_id", "xero_tenant_id"])

    # --- xero_oauth_tokens ---
    op.create_table(
        "xero_oauth_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("xero_tenant_id", sa.String(100), nullable=False),
        sa.Column("access_token_encrypted", sa.Text, nullable=False),
        sa.Column("refresh_token_encrypted", sa.Text, nullable=False),
        sa.Column("token_type", sa.String(50), nullable=False, server_default="Bearer"),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("scopes", sa.Text, nullable=True),
        sa.Column("is_valid", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("last_refreshed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # --- xero_contacts ---
    op.create_table(
        "xero_contacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("xero_contact_id", sa.String(100), nullable=False),
        sa.Column("xero_tenant_id", sa.String(100), nullable=False),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("first_name", sa.String(255), nullable=True),
        sa.Column("last_name", sa.String(255), nullable=True),
        sa.Column("email_address", sa.String(255), nullable=True),
        sa.Column("phone_number", sa.String(50), nullable=True),
        sa.Column("addresses", postgresql.JSONB(), nullable=True),
        sa.Column("tax_number", sa.String(50), nullable=True),
        sa.Column("account_number", sa.String(50), nullable=True),
        sa.Column("contact_status", sa.String(50), nullable=True),
        sa.Column("is_customer", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("is_supplier", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("xero_updated_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_synced_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_xero_contacts_org_id", "xero_contacts", ["org_id"])
    op.create_index("ix_xero_contacts_org_name", "xero_contacts", ["org_id", "name"])
    op.create_index("ix_xero_contacts_org_email", "xero_contacts", ["org_id", "email_address"])
    op.create_unique_constraint("uq_xero_contacts_org_xero", "xero_contacts", ["org_id", "xero_contact_id"])

    # --- xero_invoices ---
    op.create_table(
        "xero_invoices",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("xero_invoice_id", sa.String(100), nullable=False),
        sa.Column("xero_tenant_id", sa.String(100), nullable=False),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("xero_contacts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("xero_contact_id", sa.String(100), nullable=True),
        sa.Column("invoice_number", sa.String(100), nullable=True),
        sa.Column("reference", sa.String(255), nullable=True),
        sa.Column("invoice_type", sa.String(20), nullable=True),
        sa.Column("status", sa.String(50), nullable=True),
        sa.Column("sub_total", sa.Numeric(18, 4), nullable=True),
        sa.Column("total_tax", sa.Numeric(18, 4), nullable=True),
        sa.Column("total", sa.Numeric(18, 4), nullable=True),
        sa.Column("amount_due", sa.Numeric(18, 4), nullable=True),
        sa.Column("amount_paid", sa.Numeric(18, 4), nullable=True),
        sa.Column("currency_code", sa.String(3), nullable=True, server_default="NZD"),
        sa.Column("date", sa.Date, nullable=True),
        sa.Column("due_date", sa.Date, nullable=True),
        sa.Column("fully_paid_on_date", sa.Date, nullable=True),
        sa.Column("xero_updated_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_synced_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_xero_invoices_org_id", "xero_invoices", ["org_id"])
    op.create_index("ix_xero_invoices_contact_id", "xero_invoices", ["contact_id"])
    op.create_index("ix_xero_invoices_org_status", "xero_invoices", ["org_id", "status"])
    op.create_index("ix_xero_invoices_org_date", "xero_invoices", ["org_id", "date"])
    op.create_unique_constraint("uq_xero_invoices_org_xero", "xero_invoices", ["org_id", "xero_invoice_id"])

    # --- xero_invoice_line_items ---
    op.create_table(
        "xero_invoice_line_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("invoice_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("xero_invoices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("xero_line_item_id", sa.String(100), nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("item_code", sa.String(100), nullable=True),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=True),
        sa.Column("unit_amount", sa.Numeric(18, 4), nullable=True),
        sa.Column("line_amount", sa.Numeric(18, 4), nullable=True),
        sa.Column("account_code", sa.String(50), nullable=True),
        sa.Column("tax_type", sa.String(50), nullable=True),
        sa.Column("tax_amount", sa.Numeric(18, 4), nullable=True),
        sa.Column("discount_rate", sa.Numeric(5, 2), nullable=True),
        sa.Column("tracking", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_xero_line_items_org_id", "xero_invoice_line_items", ["org_id"])
    op.create_index("ix_xero_line_items_invoice_id", "xero_invoice_line_items", ["invoice_id"])

    # --- xero_sync_jobs ---
    op.create_table(
        "xero_sync_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("xero_tenant_id", sa.String(100), nullable=False),
        sa.Column("sync_type", sa.String(50), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("contacts_synced", sa.Integer, nullable=False, server_default="0"),
        sa.Column("invoices_synced", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("error_details", postgresql.JSONB(), nullable=True),
        sa.Column("triggered_by", sa.String(50), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_xero_sync_jobs_org_id", "xero_sync_jobs", ["org_id"])
    op.create_index("ix_xero_sync_jobs_org_created", "xero_sync_jobs", ["org_id", "created_at"])

    # --- product_mappings ---
    op.create_table(
        "product_mappings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("biz_e_product_name", sa.String(500), nullable=False),
        sa.Column("xero_description_pattern", sa.String(500), nullable=False),
        sa.Column("match_type", sa.String(50), nullable=False, server_default="exact"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_product_mappings_org_id", "product_mappings", ["org_id"])
    op.create_unique_constraint(
        "uq_product_mappings_org_biz_xero",
        "product_mappings",
        ["org_id", "biz_e_product_name", "xero_description_pattern"],
    )

    # --- crm_notes ---
    op.create_table(
        "crm_notes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("xero_contacts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_crm_notes_org_id", "crm_notes", ["org_id"])
    op.create_index("ix_crm_notes_contact_id", "crm_notes", ["contact_id"])

    # --- crm_tasks ---
    op.create_table(
        "crm_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("xero_contacts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("due_date", sa.Date, nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("priority", sa.String(20), nullable=False, server_default="medium"),
        sa.Column("assigned_to_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_crm_tasks_org_id", "crm_tasks", ["org_id"])
    op.create_index("ix_crm_tasks_contact_id", "crm_tasks", ["contact_id"])
    op.create_index("ix_crm_tasks_org_due_date", "crm_tasks", ["org_id", "due_date"])
    op.create_index("ix_crm_tasks_org_assigned_status", "crm_tasks", ["org_id", "assigned_to_user_id", "status"])


def downgrade() -> None:
    op.drop_table("crm_tasks")
    op.drop_table("crm_notes")
    op.drop_table("product_mappings")
    op.drop_table("xero_sync_jobs")
    op.drop_table("xero_invoice_line_items")
    op.drop_table("xero_invoices")
    op.drop_table("xero_contacts")
    op.drop_table("xero_oauth_tokens")
    op.drop_table("xero_tenants")
