"""Multiple sites sit behind three gates, all off by default (GL-P07).

1. the deployment: ``[features] multi_site_enabled``;
2. the organisation's plan: the ``multi_site`` subscription;
3. the organisation's own switch in Settings, Sites.

With all three on, work happens at any active site and the default site is only where records
made without a site land. Take any gate away and everything new stays at the default site.
"""

import re
from datetime import date
from uuid import UUID

import pytest

from app.core.db.models.organisation import Organisation
from app.core.db.models.stock_location import StockLocation
from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository
from app.core.db.repositories.inventory_repo import InventoryRepository
from app.core.security.tenant_scope import unscoped
from app.utils.config_loader import config
from tests.factories import InventoryItemFactory
from tests.test_compliant_routes import _admin_client
from tests.test_sites import _add, _enable, flask_app, world  # noqa: F401 -- shared fixtures


def _stock_at(client, site_id, name="Juniper berries"):
    body = {"name": name, "quantity": "5", "unit": "kg", "inventory_type": "raw_material"}
    if site_id is not None:  # a page that doesn't ask where stock goes sends no site at all
        body["site_id"] = site_id
    return client.post("/api/core/inventory", json=body)


def _site_of(db, response):
    from app.core.db.models.inventory_item import InventoryItem

    with unscoped():
        return str(db.get(InventoryItem, UUID(response.get_json()["id"])).site_id)


def test_without_the_plan_the_switch_stays_off_and_the_tab_is_hidden(db, flask_app):  # noqa: F811
    org, client = _admin_client(db, flask_app)
    overview = client.get("/api/core/sites").get_json()
    assert overview["entitled"] is False and overview["enabled"] is False
    refused = client.put("/api/core/sites/settings", json={"enabled": True})
    assert refused.status_code == 400 and "plan" in refused.get_json()["error"]
    assert _sites_tab(client) == "hidden"


def _sites_tab(client):
    """The Settings > Sites tab: "hidden", "shown", or None when it isn't in the page."""
    match = re.search(r'<a [^>]*data-section-tab="sites"[^>]*>', client.get("/core/settings").get_data(as_text=True))
    if match is None:
        return None
    return "hidden" if re.search(r"\shidden(\s|>)", match.group(0)) else "shown"


def test_the_deployment_flag_is_a_gate_of_its_own(world, monkeypatch):  # noqa: F811
    _, admin, _, _ = world  # this organisation's plan includes multiple sites
    monkeypatch.setattr(type(config), "multi_site_enabled", property(lambda self: False))
    assert admin.get("/api/core/sites").get_json()["entitled"] is False
    assert admin.put("/api/core/sites/settings", json={"enabled": True}).status_code == 400


def test_with_every_gate_on_work_happens_at_any_active_site(world, db):  # noqa: F811
    _, admin, _, _ = world
    assert _sites_tab(admin) == "shown"
    default = _enable(admin)
    bond = _add(admin)
    assert bond["operations_available"] is True
    assert admin.get("/api/core/sites").get_json()["additional_site_operations_available"] is True
    made = _stock_at(admin, bond["id"])
    assert made.status_code == 201, made.get_json()
    # Without a site, stock lands on the default.
    unplaced = _stock_at(admin, None, name="Coriander seed")
    assert unplaced.status_code == 201, unplaced.get_json()
    assert _site_of(db, unplaced) == default["id"]


def test_taking_the_plan_away_keeps_new_work_at_the_default_site(world, db):  # noqa: F811
    org, admin, _, _ = world
    default = _enable(admin)
    bond = _add(admin)
    with unscoped():
        FeatureSubscriptionRepository(db).revoke(org.id, "multi_site")
        db.commit()
    refused = _stock_at(admin, bond["id"])
    assert refused.status_code == 400 and "plan" in refused.get_json()["error"]
    assert _stock_at(admin, default["id"]).status_code == 201


def test_the_default_site_can_change_once_stock_exists(world, db):  # noqa: F811
    _, admin, _, _ = world
    default = _enable(admin)
    bond = _add(admin)
    assert _stock_at(admin, default["id"]).status_code == 201
    moved = admin.patch(f"/api/core/sites/{bond['id']}", json={"is_default": True})
    assert moved.status_code == 200, moved.get_json()
    later = _stock_at(admin, None, name="Orris root")
    assert later.status_code == 201, later.get_json()
    assert _site_of(db, later) == bond["id"]  # only new records follow the new default


@pytest.mark.parametrize("crosses_licensed_area", [False, True])
def test_moving_between_places_at_one_site(world, db, crosses_licensed_area):  # noqa: F811
    org, admin, _, _ = world
    default = _enable(admin)
    site_id = UUID(default["id"])
    with unscoped():
        tank = StockLocation(org_id=org.id, name="Tank bay", site_id=site_id, inside_licensed_area=True)
        shelf = StockLocation(
            org_id=org.id, name="Store shelf", site_id=site_id, inside_licensed_area=not crosses_licensed_area
        )
        db.add_all([tank, shelf])
        db.flush()
        lot = InventoryItemFactory(org_id=org.id, name="Gin", quantity="10", unit="L", site_id=site_id)
        lot.location_id = tank.id
        db.commit()
        assert db.get(Organisation, org.id).multiple_sites_enabled
        repo = InventoryRepository(db)
        if crosses_licensed_area:
            # Leaving the licensed area is a movement the compliance module rules on.
            with pytest.raises(ValueError, match="licensed area"):
                repo.move_lot(org.id, lot.id, "4", shelf.id, date.today())
        else:
            # It used to refuse every move once sites were on, even across one room.
            moved, _ = repo.move_lot(org.id, lot.id, "4", shelf.id, date.today())
            assert moved.location_id == shelf.id and moved.site_id == site_id
