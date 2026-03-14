"""Organisation repository with CRUD operations"""

from uuid import UUID

from sqlalchemy.orm import Session

from app.core.db.models.organisation import Organisation, OrganisationStatus


class OrganisationRepository:
    """Repository for organisation operations"""

    def __init__(self, db: Session):
        self.db = db

    def create_org(self, name: str, status: OrganisationStatus = OrganisationStatus.ACTIVE) -> Organisation:
        """Create a new organisation"""
        org = Organisation(name=name, status=status)
        self.db.add(org)
        self.db.flush()  # Flush to get the ID without committing
        # Access id to ensure it's loaded
        _ = org.id
        self.db.commit()
        return org

    def get_org_by_id(self, org_id: UUID) -> Organisation | None:
        """Get organisation by ID"""
        return self.db.query(Organisation).filter(Organisation.id == org_id).first()

    def get_org_by_name(self, name: str) -> Organisation | None:
        """Get organisation by name"""
        return self.db.query(Organisation).filter(Organisation.name == name).first()

    def list_orgs(self, status: OrganisationStatus | None = None) -> list[Organisation]:
        """List all organisations, optionally filtered by status"""
        query = self.db.query(Organisation)
        if status:
            query = query.filter(Organisation.status == status)
        return query.all()

    def update_org(
        self, org_id: UUID, name: str | None = None, status: OrganisationStatus | None = None
    ) -> Organisation | None:
        """Update organisation"""
        org = self.get_org_by_id(org_id)
        if not org:
            return None

        if name is not None:
            org.name = name
        if status is not None:
            org.status = status

        # Commit changes - updated_at will be set by onupdate trigger
        self.db.commit()

        # Expire only the updated_at attribute to force reload from DB
        # This is more efficient than re-querying the entire object
        self.db.expire(org, ["updated_at"])
        # Access updated_at to trigger lazy load while object is still bound to session
        _ = org.updated_at

        return org

    def delete_org(self, org_id: UUID) -> bool:
        """Delete organisation (soft delete by setting status to SUSPENDED)"""
        org = self.get_org_by_id(org_id)
        if not org:
            return False

        org.status = OrganisationStatus.SUSPENDED
        self.db.commit()
        return True
