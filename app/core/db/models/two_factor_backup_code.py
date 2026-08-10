"""Two-factor authentication backup code model"""

import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID

from app.core.db.models.models import Base
from app.core.db.models.tenant_mixin import TenantScoped
from app.core.utils.time import utc_now


class TwoFactorBackupCode(TenantScoped, Base):
    """Model for storing encrypted 2FA backup codes.

    org_id is denormalized here (backfilled from user.org_id by migration
    tenant_org_id_backfill_001) -- see Step's docstring / tenant_org_id_add_001 for why.
    """

    __tablename__ = "two_factor_backup_codes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    encrypted_code = Column(String, nullable=False)  # Encrypted backup code
    consumed = Column(Boolean, default=False, nullable=False)  # One-time use flag
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    def __repr__(self):
        return f"<TwoFactorBackupCode(id={self.id}, user_id={self.user_id}, consumed={self.consumed})>"
