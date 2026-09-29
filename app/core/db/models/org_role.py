"""An organisation's custom roles (plan 0.4c)."""

import uuid

from sqlalchemy import TIMESTAMP, Column, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.db.models.models import Base
from app.core.db.models.tenant_mixin import TenantScoped
from app.core.utils.time import utc_now


class OrgRole(TenantScoped, Base):
    """A permission set an admin made by cloning a built-in role and ticking permissions."""

    __tablename__ = "org_roles"
    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_org_roles_org_name"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False)
    description = Column(String(500), nullable=True)
    base_role = Column(String(20), nullable=False)  # a UserRole value, never admin
    permissions = Column(JSONB, nullable=False, default=list, server_default="[]")
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
