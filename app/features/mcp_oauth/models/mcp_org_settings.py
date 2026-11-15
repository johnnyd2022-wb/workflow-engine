"""Per-organisation switch and role list for AI assistant access (off by default)."""

from sqlalchemy import TIMESTAMP, Boolean, Column, ForeignKey, ForeignKeyConstraint, Text
from sqlalchemy.dialects.postgresql import UUID

from app.core.db.models.models import Base
from app.core.db.models.tenant_mixin import TenantScoped
from app.core.utils.time import utc_now


class McpOrgSettings(TenantScoped, Base):
    __tablename__ = "mcp_org_settings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "updated_by_user_id"],
            ["users.org_id", "users.id"],
            name="fk_mcp_org_settings_updated_by",
            ondelete="SET NULL (updated_by_user_id)",
        ),
    )

    # One row per organisation: the org id is the key.
    org_id = Column(UUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), primary_key=True)
    enabled = Column(Boolean, nullable=False, default=False, server_default="false")
    updated_by_user_id = Column(UUID(as_uuid=True), nullable=True)
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


class McpAllowedRole(TenantScoped, Base):
    """A role whose people may connect an assistant. ``builtin:<UserRole value>`` or
    ``custom:<org_roles.id>``; a custom key is checked against ``org_roles`` on write and pruned
    when the role is deleted (a composite FK is not possible on the union)."""

    __tablename__ = "mcp_allowed_roles"

    org_id = Column(UUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), primary_key=True)
    role_key = Column(Text, primary_key=True)
