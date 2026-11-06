"""Quality hold and release on a lot (GL-P02).

`lot_holds`: one row per hold placed on an inventory lot, closed (never deleted) by a
release with a note. At most one open hold per lot. Downgrade refuses while any hold
exists, since that would lose the quality record.

Revision ID: lot_holds_001
Revises: supplier_lead_time_001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import UUID

revision = "lot_holds_001"
down_revision = "supplier_lead_time_001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "lot_holds",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("inventory_item_id", UUID(as_uuid=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "source_hold_id", UUID(as_uuid=True), sa.ForeignKey("lot_holds.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("placed_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("placed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("released_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("release_note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["org_id", "inventory_item_id"],
            ["inventory_items.org_id", "inventory_items.id"],
            name="fk_lot_hold_org_item",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("length(trim(reason)) > 0", name="ck_lot_hold_reason"),
        sa.CheckConstraint(
            "released_at IS NULL OR length(trim(coalesce(release_note, ''))) > 0", name="ck_lot_hold_release_note"
        ),
    )
    op.create_index("ix_lot_holds_org_id", "lot_holds", ["org_id"])
    op.create_index(
        "uq_lot_hold_open",
        "lot_holds",
        ["org_id", "inventory_item_id"],
        unique=True,
        postgresql_where=sa.text("released_at IS NULL"),
    )


def downgrade():
    if op.get_bind().execute(text("SELECT 1 FROM lot_holds LIMIT 1")).first():
        raise RuntimeError("Lots have quality holds recorded; downgrading would lose them")
    op.drop_table("lot_holds")
