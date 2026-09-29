"""Admin configuration of site grants. No selected-site staff activation yet."""

from uuid import UUID

from sqlalchemy import select

from app.core.db.models.org_role_site import OrgRoleSite
from app.core.db.models.organisation import Organisation
from app.core.db.models.site import Site
from app.core.db.models.user import User
from app.core.security.people import PeopleError

# Code release gate, never an organisation setting. Route/stock guards must land first.
SELECTED_SITE_ROLES_ACTIVE = False


def lock_role_administration(db, org_id):
    """Serialize role/grant/assignment changes in the organisation.

    Integration stock writes will refresh authorization after their existing org SHARE
    lock and before site/inventory locks. No ambient middleware org lock is acquired.
    """
    db.execute(select(Organisation.id).where(Organisation.id == org_id).with_for_update(key_share=True)).one()


def validate_site_config(db, org_id, data, *, default_mode="all", default_ids=()):
    mode = data.get("site_access_mode", default_mode)
    raw = data.get("site_ids", [] if mode == "all" else list(default_ids))
    if mode not in ("all", "selected"):
        raise PeopleError("Choose all sites or selected sites.")
    if not isinstance(raw, list) or len(raw) > 250:
        raise PeopleError("Site grants must be a list of up to 250 site IDs.")
    try:
        if any(not isinstance(value, str) for value in raw):
            raise ValueError
        ids = frozenset(UUID(value) for value in raw)
    except (ValueError, AttributeError):
        raise PeopleError("Invalid site grant.") from None
    if mode == "all" and ids:
        raise PeopleError("An all-sites role cannot also have selected site grants.")
    valid = set(
        db.scalars(
            select(Site.id).where(
                Site.org_id == org_id,
                Site.id.in_(ids),
                (Site.is_active.is_(True) | Site.id.in_([UUID(str(value)) for value in default_ids])),
            )
        )
    )
    if valid != ids:
        raise PeopleError("Choose active sites belonging to this organisation.")
    return mode, ids


def role_site_ids(db, org_id, role_id):
    return tuple(
        db.scalars(
            select(OrgRoleSite.site_id)
            .where(
                OrgRoleSite.org_id == org_id,
                OrgRoleSite.role_id == role_id,
            )
            .order_by(OrgRoleSite.site_id)
        )
    )


def replace_site_config(db, role, mode, ids):
    if mode == "selected" and not SELECTED_SITE_ROLES_ACTIVE:
        held = db.scalar(select(User.id).where(User.org_id == role.org_id, User.custom_role_id == role.id).limit(1))
        if held is not None:
            raise PeopleError("Selected-site roles cannot be assigned yet. Give its people another role first.")
    db.query(OrgRoleSite).filter(OrgRoleSite.org_id == role.org_id, OrgRoleSite.role_id == role.id).delete(
        synchronize_session=False,
    )
    role.site_access_mode = mode
    db.flush()
    db.add_all(OrgRoleSite(org_id=role.org_id, role_id=role.id, site_id=site_id) for site_id in sorted(ids))


def check_site_role_assignment(custom):
    if custom is None:
        return
    if custom.site_access_mode not in ("all", "selected"):
        raise PeopleError("This role has invalid site access configuration.")
    if custom.site_access_mode == "selected" and not SELECTED_SITE_ROLES_ACTIVE:
        raise PeopleError("Selected-site roles cannot be assigned yet. Use an all-sites role.")
