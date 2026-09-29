"""Validated default-site tags while multi-site operations are staged.

The site register can be configured now. Stock and production at additional sites are
closed until consumption, sales matching and compliant movements enforce their scope.
No industry rules live here. A tag is a physical fact and cannot be edited as a move.
"""

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session


class SiteScopeError(ValueError):
    pass


def _before_flush(session, _flush_context, _instances):
    from app.core.db.models.execution import Execution
    from app.core.db.models.inventory_item import InventoryItem
    from app.core.db.models.organisation import Organisation
    from app.core.db.models.site import Site
    from app.core.db.models.stock_location import StockLocation

    scoped = (StockLocation, Execution, InventoryItem)
    affected = []
    for obj in session.new | session.dirty:
        if not isinstance(obj, scoped):
            continue
        attrs = inspect(obj).attrs
        relevant = ("site_id",)
        if isinstance(obj, InventoryItem):
            relevant += ("location_id", "source_execution_id")
        if obj in session.new or any(attrs[key].history.has_changes() for key in relevant):
            affected.append(obj)
    if not affected:
        return
    org_ids = {obj.org_id for obj in affected}
    organisations = {row.id: row for row in session.query(Organisation).filter(Organisation.id.in_(org_ids))}
    # Share-lock registration rows while assigning tags. A concurrent default change
    # takes an exclusive lock before checking occupancy, so it cannot strand new stock
    # at what has just become an additional (not operational yet) site.
    sites = {
        (row.org_id, row.id): row
        for row in session.query(Site)
        .filter(Site.org_id.in_(org_ids))
        .order_by(Site.org_id, Site.id)
        .with_for_update(read=True)
        .populate_existing()
    }
    defaults = {row.org_id: row for row in sites.values() if row.is_default}
    location_ids = {obj.location_id for obj in affected if isinstance(obj, InventoryItem) and obj.location_id}
    execution_ids = {
        obj.source_execution_id for obj in affected if isinstance(obj, InventoryItem) and obj.source_execution_id
    }
    locations = (
        {
            (row.org_id, row.id): row
            for row in session.query(StockLocation).filter(
                StockLocation.org_id.in_(org_ids),
                StockLocation.id.in_(location_ids),
            )
        }
        if location_ids
        else {}
    )
    executions = (
        {
            (row.org_id, row.id): row
            for row in session.query(Execution).filter(
                Execution.org_id.in_(org_ids),
                Execution.id.in_(execution_ids),
            )
        }
        if execution_ids
        else {}
    )
    for obj in affected:
        org_id = obj.org_id
        org, default = organisations.get(org_id), defaults.get(org_id)
        if org is None:
            raise SiteScopeError("Organisation not found")
        history = inspect(obj).attrs.site_id.history
        if obj not in session.new and history.has_changes() and history.deleted and history.deleted[0] is not None:
            raise SiteScopeError("A site tag cannot be changed: moving stock requires a recorded transfer")
        if org.multiple_sites_enabled and (default is None or not default.is_active):
            raise SiteScopeError("An active default site is required")
        if obj.site_id is None and default is not None:
            obj.site_id = default.id
        if obj.site_id is not None:
            site = sites.get((org_id, obj.site_id))
            if site is None or not site.is_active:
                raise SiteScopeError("Site must be active and belong to this organisation")
            if not site.is_default:
                raise SiteScopeError("Operations at additional sites are not available yet")
        if isinstance(obj, InventoryItem) and obj.location_id is not None:
            location = locations.get((org_id, obj.location_id))
            if location is None:
                raise SiteScopeError("Location must belong to this organisation")
            if location.site_id != obj.site_id:
                raise SiteScopeError("Stock and its location must belong to the same site")
        if isinstance(obj, InventoryItem) and obj.source_execution_id is not None:
            execution = executions.get((org_id, obj.source_execution_id))
            if execution is not None and execution.site_id != obj.site_id:
                raise SiteScopeError("Produced stock must belong to its execution's site")


def register_site_guard():
    if getattr(register_site_guard, "_registered", False):
        return
    event.listen(Session, "before_flush", _before_flush, propagate=True)
    register_site_guard._registered = True
