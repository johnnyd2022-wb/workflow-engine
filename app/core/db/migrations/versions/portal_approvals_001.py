"""Keep a tenant-scoped, one-time customer decision for a shared label proof."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "portal_approvals_001"
down_revision = "multiple_sites_001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_unique_constraint(
        "uq_portal_principal_customer_scope",
        "contract_portal_principals",
        ["org_id", "customer_id", "id"],
    )
    op.create_unique_constraint(
        "uq_portal_document_order_scope",
        "contract_portal_documents",
        ["org_id", "order_id", "customer_id", "id"],
    )
    op.create_table(
        "contract_portal_approvals",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("order_id", UUID(as_uuid=True), nullable=False),
        sa.Column("customer_id", UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", UUID(as_uuid=True), nullable=False),
        sa.Column("prompt", sa.String(500), nullable=False),
        sa.Column("requested_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("decision", sa.String(30)),
        sa.Column("response_note", sa.String(1000)),
        sa.Column("responded_by", UUID(as_uuid=True)),
        sa.Column("responded_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["org_id", "order_id", "customer_id"],
            ["contract_orders.org_id", "contract_orders.id", "contract_orders.customer_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "order_id", "customer_id", "document_id"],
            [
                "contract_portal_documents.org_id",
                "contract_portal_documents.order_id",
                "contract_portal_documents.customer_id",
                "contract_portal_documents.id",
            ],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "customer_id", "responded_by"],
            [
                "contract_portal_principals.org_id",
                "contract_portal_principals.customer_id",
                "contract_portal_principals.id",
            ],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("org_id", "order_id", "document_id", name="uq_portal_approval_document"),
        sa.CheckConstraint(
            "(decision IS NULL AND responded_by IS NULL AND responded_at IS NULL AND response_note IS NULL) OR "
            "(decision IN ('approved','changes_requested') AND responded_by IS NOT NULL AND responded_at IS NOT NULL)",
            name="ck_portal_approval_response",
        ),
    )
    op.create_index(
        "ix_portal_approvals_customer_order",
        "contract_portal_approvals",
        ["org_id", "customer_id", "order_id"],
    )
    op.execute(
        """CREATE FUNCTION guard_portal_approval_final() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF OLD.responded_at IS NOT NULL OR
             ROW(NEW.id,NEW.org_id,NEW.order_id,NEW.customer_id,NEW.document_id,NEW.prompt,NEW.requested_by,NEW.requested_at)
             IS DISTINCT FROM
             ROW(OLD.id,OLD.org_id,OLD.order_id,OLD.customer_id,OLD.document_id,OLD.prompt,OLD.requested_by,OLD.requested_at) THEN
            RAISE EXCEPTION 'Portal approval request or response is immutable';
          END IF;
          RETURN NEW;
        END $$"""
    )
    op.execute(
        """CREATE TRIGGER trg_portal_approval_final BEFORE UPDATE ON contract_portal_approvals
        FOR EACH ROW EXECUTE FUNCTION guard_portal_approval_final()"""
    )


def downgrade():
    op.execute("DROP TRIGGER trg_portal_approval_final ON contract_portal_approvals")
    op.execute("DROP FUNCTION guard_portal_approval_final()")
    op.drop_index("ix_portal_approvals_customer_order", table_name="contract_portal_approvals")
    op.drop_table("contract_portal_approvals")
    op.drop_constraint("uq_portal_principal_customer_scope", "contract_portal_principals", type_="unique")
    op.drop_constraint("uq_portal_document_order_scope", "contract_portal_documents", type_="unique")
