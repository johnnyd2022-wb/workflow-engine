"""User model for multi-tenant support"""

import enum
import uuid

from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.db.models.models import Base
from app.core.db.models.tenant_mixin import TenantScoped
from app.core.utils.time import utc_now


class UserRole(enum.Enum):
    """User role enum"""

    ADMIN = "admin"
    MEMBER = "member"  # shown as "Staff": everything except admin-only settings
    PRODUCTION = "production"
    COMPLIANCE = "compliance"
    SALES = "sales"
    AUDITOR = "auditor"  # read-only and time-limited (access_expires_at)


class User(TenantScoped, Base):
    """User model with organisation relationship"""

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("org_id", "id", name="uq_oc_users_org_id_id"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), nullable=False, unique=True, index=True)
    password_hash = Column(String(255), nullable=False)
    phone_number = Column(String(15), nullable=True)  # 6-15 digits
    # Optional profile names (used for UI personalization like avatar initials).
    first_name = Column(String(255), nullable=True)
    last_name = Column(String(255), nullable=True)
    role = Column(Enum(UserRole, name="user_role"), default=UserRole.MEMBER, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    totp_secret = Column(String, nullable=True)
    two_factor_enabled = Column(Boolean, default=False, nullable=False)
    # Conservative default (24h); long sessions only with explicit user choice in settings.
    session_timeout_minutes = Column(Integer, default=24 * 60, nullable=False)
    # Time-limited access (e.g. an Auditor for a verification visit). After this moment
    # the account can't sign in or use an existing session.
    access_expires_at = Column(DateTime(timezone=True), nullable=True)
    # A custom role (plan 0.4c) replaces the built-in role's permissions; ``role`` then
    # holds the built-in role it was cloned from.
    custom_role_id = Column(UUID(as_uuid=True), ForeignKey("org_roles.id", ondelete="RESTRICT"), nullable=True)
    # Pending invite: SHA-256 of the one-time setup token, and when it stops working.
    invite_token_hash = Column(String(64), nullable=True, unique=True, index=True)
    invite_expires_at = Column(DateTime(timezone=True), nullable=True)

    # Account lockout fields for brute force protection
    failed_login_attempts = Column(Integer, default=0, nullable=False)  # Count of consecutive failed login attempts
    account_locked_until = Column(DateTime(timezone=True), nullable=True)  # Timestamp when account lockout expires

    # Relationship
    organisation = relationship("Organisation", backref="users")

    def __repr__(self):
        return f"<User(id={self.id}, email={self.email}, org_id={self.org_id}, role={self.role.value})>"
