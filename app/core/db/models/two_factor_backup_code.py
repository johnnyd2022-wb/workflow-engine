"""Two-factor authentication backup code model"""

import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID

from app.core.db.models.models import Base
from app.core.utils.time import utc_now


class TwoFactorBackupCode(Base):
    """Model for storing encrypted 2FA backup codes"""

    __tablename__ = "two_factor_backup_codes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    encrypted_code = Column(String, nullable=False)  # Encrypted backup code
    consumed = Column(Boolean, default=False, nullable=False)  # One-time use flag
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    def __repr__(self):
        return f"<TwoFactorBackupCode(id={self.id}, user_id={self.user_id}, consumed={self.consumed})>"
