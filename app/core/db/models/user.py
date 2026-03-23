"""User model for multi-tenant support"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.db.models.models import Base


class UserRole(enum.Enum):
    """User role enum"""

    ADMIN = "admin"
    MEMBER = "member"


class User(Base):
    """User model with organisation relationship"""

    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False, index=True)
    email = Column(String(255), nullable=False, unique=True, index=True)
    password_hash = Column(String(255), nullable=False)
    phone_number = Column(String(15), nullable=True)  # 6-15 digits
    # Optional profile names (used for UI personalization like avatar initials).
    first_name = Column(String(255), nullable=True)
    last_name = Column(String(255), nullable=True)
    role = Column(Enum(UserRole, name="user_role"), default=UserRole.MEMBER, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    totp_secret = Column(String, nullable=True)
    two_factor_enabled = Column(Boolean, default=False, nullable=False)
    # Conservative default (24h); long sessions only with explicit user choice in settings.
    session_timeout_minutes = Column(Integer, default=24 * 60, nullable=False)

    # Account lockout fields for brute force protection
    failed_login_attempts = Column(Integer, default=0, nullable=False)  # Count of consecutive failed login attempts
    account_locked_until = Column(DateTime(timezone=True), nullable=True)  # Timestamp when account lockout expires

    # Relationship
    organisation = relationship("Organisation", backref="users")

    def __repr__(self):
        return f"<User(id={self.id}, email={self.email}, org_id={self.org_id}, role={self.role.value})>"
