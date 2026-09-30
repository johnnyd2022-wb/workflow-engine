"""Customer portal identities and explicitly shared, immutable order snapshots."""

import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.db.models.models import Base
from app.core.db.models.tenant_mixin import TenantScoped
from app.core.utils.time import utc_now


class PortalPrincipal(TenantScoped, Base):
    __tablename__ = "contract_portal_principals"
    __table_args__ = (
        UniqueConstraint("org_id", "customer_id", "email", name="uq_portal_customer_email"),
        UniqueConstraint("org_id", "id", name="uq_portal_principal_org_id"),
        UniqueConstraint("org_id", "customer_id", "id", name="uq_portal_principal_customer_scope"),
        ForeignKeyConstraint(
            ["org_id", "customer_id"], ["contract_customers.org_id", "contract_customers.id"], ondelete="RESTRICT"
        ),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id = Column(UUID(as_uuid=True), nullable=False)
    email = Column(String(255), nullable=False)
    password_hash = Column(String(255), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    failed_attempts = Column(Integer, nullable=False, default=0)
    locked_until = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class PortalInvite(TenantScoped, Base):
    __tablename__ = "contract_portal_invites"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "customer_id"], ["contract_customers.org_id", "contract_customers.id"], ondelete="RESTRICT"
        ),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id = Column(UUID(as_uuid=True), nullable=False)
    email = Column(String(255), nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    consumed_at = Column(DateTime(timezone=True))
    revoked_at = Column(DateTime(timezone=True))
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class PortalSession(TenantScoped, Base):
    __tablename__ = "contract_portal_sessions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "principal_id"],
            ["contract_portal_principals.org_id", "contract_portal_principals.id"],
            ondelete="CASCADE",
        ),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    principal_id = Column(UUID(as_uuid=True), nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    last_seen_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    revoked_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class PortalPublication(TenantScoped, Base):
    __tablename__ = "contract_portal_publications"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "order_id", "customer_id"],
            ["contract_orders.org_id", "contract_orders.id", "contract_orders.customer_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["org_id", "customer_id"], ["contract_customers.org_id", "contract_customers.id"], ondelete="RESTRICT"
        ),
        UniqueConstraint("org_id", "order_id", "revision", name="uq_portal_order_revision"),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(UUID(as_uuid=True), nullable=False)
    customer_id = Column(UUID(as_uuid=True), nullable=False)
    revision = Column(Integer, nullable=False)
    payload = Column(JSONB, nullable=False)
    published_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    revoked_at = Column(DateTime(timezone=True))


class PortalDocument(TenantScoped, Base):
    __tablename__ = "contract_portal_documents"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "order_id", "customer_id"],
            ["contract_orders.org_id", "contract_orders.id", "contract_orders.customer_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["org_id", "customer_id"], ["contract_customers.org_id", "contract_customers.id"], ondelete="RESTRICT"
        ),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(UUID(as_uuid=True), nullable=False)
    customer_id = Column(UUID(as_uuid=True), nullable=False)
    title = Column(String(255), nullable=False)
    content_type = Column(String(100), nullable=False)
    content = Column(LargeBinary, nullable=False)
    sha256 = Column(String(64), nullable=False)
    uploaded_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    revoked_at = Column(DateTime(timezone=True))


class PortalApproval(TenantScoped, Base):
    """One customer decision on one explicitly shared document."""

    __tablename__ = "contract_portal_approvals"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "order_id", "customer_id"],
            ["contract_orders.org_id", "contract_orders.id", "contract_orders.customer_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["org_id", "order_id", "customer_id", "document_id"],
            [
                "contract_portal_documents.org_id",
                "contract_portal_documents.order_id",
                "contract_portal_documents.customer_id",
                "contract_portal_documents.id",
            ],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["org_id", "customer_id", "responded_by"],
            [
                "contract_portal_principals.org_id",
                "contract_portal_principals.customer_id",
                "contract_portal_principals.id",
            ],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("org_id", "order_id", "document_id", name="uq_portal_approval_document"),
        CheckConstraint(
            "(decision IS NULL AND responded_by IS NULL AND responded_at IS NULL AND response_note IS NULL) OR "
            "(decision IN ('approved','changes_requested') AND responded_by IS NOT NULL AND responded_at IS NOT NULL)",
            name="ck_portal_approval_response",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(UUID(as_uuid=True), nullable=False)
    customer_id = Column(UUID(as_uuid=True), nullable=False)
    document_id = Column(UUID(as_uuid=True), nullable=False)
    prompt = Column(String(500), nullable=False)
    requested_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    requested_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    decision = Column(String(30))
    response_note = Column(String(1000))
    responded_by = Column(UUID(as_uuid=True))
    responded_at = Column(DateTime(timezone=True))


class PortalMessage(TenantScoped, Base):
    """Append-only conversation entry on one published customer order."""

    __tablename__ = "contract_portal_messages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "order_id", "customer_id"],
            ["contract_orders.org_id", "contract_orders.id", "contract_orders.customer_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["org_id", "customer_id", "sender_portal_id"],
            [
                "contract_portal_principals.org_id",
                "contract_portal_principals.customer_id",
                "contract_portal_principals.id",
            ],
            ondelete="RESTRICT",
        ),
        CheckConstraint("(sender_staff_id IS NULL) <> (sender_portal_id IS NULL)", name="ck_portal_message_one_sender"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(UUID(as_uuid=True), nullable=False)
    customer_id = Column(UUID(as_uuid=True), nullable=False)
    sender_staff_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"))
    sender_portal_id = Column(UUID(as_uuid=True))
    body = Column(String(2000), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
