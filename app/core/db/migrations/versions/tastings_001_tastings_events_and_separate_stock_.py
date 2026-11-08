"""Tastings events and separate stock ledger

Revision ID: tastings_001
Revises: cca_transfers_001
Create Date: 2026-10-26 21:39:33.085894

"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "tastings_001"
down_revision: Union[str, None] = "cca_transfers_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint("uq_crm_tasks_org_id", "crm_tasks", ["org_id", "id"])
    op.create_table(
        "tastings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("task_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("venue_name", sa.String(length=160), nullable=False),
        sa.Column("venue_address", sa.String(length=500), nullable=False),
        sa.Column("venue_type", sa.String(length=20), nullable=False),
        sa.Column("licence_reference", sa.String(length=160), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rep_id", sa.UUID(), nullable=False),
        sa.Column("contact_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("outcome_notes", sa.Text(), server_default="", nullable=False),
        sa.Column("dispatch_key", sa.String(length=100), nullable=True),
        sa.Column("dispatch_hash", sa.String(length=64), nullable=True),
        sa.Column("finalise_hash", sa.String(length=64), nullable=True),
        sa.Column("dispatched_on", sa.Date(), nullable=True),
        sa.Column("samples_count", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("dispatched_by", sa.UUID(), nullable=True),
        sa.Column("finalised_by", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.CheckConstraint("status IN ('planned','dispatched','completed','cancelled')", name="ck_tasting_status"),
        sa.CheckConstraint("venue_type IN ('own','external')", name="ck_tasting_venue"),
        sa.CheckConstraint("ends_at > starts_at", name="ck_tasting_times"),
        sa.ForeignKeyConstraint(["contact_id"], ["xero_contacts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["dispatched_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["finalised_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"]),
        sa.ForeignKeyConstraint(["rep_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["task_id"], ["crm_tasks.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "dispatch_key", name="uq_tastings_dispatch_key"),
        sa.UniqueConstraint("org_id", "id", name="uq_tastings_org_id"),
        sa.UniqueConstraint("task_id", name="uq_tastings_task"),
    )
    op.create_index(op.f("ix_tastings_org_id"), "tastings", ["org_id"], unique=False)
    op.create_index("ix_tastings_org_start", "tastings", ["org_id", "starts_at"], unique=False)
    op.create_table(
        "tasting_stock_lots",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tasting_id", sa.UUID(), nullable=False),
        sa.Column("source_item_id", sa.UUID(), nullable=False),
        sa.Column("purpose", sa.String(length=20), server_default="tasting", nullable=False),
        sa.Column("quantity", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("unit", sa.String(length=50), nullable=False),
        sa.Column("initial_volume_ml", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("remaining_volume_ml", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("reserved_volume_ml", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("removed_on", sa.Date(), nullable=False),
        sa.Column("creates_removal", sa.Integer(), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("recorded_by", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "initial_volume_ml > 0 AND remaining_volume_ml >= 0 AND reserved_volume_ml >= 0 AND remaining_volume_ml <= initial_volume_ml AND reserved_volume_ml <= remaining_volume_ml",
            name="ck_tasting_stock_conservation",
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "source_item_id"],
            ["inventory_items.org_id", "inventory_items.id"],
            name="fk_tasting_stock_source",
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "tasting_id"], ["tastings.org_id", "tastings.id"], name="fk_tasting_stock_event"
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"]),
        sa.ForeignKeyConstraint(["recorded_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "id", name="uq_tasting_stock_org_id"),
    )
    op.create_index(op.f("ix_tasting_stock_lots_org_id"), "tasting_stock_lots", ["org_id"], unique=False)
    op.create_index("ix_tasting_stock_org_removal", "tasting_stock_lots", ["org_id", "removed_on"], unique=False)
    op.create_table(
        "tasting_allocations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tasting_id", sa.UUID(), nullable=False),
        sa.Column("source_item_id", sa.UUID(), nullable=True),
        sa.Column("source_pool_id", sa.UUID(), nullable=True),
        sa.Column("stock_lot_id", sa.UUID(), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("reserved_volume_ml", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("used_volume_ml", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "(source_item_id IS NULL) <> (source_pool_id IS NULL)", name="ck_tasting_allocation_one_source"
        ),
        sa.CheckConstraint(
            "quantity > 0 AND reserved_volume_ml >= 0 AND used_volume_ml >= 0 AND used_volume_ml <= reserved_volume_ml",
            name="ck_tasting_allocation_amount",
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "source_item_id"],
            ["inventory_items.org_id", "inventory_items.id"],
            name="fk_tasting_allocation_source",
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "source_pool_id"],
            ["tasting_stock_lots.org_id", "tasting_stock_lots.id"],
            name="fk_tasting_allocation_pool",
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "stock_lot_id"],
            ["tasting_stock_lots.org_id", "tasting_stock_lots.id"],
            name="fk_tasting_allocation_dispatched_pool",
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "tasting_id"], ["tastings.org_id", "tastings.id"], name="fk_tasting_allocation_event"
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tasting_allocation_org_event", "tasting_allocations", ["org_id", "tasting_id"], unique=False)
    op.create_index(op.f("ix_tasting_allocations_org_id"), "tasting_allocations", ["org_id"], unique=False)

    op.create_foreign_key(
        "fk_tasting_org_task", "tastings", "crm_tasks", ["org_id", "task_id"], ["org_id", "id"], ondelete="RESTRICT"
    )
    op.execute("""
    CREATE FUNCTION protect_tasting_stock_basis() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF (to_jsonb(NEW) - 'remaining_volume_ml' - 'reserved_volume_ml')
            IS DISTINCT FROM (to_jsonb(OLD) - 'remaining_volume_ml' - 'reserved_volume_ml') THEN
            RAISE EXCEPTION 'Tasting removal evidence is immutable';
        END IF;
        RETURN NEW;
    END $$;
    CREATE TRIGGER tasting_stock_immutable BEFORE UPDATE ON tasting_stock_lots
        FOR EACH ROW EXECUTE FUNCTION protect_tasting_stock_basis();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS tasting_stock_immutable ON tasting_stock_lots")
    op.execute("DROP FUNCTION IF EXISTS protect_tasting_stock_basis()")
    op.drop_index("ix_tasting_allocation_org_event", table_name="tasting_allocations")
    op.drop_table("tasting_allocations")
    op.drop_index("ix_tasting_stock_org_removal", table_name="tasting_stock_lots")
    op.drop_table("tasting_stock_lots")
    op.drop_index("ix_tastings_org_start", table_name="tastings")
    op.drop_table("tastings")
    op.drop_constraint("uq_crm_tasks_org_id", "crm_tasks", type_="unique")
