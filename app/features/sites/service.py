"""Site registration without exposing incomplete multi-site operations."""

from uuid import UUID

from sqlalchemy import func, select

from app.core.db.models.execution import Execution
from app.core.db.models.inventory_item import InventoryItem
from app.core.db.models.organisation import Organisation
from app.core.db.models.site import Site
from app.core.db.models.stock_location import StockLocation
from app.core.db.site_guard import SiteScopeError

KINDS = {
    "manufacturing": "Manufacturing",
    "storage": "Storage / bond",
    "retail": "Cellar door / retail",
    "warehouse": "Warehouse / 3PL",
    "event": "Event",
}


def parse_id(value):
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise SiteScopeError("Invalid site ID") from None


def get_site(session, org_id, site_id):
    return session.query(Site).filter(Site.org_id == org_id, Site.id == site_id).one_or_none()


def locked_org(session, org_id):
    org = session.query(Organisation).filter(Organisation.id == org_id).with_for_update().one_or_none()
    if org is None:
        raise SiteScopeError("Organisation not found")
    return org


def ensure_default(session, org_id):
    # Caller holds the org row lock, so two settings requests cannot create two defaults.
    site = session.query(Site).filter(Site.org_id == org_id, Site.is_default.is_(True)).one_or_none()
    if site is None:
        site = Site(org_id=org_id, name="Main site", kind="manufacturing", is_default=True)
        session.add(site)
        session.flush()
    return site


def configure(session, org_id, enabled):
    if not isinstance(enabled, bool):
        raise SiteScopeError("enabled must be true or false")
    org = locked_org(session, org_id)
    if not enabled and org.multiple_site_operations_enabled:
        session.query(Site).filter(Site.org_id == org_id).order_by(Site.id).with_for_update().populate_existing().all()
        additional = select(Site.id).where(Site.org_id == org_id, Site.is_default.is_(False))

        def has_additional(model):
            return (
                session.query(model.id).filter(model.org_id == org_id, model.site_id.in_(additional)).first()
                is not None
            )

        if has_additional(StockLocation) or has_additional(Execution) or has_additional(InventoryItem):
            raise SiteScopeError("Multiple sites cannot switch off while additional-site operational records exist")
    if enabled:
        default = ensure_default(session, org_id)

        def backfill(model):
            session.query(model).filter(model.org_id == org_id, model.site_id.is_(None)).update(
                {model.site_id: default.id}, synchronize_session="fetch"
            )

        # Three table updates regardless of the number of stock rows.
        backfill(StockLocation)
        backfill(Execution)
        backfill(InventoryItem)
    org.multiple_sites_enabled = enabled
    session.flush()
    return org


def clean_site(data, current=None):
    allowed = {"name", "address", "kind", "is_active", "is_default"}
    if not isinstance(data, dict) or set(data) - allowed:
        raise SiteScopeError("Unknown site field")
    values = {}
    for field, limit in (("name", 120), ("address", 500)):
        if current is None or field in data:
            raw = data.get(field)
            if raw is not None and not isinstance(raw, str):
                raise SiteScopeError(f"{field} must be text")
            value = (raw or "").strip()
            if len(value) > limit or (field == "name" and not value):
                raise SiteScopeError(f"{field} must be {'1–' if field == 'name' else 'up to '}{limit} characters")
            values[field] = value or None
    if current is None or "kind" in data:
        kind = data.get("kind", "manufacturing")
        if not isinstance(kind, str) or kind not in KINDS:
            raise SiteScopeError("Choose a supported site kind")
        values["kind"] = kind
    for field in ("is_active", "is_default"):
        if field in data:
            if not isinstance(data[field], bool):
                raise SiteScopeError(f"{field} must be true or false")
            values[field] = data[field]
    return values


def save_site(session, org_id, data, site=None):
    org = locked_org(session, org_id)
    if not org.multiple_sites_enabled:
        raise SiteScopeError("Switch on multiple sites before editing the site register")
    default = ensure_default(session, org_id)
    values = clean_site(data, site)
    if site is None:
        site = Site(
            org_id=org_id,
            name=values["name"],
            address=values["address"],
            kind=values["kind"],
            is_default=False,
            is_active=True,
        )
        session.add(site)
    if values.get("is_default") is False and site.is_default:
        raise SiteScopeError("Choose another default site instead")
    if values.get("is_active") is False and (site.is_default or values.get("is_default")):
        raise SiteScopeError("The default site must stay active")
    if values.get("is_default") and not values.get("is_active", site.is_active):
        raise SiteScopeError("The default site must stay active")
    if values.get("is_default") is True and site.id != default.id:
        # Pair with the operational tag guard's shared lock before checking whether
        # the old default is empty. Concurrent first stock must win or follow us.
        session.query(Site).filter(Site.org_id == org_id).order_by(Site.id).with_for_update().populate_existing().all()
        occupied = any(
            session.query(model.id).filter(model.org_id == org_id).first() is not None
            for model in (StockLocation, Execution, InventoryItem)
        )
        if occupied:
            raise SiteScopeError("The default cannot change after stock, locations or batches exist")
        default.is_default = False
        session.flush()
    for key, value in values.items():
        setattr(site, key, value)
    if not site.name:
        raise SiteScopeError("Give the site a name")
    duplicate = session.query(Site).filter(Site.org_id == org_id, func.lower(Site.name) == site.name.lower()).all()
    if any(row.id != site.id for row in duplicate):
        raise SiteScopeError("A site with that name already exists")
    session.flush()
    return site


def serialise(site):
    return {
        "id": str(site.id),
        "name": site.name,
        "address": site.address,
        "kind": site.kind,
        "is_active": bool(site.is_active),
        "is_default": bool(site.is_default),
        "operations_available": bool(site.is_default),
    }


def overview(session, org_id):
    org = session.query(Organisation).filter(Organisation.id == org_id).one()
    sites = session.query(Site).filter(Site.org_id == org_id).order_by(Site.is_default.desc(), Site.name).all()
    return {
        "enabled": bool(org.multiple_sites_enabled),
        "sites": [serialise(site) for site in sites] if org.multiple_sites_enabled else [],
        "kinds": KINDS,
        "additional_site_operations_available": bool(org.multiple_site_operations_enabled),
    }
