"""Contract goods leaving the CCA: dispatches and their lines (GL-P08 part 2)."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "contract_dispatch_001"
down_revision = "tastings_tasks_002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "contract_dispatches",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("order_id", UUID(as_uuid=True), nullable=False),
        sa.Column("treatment", sa.String(20), nullable=False),
        sa.Column("destination_name", sa.String(255), nullable=False),
        sa.Column("destination_cca", sa.String(255)),
        sa.Column("moved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("carrier", sa.String(200), nullable=False),
        sa.Column("consignment_note", sa.String(200)),
        sa.Column("received_on", sa.Date()),
        sa.Column("receipt_reference", sa.String(500)),
        sa.Column("recorded_by_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["org_id", "order_id"],
            ["contract_orders.org_id", "contract_orders.id"],
            name="fk_contract_dispatch_order",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("treatment IN ('cca_transfer','removal')", name="ck_contract_dispatch_treatment"),
        sa.CheckConstraint(
            "treatment = 'removal' OR (destination_cca IS NOT NULL AND length(trim(destination_cca)) > 0)",
            name="ck_contract_dispatch_destination",
        ),
        sa.CheckConstraint(
            "received_on IS NULL OR (treatment = 'cca_transfer' AND receipt_reference IS NOT NULL)",
            name="ck_contract_dispatch_receipt",
        ),
    )
    op.create_index("ix_contract_dispatches_org_id", "contract_dispatches", ["org_id"])
    op.create_index("ix_contract_dispatches_order_id", "contract_dispatches", ["order_id"])
    op.create_table(
        "contract_dispatch_lines",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column(
            "dispatch_id",
            UUID(as_uuid=True),
            sa.ForeignKey("contract_dispatches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("inventory_item_id", UUID(as_uuid=True), nullable=False),
        sa.Column("product_name", sa.String(255), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("unit", sa.String(50), nullable=False),
        sa.ForeignKeyConstraint(
            ["org_id", "inventory_item_id"],
            ["inventory_items.org_id", "inventory_items.id"],
            name="fk_contract_dispatch_line_item",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("quantity > 0", name="ck_contract_dispatch_line_quantity"),
    )
    op.create_index("ix_contract_dispatch_lines_org_id", "contract_dispatch_lines", ["org_id"])
    op.create_index("ix_contract_dispatch_lines_dispatch_id", "contract_dispatch_lines", ["dispatch_id"])
    op.create_index("ix_contract_dispatch_lines_inventory_item_id", "contract_dispatch_lines", ["inventory_item_id"])


def downgrade():
    op.drop_table("contract_dispatch_lines")
    op.drop_table("contract_dispatches")
