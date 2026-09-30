"""External identity bindings; Google subjects never move between local accounts."""

import uuid

from sqlalchemy import Column, DateTime, ForeignKeyConstraint, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.core.db.models.models import Base
from app.core.db.models.tenant_mixin import TenantScoped
from app.core.utils.time import utc_now


class UserIdentity(TenantScoped, Base):
    __tablename__ = "user_identities"
    __table_args__ = (
        UniqueConstraint("provider", "subject", name="uq_user_identity_provider_subject"),
        UniqueConstraint("org_id", "user_id", "provider", name="uq_user_identity_user_provider"),
        ForeignKeyConstraint(
            ["org_id", "user_id"], ["users.org_id", "users.id"], ondelete="CASCADE", name="fk_user_identity_account"
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    provider = Column(String(20), nullable=False)
    subject = Column(String(255), nullable=False)
    email_at_link = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
