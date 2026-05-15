"""XeroOAuthToken — encrypted OAuth2 token set per Biz-e org (one active set)."""

import uuid
from datetime import datetime

from sqlalchemy import TIMESTAMP, Boolean, Column, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.core.db.models.models import Base


class XeroOAuthToken(Base):
    __tablename__ = "xero_oauth_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # One active token set per org — UNIQUE enforced at DB level
    org_id = Column(UUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, unique=True)
    xero_tenant_id = Column(String(100), nullable=False)
    # Fernet-encrypted — never store plaintext
    access_token_encrypted = Column(Text, nullable=False)
    refresh_token_encrypted = Column(Text, nullable=False)
    token_type = Column(String(50), nullable=False, default="Bearer")
    expires_at = Column(TIMESTAMP(timezone=True), nullable=False)
    scopes = Column(Text, nullable=True)
    is_valid = Column(Boolean, nullable=False, default=True)
    last_refreshed_at = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<XeroOAuthToken(id={self.id}, org_id={self.org_id}, valid={self.is_valid})>"
