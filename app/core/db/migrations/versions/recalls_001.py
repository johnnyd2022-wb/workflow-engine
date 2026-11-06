"""Product recall cases (GL-P03).

`recalls` (one per recall operational case: the lot, reason, risk, drill flag, scope and the
holds it placed) and `recall_contacts` (each customer reached: supplied, notice sent outside
Biz-E, acknowledgement, recovered and disposed quantities). Downgrade refuses while any recall
exists.

Revision ID: recalls_001
Revises: xero_credit_notes_001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "recalls_001"
down_revision = "xero_credit_notes_001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "recalls",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("case_id", UUID(as_uuid=True), nullable=False),
        sa.Column("root_lot_id", UUID(as_uuid=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("risk", sa.String(20), nullable=False),
        sa.Column("is_drill", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("scope_lots", JSONB, nullable=False, server_default="[]"),
        sa.Column("hold_ids", JSONB, nullable=False, server_default="[]"),
        sa.Column("opened_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("org_id", "id", name="uq_recalls_org_id"),
        sa.UniqueConstraint("org_id", "case_id", name="uq_recalls_org_case"),
        sa.ForeignKeyConstraint(
            ["org_id", "case_id"],
            ["operational_cases.org_id", "operational_cases.id"],
            name="fk_recall_org_case",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "root_lot_id"],
            ["inventory_items.org_id", "inventory_items.id"],
            name="fk_recall_org_lot",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("risk IN ('health', 'quality', 'regulatory')", name="ck_recall_risk"),
        sa.CheckConstraint("length(trim(reason)) > 0", name="ck_recall_reason"),
    )
    op.create_index("ix_recalls_org_id", "recalls", ["org_id"])
    op.create_table(
        "recall_contacts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("recall_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "contact_id", UUID(as_uuid=True), sa.ForeignKey("xero_contacts.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("customer_name", sa.String(255), nullable=False),
        sa.Column("product_name", sa.String(500), nullable=False),
        sa.Column("unit", sa.String(50), nullable=False),
        sa.Column("quantity_supplied", sa.Numeric(18, 4), nullable=False),
        sa.Column("invoices", JSONB, nullable=False, server_default="[]"),
        sa.Column("notice_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notice_channel", sa.String(100), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_by", sa.String(255), nullable=True),
        sa.Column("ack_note", sa.Text(), nullable=True),
        sa.Column("unreachable_note", sa.Text(), nullable=True),
        sa.Column("recovered_qty", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("disposed_qty", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("unrecoverable_qty", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("updated_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("org_id", "id", name="uq_recall_contacts_org_id"),
        sa.ForeignKeyConstraint(
            ["org_id", "recall_id"],
            ["recalls.org_id", "recalls.id"],
            name="fk_recall_contact_org_recall",
            ondelete="CASCADE",
        ),
        # Postgres NUMERIC accepts NaN and sorts it above every number, so "> 0" alone lets it in.
        sa.CheckConstraint(
            "quantity_supplied <> 'NaN'::numeric AND recovered_qty <> 'NaN'::numeric AND disposed_qty <> 'NaN'::numeric AND unrecoverable_qty <> 'NaN'::numeric",
            name="ck_recall_contact_finite",
        ),
        sa.CheckConstraint("quantity_supplied > 0", name="ck_recall_contact_supplied"),
        # Only a customer recorded as unreachable can have stock written off as not recoverable.
        sa.CheckConstraint(
            "unrecoverable_qty = 0 OR unreachable_note IS NOT NULL",
            name="ck_recall_contact_unrecoverable_needs_unreachable",
        ),
        sa.CheckConstraint(
            "recovered_qty >= 0 AND disposed_qty >= 0 AND unrecoverable_qty >= 0 AND recovered_qty + disposed_qty + unrecoverable_qty <= quantity_supplied",
            name="ck_recall_contact_accounted",
        ),
    )
    op.create_index("ix_recall_contacts_org_id", "recall_contacts", ["org_id"])
    op.create_index("ix_recall_contacts_recall_id", "recall_contacts", ["recall_id"])


def downgrade():
    if op.get_bind().execute(text("SELECT 1 FROM recalls LIMIT 1")).first():
        raise RuntimeError("Recalls are recorded; downgrading would lose them")
    op.drop_table("recall_contacts")
    op.drop_table("recalls")
