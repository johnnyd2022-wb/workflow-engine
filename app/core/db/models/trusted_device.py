"""Trusted Device model for 2FA 'Remember this device' feature"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID

from app.core.db.models.models import Base


class TrustedDevice(Base):
    """Trusted Device model for storing device tokens that bypass 2FA

    When a user enables "Remember this device" during 2FA verification,
    a secure token is generated and stored. This token allows the user
    to skip 2FA on the same device for 30 days.
    """

    __tablename__ = "trusted_devices"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    device_token = Column(String(255), nullable=False, unique=True, index=True)  # Hashed token
    device_fingerprint = Column(String(255), nullable=False, index=True)  # Browser characteristics hash
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    last_used_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    def __repr__(self):
        return f"<TrustedDevice(id={self.id}, user_id={self.user_id}, expires_at={self.expires_at})>"

    def is_expired(self):
        """Check if the trusted device token has expired"""
        # Compare timezone-aware datetimes
        now = datetime.now(timezone.utc)
        # Ensure expires_at is timezone-aware (it should be from DB, but be safe)
        if self.expires_at.tzinfo is None:
            expires_at = self.expires_at.replace(tzinfo=timezone.utc)
        else:
            expires_at = self.expires_at
        return now > expires_at

    @staticmethod
    def get_expiration_date():
        """Get the expiration date for a new trusted device (30 days from now)"""
        return datetime.now(timezone.utc) + timedelta(days=30)
