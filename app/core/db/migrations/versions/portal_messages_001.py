"""Append-only customer/producer messages on a published contract order."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "portal_messages_001"
down_revision = "google_identities_001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "contract_portal_messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("order_id", UUID(as_uuid=True), nullable=False),
        sa.Column("customer_id", UUID(as_uuid=True), nullable=False),
        sa.Column("sender_staff_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT")),
        sa.Column("sender_portal_id", UUID(as_uuid=True)),
        sa.Column("body", sa.String(2000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["org_id", "order_id", "customer_id"],
            ["contract_orders.org_id", "contract_orders.id", "contract_orders.customer_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "customer_id", "sender_portal_id"],
            [
                "contract_portal_principals.org_id",
                "contract_portal_principals.customer_id",
                "contract_portal_principals.id",
            ],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "(sender_staff_id IS NULL) <> (sender_portal_id IS NULL)", name="ck_portal_message_one_sender"
        ),
    )
    op.create_index(
        "ix_portal_messages_order_time",
        "contract_portal_messages",
        ["org_id", "customer_id", "order_id", "created_at", "id"],
    )
    op.execute(
        """CREATE FUNCTION guard_portal_message_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'Portal messages are append-only';
        END $$"""
    )
    op.execute(
        """CREATE TRIGGER trg_portal_message_immutable BEFORE UPDATE ON contract_portal_messages
        FOR EACH ROW EXECUTE FUNCTION guard_portal_message_immutable()"""
    )


def downgrade():
    op.execute("DROP TRIGGER trg_portal_message_immutable ON contract_portal_messages")
    op.execute("DROP FUNCTION guard_portal_message_immutable()")
    op.drop_index("ix_portal_messages_order_time", table_name="contract_portal_messages")
    op.drop_table("contract_portal_messages")
