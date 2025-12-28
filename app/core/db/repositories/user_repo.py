"""User repository with tenancy enforcement"""

from uuid import UUID

from sqlalchemy.orm import Session

from app.core.db.models.user import User, UserRole


class UserRepository:
    """Repository for user operations with automatic tenancy enforcement"""

    def __init__(self, db: Session):
        self.db = db

    def create_user(
        self, org_id: UUID, email: str, password_hash: str, role: UserRole = UserRole.MEMBER, is_active: bool = True
    ) -> User:
        """Create a new user (must belong to an organisation)"""
        user = User(org_id=org_id, email=email, password_hash=password_hash, role=role, is_active=is_active)
        self.db.add(user)
        self.db.flush()  # Flush to get the ID without committing
        # Access id to ensure it's loaded
        _ = user.id
        self.db.commit()
        return user

    def get_user_by_id(self, user_id: UUID, org_id: UUID | None = None) -> User | None:
        """Get user by ID, optionally scoped to organisation"""
        query = self.db.query(User).filter(User.id == user_id)
        if org_id is not None:
            query = query.filter(User.org_id == org_id)
        return query.first()

    def get_user_by_email(self, email: str, org_id: UUID | None = None) -> User | None:
        """Get user by email, optionally scoped to organisation"""
        query = self.db.query(User).filter(User.email == email)
        if org_id is not None:
            query = query.filter(User.org_id == org_id)
        return query.first()

    def list_users_for_org(self, org_id: UUID, active_only: bool = False) -> list[User]:
        """List all users for an organisation (tenancy enforced)"""
        query = self.db.query(User).filter(User.org_id == org_id)
        if active_only:
            query = query.filter(User.is_active.is_(True))  # SQLAlchemy boolean comparison
        return query.all()

    def update_user(
        self,
        user_id: UUID,
        org_id: UUID,
        email: str | None = None,
        password_hash: str | None = None,
        role: UserRole | None = None,
        is_active: bool | None = None,
    ) -> User | None:
        """Update user (tenancy enforced - must match org_id)"""
        user = self.get_user_by_id(user_id, org_id=org_id)
        if not user:
            return None

        if email is not None:
            user.email = email
        if password_hash is not None:
            user.password_hash = password_hash
        if role is not None:
            user.role = role
        if is_active is not None:
            user.is_active = is_active

        self.db.commit()
        self.db.refresh(user)
        return user

    def delete_user(self, user_id: UUID, org_id: UUID) -> bool:
        """Delete user (tenancy enforced - soft delete by setting is_active=False)"""
        user = self.get_user_by_id(user_id, org_id=org_id)
        if not user:
            return False

        user.is_active = False
        self.db.commit()
        return True

    def set_totp_secret(self, user_id: UUID, secret: str) -> User | None:
        """Set TOTP secret for a user"""
        user = self.get_user_by_id(user_id)
        if not user:
            return None
        user.totp_secret = secret
        self.db.commit()
        return user

    def enable_two_factor(self, user_id: UUID) -> User | None:
        """Enable two-factor authentication for a user"""
        user = self.get_user_by_id(user_id)
        if not user:
            return None
        user.two_factor_enabled = True
        self.db.commit()
        return user

    def disable_two_factor(self, user_id: UUID) -> User | None:
        """Disable two-factor authentication for a user"""
        user = self.get_user_by_id(user_id)
        if not user:
            return None
        user.totp_secret = None
        user.two_factor_enabled = False
        self.db.commit()
        return user

    def update_session_timeout(self, user_id: UUID, timeout_minutes: int) -> User | None:
        """Update session timeout for a user"""
        user = self.get_user_by_id(user_id)
        if not user:
            return None
        user.session_timeout_minutes = timeout_minutes
        self.db.commit()
        return user

    def increment_failed_login_attempts(self, user_id: UUID) -> User | None:
        """Increment failed login attempts counter for account lockout"""
        user = self.get_user_by_id(user_id)
        if not user:
            return None
        user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
        self.db.commit()
        return user

    def reset_failed_login_attempts(self, user_id: UUID) -> User | None:
        """Reset failed login attempts counter on successful login"""
        user = self.get_user_by_id(user_id)
        if not user:
            return None
        user.failed_login_attempts = 0
        user.account_locked_until = None
        self.db.commit()
        return user

    def lock_account(self, user_id: UUID, lockout_duration_minutes: int = 1) -> User | None:
        """Lock user account for specified duration (default 1 minute)"""
        from datetime import datetime, timedelta, timezone
        
        user = self.get_user_by_id(user_id)
        if not user:
            return None
        user.account_locked_until = datetime.now(timezone.utc) + timedelta(minutes=lockout_duration_minutes)
        self.db.commit()
        return user

    def unlock_account(self, user_id: UUID) -> User | None:
        """Unlock user account (used during password reset)"""
        user = self.get_user_by_id(user_id)
        if not user:
            return None
        user.account_locked_until = None
        user.failed_login_attempts = 0
        self.db.commit()
        return user

    def is_account_locked(self, user_id: UUID) -> bool:
        """Check if account is currently locked"""
        from datetime import datetime, timezone
        
        user = self.get_user_by_id(user_id)
        if not user:
            return False
        if not user.account_locked_until:
            return False
        # Check if lockout has expired
        if user.account_locked_until < datetime.now(timezone.utc):
            # Auto-unlock expired accounts
            user.account_locked_until = None
            user.failed_login_attempts = 0
            self.db.commit()
            return False
        return True