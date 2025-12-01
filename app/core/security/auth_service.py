"""Authentication service for user authentication and session management"""

import hashlib
import hmac
import secrets
from uuid import UUID
from datetime import datetime
from flask import g, session
from sqlalchemy.orm import Session

from app.core.db.models.user import User
from app.core.db.repositories.user_repo import UserRepository
from app.core.db.repositories.organisation_repo import OrganisationRepository


class AuthService:
    """Service for authentication and authorization"""

    def __init__(self, db: Session):
        self.db = db
        self.user_repo = UserRepository(db)
        self.org_repo = OrganisationRepository(db)

    @staticmethod
    def hash_password(password: str) -> str:
        """Hash a password using SHA-256 with salt"""
        # Generate a random salt
        salt = secrets.token_hex(16)
        # Hash password with salt
        password_hash = hashlib.sha256((password + salt).encode()).hexdigest()
        # Store as salt:hash
        return f"{salt}:{password_hash}"

    @staticmethod
    def verify_password(password: str, password_hash: str) -> bool:
        """Verify a password against a hash"""
        try:
            salt, stored_hash = password_hash.split(":", 1)
            computed_hash = hashlib.sha256((password + salt).encode()).hexdigest()
            return hmac.compare_digest(computed_hash, stored_hash)
        except (ValueError, AttributeError):
            return False

    def authenticate(self, email: str, password: str, org_id: UUID | None = None) -> User | None:
        """Authenticate a user by email and password"""
        user = self.user_repo.get_user_by_email(email, org_id=org_id)
        if not user:
            return None

        if not user.is_active:
            return None

        if not self.verify_password(password, user.password_hash):
            return None

        return user

    def generate_session(self, user: User) -> dict:
        """Generate session data for a user"""
        session_data = {
            "user_id": str(user.id),
            "org_id": str(user.org_id),
            "email": user.email,
            "role": user.role.value,
            "created_at": datetime.utcnow().isoformat()
        }
        return session_data

    def get_current_user(self) -> User | None:
        """Get current user from Flask g or session"""
        # First check Flask g (set by middleware)
        if hasattr(g, "current_user") and g.current_user:
            return g.current_user

        # Fallback to session
        if "user_id" in session:
            user_id = UUID(session["user_id"])
            org_id = UUID(session["org_id"]) if "org_id" in session else None
            return self.user_repo.get_user_by_id(user_id, org_id=org_id)

        return None

    def get_current_org_id(self) -> UUID | None:
        """Get current organisation ID from Flask g or session"""
        if hasattr(g, "current_org_id") and g.current_org_id:
            return g.current_org_id

        if "org_id" in session:
            return UUID(session["org_id"])

        return None

