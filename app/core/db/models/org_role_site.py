"""Site grants belonging to an organisation's custom role."""

from sqlalchemy import Column, ForeignKeyConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.core.db.models.models import Base
from app.core.db.models.tenant_mixin import TenantScoped


class OrgRoleSite(TenantScoped, Base):
    __tablename__ = "org_role_sites"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "role_id"],
            ["org_roles.org_id", "org_roles.id"],
            name="fk_org_role_sites_role",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["org_id", "site_id"],
            ["sites.org_id", "sites.id"],
            name="fk_org_role_sites_site",
            ondelete="RESTRICT",
        ),
    )

    role_id = Column(UUID(as_uuid=True), primary_key=True)
    site_id = Column(UUID(as_uuid=True), primary_key=True)
