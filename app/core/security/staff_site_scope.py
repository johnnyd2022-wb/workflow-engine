"""Immutable staff site authorization from a fresh, trusted database projection.

Physical site consistency and role permissions are independent checks. This scope never
uses a client site list or turns organisation opt-out into an authorization bypass.
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import and_, select

from app.core.db.models.org_role import OrgRole
from app.core.db.models.org_role_site import OrgRoleSite
from app.core.db.models.user import User, UserRole


@dataclass(frozen=True)
class StaffSiteScope:
    org_id: UUID
    user_id: UUID
    mode: str
    site_ids: frozenset[UUID] = frozenset()
    reason: str | None = None

    def permits(self, site_id):
        if self.mode == "all":
            return True
        return self.mode == "selected" and site_id is not None and site_id in self.site_ids

    def permits_transfer(self, source_site_id, destination_site_id):
        return self.permits(source_site_id) and self.permits(destination_site_id)


def load_staff_site_scope(db, org_id, user_id):
    """One statement provides a consistent snapshot, bypassing ORM identity-map state.

    Mutating operations in the future activation slice must refresh this projection
    under their org lock. Middleware deliberately does not acquire an ambient org lock.
    """
    rows = db.execute(
        select(
            User.role,
            User.custom_role_id,
            User.is_active,
            OrgRole.id,
            OrgRole.org_id,
            OrgRole.base_role,
            OrgRole.site_access_mode,
            OrgRoleSite.site_id,
        )
        .select_from(User)
        .outerjoin(OrgRole, User.custom_role_id == OrgRole.id)
        .outerjoin(
            OrgRoleSite,
            and_(OrgRoleSite.role_id == OrgRole.id, OrgRoleSite.org_id == OrgRole.org_id),
        )
        .where(User.id == user_id, User.org_id == org_id)
    ).all()

    def denied(reason):
        return StaffSiteScope(org_id, user_id, "deny", reason=reason)

    if not rows or not rows[0][2]:
        return denied("invalid_principal")
    role, custom_id, _, loaded_id, role_org, base, mode, _ = rows[0]
    if custom_id is None:
        return StaffSiteScope(org_id, user_id, "all") if isinstance(role, UserRole) else denied("invalid_role")
    if loaded_id != custom_id or role_org != org_id or base != getattr(role, "value", None) or role == UserRole.ADMIN:
        return denied("invalid_custom_role")
    ids = frozenset(row[7] for row in rows if row[7] is not None)
    if mode not in ("all", "selected") or (mode == "all" and ids):
        return denied("invalid_site_grants")
    if mode == "selected" and not ids:
        return denied("empty_site_grants")
    return StaffSiteScope(org_id, user_id, mode, ids)
