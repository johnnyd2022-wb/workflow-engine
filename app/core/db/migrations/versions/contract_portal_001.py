"""Separate portal principals, one-use invitations, sessions and immutable sharing.

No staff users are created. No existing orders are automatically published.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "contract_portal_001"
down_revision = "contract_orders_001"
branch_labels = None
depends_on = None


def _identity():
    return [
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False),
    ]


def _created():
    return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def _customer():
    return sa.ForeignKeyConstraint(
        ["org_id", "customer_id"], ["contract_customers.org_id", "contract_customers.id"], ondelete="RESTRICT"
    )


def _order_customer():
    return sa.ForeignKeyConstraint(
        ["org_id", "order_id", "customer_id"],
        ["contract_orders.org_id", "contract_orders.id", "contract_orders.customer_id"],
        ondelete="RESTRICT",
    )


def _actor(name):
    return sa.Column(name, UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)


def upgrade():
    op.create_unique_constraint("uq_contract_order_customer_scope", "contract_orders", ["org_id", "id", "customer_id"])
    op.create_table(
        "contract_portal_principals",
        *_identity(),
        sa.Column("customer_id", UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("failed_attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
        _created(),
        _customer(),
        sa.UniqueConstraint("org_id", "customer_id", "email", name="uq_portal_customer_email"),
        sa.UniqueConstraint("org_id", "id", name="uq_portal_principal_org_id"),
    )
    op.create_table(
        "contract_portal_invites",
        *_identity(),
        sa.Column("customer_id", UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        _actor("created_by"),
        _created(),
        _customer(),
    )
    op.create_table(
        "contract_portal_sessions",
        *_identity(),
        sa.Column("principal_id", UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        _created(),
        sa.ForeignKeyConstraint(
            ["org_id", "principal_id"],
            ["contract_portal_principals.org_id", "contract_portal_principals.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_table(
        "contract_portal_publications",
        *_identity(),
        sa.Column("order_id", UUID(as_uuid=True), nullable=False),
        sa.Column("customer_id", UUID(as_uuid=True), nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        _actor("published_by"),
        _created(),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        _customer(),
        _order_customer(),
        sa.UniqueConstraint("org_id", "order_id", "revision", name="uq_portal_order_revision"),
    )
    op.create_table(
        "contract_portal_documents",
        *_identity(),
        sa.Column("order_id", UUID(as_uuid=True), nullable=False),
        sa.Column("customer_id", UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("content", sa.LargeBinary, nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        _actor("uploaded_by"),
        _created(),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        _customer(),
        _order_customer(),
    )
    for table in (
        "contract_portal_principals",
        "contract_portal_invites",
        "contract_portal_sessions",
        "contract_portal_publications",
        "contract_portal_documents",
    ):
        op.create_index(f"ix_{table}_org_id", table, ["org_id"])
    op.create_index(
        "ix_portal_publication_scope", "contract_portal_publications", ["org_id", "customer_id", "order_id", "revision"]
    )
    op.create_index("ix_portal_invite_email", "contract_portal_invites", ["org_id", "customer_id", "email"])
    op.create_index("ix_portal_sessions_principal", "contract_portal_sessions", ["org_id", "principal_id"])
    op.execute(
        """CREATE FUNCTION guard_contract_portal_publications_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF ROW(NEW.id,NEW.org_id,NEW.order_id,NEW.customer_id,NEW.revision,NEW.payload,NEW.published_by,NEW.created_at) IS DISTINCT FROM ROW(OLD.id,OLD.org_id,OLD.order_id,OLD.customer_id,OLD.revision,OLD.payload,OLD.published_by,OLD.created_at) THEN
            RAISE EXCEPTION 'Published portal facts are immutable; create a new revision';
          END IF;
          RETURN NEW;
        END $$"""
    )
    op.execute(
        "CREATE TRIGGER immutable_portal_facts BEFORE UPDATE ON contract_portal_publications FOR EACH ROW EXECUTE FUNCTION guard_contract_portal_publications_immutable()"
    )
    op.execute(
        """CREATE FUNCTION guard_contract_portal_documents_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF ROW(NEW.id,NEW.org_id,NEW.order_id,NEW.customer_id,NEW.title,NEW.content_type,NEW.content,NEW.sha256,NEW.uploaded_by,NEW.created_at) IS DISTINCT FROM ROW(OLD.id,OLD.org_id,OLD.order_id,OLD.customer_id,OLD.title,OLD.content_type,OLD.content,OLD.sha256,OLD.uploaded_by,OLD.created_at) THEN
            RAISE EXCEPTION 'Published portal facts are immutable; create a new revision';
          END IF;
          RETURN NEW;
        END $$"""
    )
    op.execute(
        "CREATE TRIGGER immutable_portal_facts BEFORE UPDATE ON contract_portal_documents FOR EACH ROW EXECUTE FUNCTION guard_contract_portal_documents_immutable()"
    )


def downgrade():
    for table in (
        "contract_portal_documents",
        "contract_portal_publications",
        "contract_portal_sessions",
        "contract_portal_invites",
        "contract_portal_principals",
    ):
        op.drop_table(table)
    op.execute("DROP FUNCTION guard_contract_portal_documents_immutable()")
    op.execute("DROP FUNCTION guard_contract_portal_publications_immutable()")
    op.drop_constraint("uq_contract_order_customer_scope", "contract_orders", type_="unique")
