"""Generic physical-site selection and production input validation.

Shipping defaults to the organisation's default site. Production always uses the
persisted execution site. Neither rule relies on a client-supplied stock tag.
"""

from uuid import UUID

from app.core.db.models.inventory_item import InventoryItem
from app.core.db.models.organisation import Organisation
from app.core.db.models.site import Site
from app.core.db.site_guard import SiteScopeError


def resolve_site(session, org_id, site_id=None):
    org = (
        session.query(
            Organisation.id, Organisation.multiple_sites_enabled, Organisation.multiple_site_operations_enabled
        )
        .filter(Organisation.id == org_id)
        .one_or_none()
    )
    if org is None:
        raise SiteScopeError("Organisation not found")
    if not org.multiple_sites_enabled:
        if site_id is not None:
            raise SiteScopeError("Multiple sites are switched off")
        return None
    query = session.query(Site).filter(Site.org_id == org_id, Site.is_active.is_(True))
    if site_id is None:
        query = query.filter(Site.is_default.is_(True))
    else:
        try:
            site_id = UUID(str(site_id))
        except (ValueError, TypeError):
            raise SiteScopeError("Invalid site ID") from None
        query = query.filter(Site.id == site_id)
    site = query.with_for_update(read=True).populate_existing().one_or_none()
    if site is None:
        raise SiteScopeError("Site must be active and belong to this organisation")
    if not site.is_default and not org.multiple_site_operations_enabled:
        raise SiteScopeError("Operations at additional sites are not available yet")
    return site.id


def validate_execution_inputs(session, execution, actual_inputs, actual_outputs):
    org = session.query(Organisation.multiple_sites_enabled).filter(Organisation.id == execution.org_id).one()
    if not org.multiple_sites_enabled:
        return
    site_id = resolve_site(session, execution.org_id, execution.site_id)
    if site_id is None:
        return
    item_ids = set()
    for entry in actual_inputs or []:
        if not isinstance(entry, dict):
            raise SiteScopeError("Each input must be an object")
        value = entry.get("inventory_item_id")
        if value:
            try:
                item_ids.add(UUID(str(value)))
            except (ValueError, TypeError):
                raise SiteScopeError("Invalid input inventory ID") from None
    for entry in actual_outputs or []:
        if not isinstance(entry, dict):
            raise SiteScopeError("Each output must be an object")
        # Reconciliation reduces physical stock as part of production too.
        value = entry.get("untracked_item_id")
        if value:
            try:
                item_ids.add(UUID(str(value)))
            except (ValueError, TypeError):
                raise SiteScopeError("Invalid reconciliation inventory ID") from None
    if not item_ids:
        return
    items = (
        session.query(InventoryItem)
        .filter(InventoryItem.org_id == execution.org_id, InventoryItem.id.in_(item_ids))
        .order_by(InventoryItem.id)
        .with_for_update()
        .populate_existing()
        .all()
    )
    if len(items) != len(item_ids) or any(item.site_id != site_id for item in items):
        raise SiteScopeError("Every input and reconciliation lot must belong to the execution's site")
