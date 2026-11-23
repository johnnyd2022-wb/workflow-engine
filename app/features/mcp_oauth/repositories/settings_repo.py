"""The organisation's MCP switch and the roles allowed to connect an assistant."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.db.models.org_role import OrgRole
from app.features.mcp_oauth.models import McpAllowedRole, McpOrgSettings


class SettingsRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, org_id: UUID) -> McpOrgSettings | None:
        return self.db.query(McpOrgSettings).filter(McpOrgSettings.org_id == org_id).one_or_none()

    def is_enabled(self, org_id: UUID) -> bool:
        row = self.get(org_id)
        return bool(row is not None and row.enabled)

    def allowed_role_keys(self, org_id: UUID) -> list[str]:
        rows = self.db.query(McpAllowedRole.role_key).filter(McpAllowedRole.org_id == org_id).all()
        return sorted(r[0] for r in rows)

    def role_is_allowed(self, org_id: UUID, role_key: str) -> bool:
        return (
            self.db.query(McpAllowedRole)
            .filter(McpAllowedRole.org_id == org_id, McpAllowedRole.role_key == role_key)
            .first()
            is not None
        )

    def custom_role_exists(self, org_id: UUID, role_id: UUID) -> bool:
        return self.db.query(OrgRole.id).filter(OrgRole.org_id == org_id, OrgRole.id == role_id).first() is not None

    def custom_roles(self, org_id: UUID) -> list[OrgRole]:
        return self.db.query(OrgRole).filter(OrgRole.org_id == org_id).order_by(OrgRole.name).all()

    def save(
        self,
        org_id: UUID,
        enabled: bool,
        role_keys: list[str],
        user_id: UUID | None,
        now: datetime,
    ) -> None:
        row = self.get(org_id)
        if row is None:
            row = McpOrgSettings(org_id=org_id)
            self.db.add(row)
        row.enabled = enabled
        row.updated_by_user_id = user_id
        row.updated_at = now
        self.db.query(McpAllowedRole).filter(McpAllowedRole.org_id == org_id).delete(synchronize_session=False)
        for key in role_keys:
            self.db.add(McpAllowedRole(org_id=org_id, role_key=key))
        self.db.flush()

    def prune_role(self, org_id: UUID, role_key: str) -> None:
        self.db.query(McpAllowedRole).filter(
            McpAllowedRole.org_id == org_id, McpAllowedRole.role_key == role_key
        ).delete(synchronize_session=False)
