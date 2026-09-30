"""Immutable customer enquiries to repeat completed contract orders."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "portal_reorders_001"
down_revision = "portal_messages_001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "contract_portal_reorders",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("order_id", UUID(as_uuid=True), nullable=False),
        sa.Column("customer_id", UUID(as_uuid=True), nullable=False),
        sa.Column("requested_by", UUID(as_uuid=True), nullable=False),
        sa.Column("note", sa.String(1000)),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["org_id", "order_id", "customer_id"],
            ["contract_orders.org_id", "contract_orders.id", "contract_orders.customer_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "customer_id", "requested_by"],
            [
                "contract_portal_principals.org_id",
                "contract_portal_principals.customer_id",
                "contract_portal_principals.id",
            ],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("org_id", "order_id", name="uq_portal_reorder_order"),
    )
    op.execute("""CREATE FUNCTION guard_portal_reorder_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'Portal reorder requests are immutable'; END $$""")
    op.execute("""CREATE TRIGGER trg_portal_reorder_immutable BEFORE UPDATE ON contract_portal_reorders
    FOR EACH ROW EXECUTE FUNCTION guard_portal_reorder_immutable()""")


def downgrade():
    op.drop_table("contract_portal_reorders")
    op.execute("DROP FUNCTION guard_portal_reorder_immutable()")
