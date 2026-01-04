"""Organisation management service"""

from uuid import UUID

from sqlalchemy.orm import Session

from app.core.db.models.organisation import Organisation, OrganisationStatus
from app.core.db.models.user import User, UserRole
from app.core.db.repositories.organisation_repo import OrganisationRepository
from app.core.db.repositories.user_repo import EmailConflictError, UserRepository
from app.core.security.auth_service import AuthService


class OrgManager:
    """Service for organisation management operations"""

    def __init__(self, db: Session):
        self.db = db
        self.org_repo = OrganisationRepository(db)
        self.user_repo = UserRepository(db)
        self.auth_service = AuthService(db)

    def create_org_with_admin_user(
        self, org_name: str, admin_email: str, password: str, phone_number: str | None = None
    ) -> tuple[Organisation, User]:
        """Create a new organisation with an admin user"""
        # Check if org name already exists
        existing_org = self.org_repo.get_org_by_name(org_name)
        if existing_org:
            raise ValueError(f"Organisation with name '{org_name}' already exists")

        # Check if email already exists (only check active users to allow reusing emails from deleted accounts)
        existing_user = self.user_repo.get_user_by_email(admin_email)
        if existing_user and existing_user.is_active:
            raise ValueError(f"User with email '{admin_email}' already exists")

        # Create organisation
        org = self.org_repo.create_org(org_name, status=OrganisationStatus.ACTIVE)

        # Create admin user
        password_hash = AuthService.hash_password(password)
        try:
            admin_user = self.user_repo.create_user(
                org_id=org.id,
                email=admin_email,
                password_hash=password_hash,
                role=UserRole.ADMIN,
                is_active=True,
                phone_number=phone_number,
            )
        except EmailConflictError:
            # Rollback org creation if user creation fails due to email conflict
            self.db.rollback()
            raise ValueError(f"User with email '{admin_email}' already exists")

        return org, admin_user

    def switch_org(self, user_id: UUID, new_org_id: UUID) -> bool:
        """Switch user's organisation (if user belongs to that org)"""
        user = self.user_repo.get_user_by_id(user_id, org_id=new_org_id)
        if not user:
            return False

        # Update session would be handled by the middleware/route
        return True
