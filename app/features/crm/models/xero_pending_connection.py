from sqlalchemy import TIMESTAMP, Column, ForeignKeyConstraint, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.db.models.models import Base
from app.core.db.models.tenant_mixin import TenantScoped


class XeroPendingConnection(TenantScoped, Base):
    __tablename__ = "xero_pending_connections"
    __table_args__ = (
        UniqueConstraint("org_id", name="uq_xero_pending_connections_org"),
        ForeignKeyConstraint(
            ["org_id", "user_id"],
            ["users.org_id", "users.id"],
            name="fk_xero_pending_connections_user",
            ondelete="CASCADE",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    connections = Column(JSONB, nullable=False)
    credentials_encrypted = Column(Text, nullable=False)
    token_expires_at = Column(TIMESTAMP(timezone=True), nullable=False)
    expires_at = Column(TIMESTAMP(timezone=True), nullable=False)
