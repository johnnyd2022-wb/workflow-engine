"""Where stock goes and where it is (GL-P07 A3).

Every way stock arrives can name a site (manual, barcode, CSV, opening stock, customer
materials, starting a batch); with none named it lands on the default site. Inventory lists say
where each line is and can be narrowed to one site. Stock area names are unique within a site.
"""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.db.models.inventory_item import InventoryItem
from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository
from app.core.security.tenant_scope import unscoped
from tests.test_go_live import _gin_workflow
from tests.test_sites import _add, _enable, flask_app, world  # noqa: F401 -- shared fixtures


def _site_of(db, item_id):
    with unscoped():
        return str(db.get(InventoryItem, UUID(str(item_id))).site_id)


def test_choices_offer_nothing_until_every_gate_is_open(world, db):  # noqa: F811
    org, admin, _, _ = world
    assert admin.get("/api/core/sites/choices").get_json() == {"on": False, "default_id": None, "sites": []}
    default = _enable(admin)
    bond = _add(admin)
    admin.post("/api/core/stock-locations", json={"name": "Bay 1", "site_id": bond["id"]})
    choices = admin.get("/api/core/sites/choices").get_json()
    assert choices["on"] is True and choices["default_id"] == default["id"]
    assert [s["name"] for s in choices["sites"]] == ["Main site", "Bond store"]
    assert [a["name"] for a in choices["sites"][1]["areas"]] == ["Bay 1"]
    # Archived sites are not offered.
    admin.patch(f"/api/core/sites/{bond['id']}", json={"is_active": False})
    assert [s["name"] for s in admin.get("/api/core/sites/choices").get_json()["sites"]] == ["Main site"]
    # Without the plan nothing can be chosen, even with the switch still on.
    with unscoped():
        FeatureSubscriptionRepository(db).revoke(org.id, "multi_site")
        db.commit()
    assert admin.get("/api/core/sites/choices").get_json()["on"] is False


def test_inventory_says_where_each_line_is_and_narrows_to_a_site(world):  # noqa: F811
    _, admin, _, neighbour = world
    default = _enable(admin)
    bond = _add(admin)
    # Unplaced stock counts as inside the licensed area, so the bay is too (a same-area move).
    bay = admin.post(
        "/api/core/stock-locations", json={"name": "Bay 1", "site_id": bond["id"], "inside_licensed_area": True}
    ).get_json()
    body = {"quantity": "5", "unit": "kg", "inventory_type": "raw_material"}
    admin.post("/api/core/inventory", json={**body, "name": "Juniper"})
    admin.post("/api/core/inventory", json={**body, "name": "Orris", "site_id": bond["id"]})
    from app.core.db import db_session

    with unscoped():
        orris = db_session.query(InventoryItem).filter(InventoryItem.name == "Orris").one()
    moved = admin.post(f"/api/core/inventory/{orris.id}/move", json={"quantity": "5", "to_location_id": bay["id"]})
    assert moved.status_code == 201, moved.get_json()

    lines = {i["name"]: i for i in admin.get("/api/core/inventory").get_json()["inventory_items"]}
    assert lines["Juniper"]["site_id"] == default["id"] and lines["Juniper"]["location_name"] is None
    assert lines["Orris"]["site_id"] == bond["id"] and lines["Orris"]["location_name"] == "Bay 1"
    at_bond = admin.get(f"/api/core/inventory?site_id={bond['id']}").get_json()["inventory_items"]
    assert [i["name"] for i in at_bond] == ["Orris"]
    compact = admin.get(f"/api/core/inventory?view=compact&site_id={default['id']}").get_json()["inventory_items"]
    assert [(i["name"], i["site_id"]) for i in compact] == [("Juniper", default["id"])]
    assert admin.get("/api/core/inventory?site_id=nope").status_code == 400
    # Another organisation's site narrows to nothing, not to its stock.
    assert neighbour.get(f"/api/core/inventory?site_id={bond['id']}").get_json()["inventory_items"] == []


def test_csv_rows_go_to_the_file_site_or_their_own_site_column(world, db):  # noqa: F811
    _, admin, _, _ = world
    default = _enable(admin)
    bond = _add(admin)
    rows = [
        {"row_index": 2, "name": "Coriander", "quantity": "3", "unit": "kg"},
        {"row_index": 3, "name": "Angelica", "quantity": "1", "unit": "kg", "site": "main SITE"},
    ]
    made = admin.post("/api/core/inventory/csv-commit", json={"rows": rows, "site_id": bond["id"]})
    assert made.status_code == 200, made.get_json()
    where = {c["name"]: _site_of(db, c["id"]) for c in made.get_json()["created"]}
    assert where == {"Coriander": bond["id"], "Angelica": default["id"]}
    unknown = admin.post(
        "/api/core/inventory/csv-commit",
        json={"rows": [{"row_index": 2, "name": "Cassia", "quantity": "1", "unit": "kg", "site": "Petone"}]},
    )
    assert unknown.status_code == 400
    assert unknown.get_json()["errors"] == [{"row_index": 2, "error": "No active site called Petone"}]


def test_a_csv_site_column_is_refused_while_sites_are_off(world):  # noqa: F811
    _, admin, _, _ = world
    rows = [{"row_index": 2, "name": "Cassia", "quantity": "1", "unit": "kg", "site": "Main site"}]
    assert admin.post("/api/core/inventory/csv-commit", json={"rows": rows}).status_code == 400


def test_opening_stock_is_recorded_where_it_was_counted(world, db):  # noqa: F811
    org, admin, _, _ = world
    _enable(admin)
    bond = _add(admin)
    _gin_workflow(db, org.id)
    assert admin.put("/api/core/go-live", json={"go_live_date": "2026-10-01"}).status_code == 200
    row = {"name": "Gin - final product", "quantity": "44", "batch_id": "VAT44", "abv_percent": "44"}
    made = admin.post("/api/core/opening-stock", json={"items": [row], "site_id": bond["id"]})
    assert made.status_code == 201, made.get_json()
    with unscoped():
        item = db.query(InventoryItem).filter(InventoryItem.org_id == org.id, InventoryItem.name == row["name"]).one()
    assert str(item.site_id) == bond["id"]


def test_two_sites_can_each_have_a_dry_store_but_one_site_cannot_have_two(world):  # noqa: F811
    _, admin, _, _ = world
    default = _enable(admin)
    bond = _add(admin)
    for site in (default, bond):
        made = admin.post("/api/core/stock-locations", json={"name": "Dry store", "site_id": site["id"]})
        assert made.status_code == 201, made.get_json()
        assert made.get_json()["site_id"] == site["id"]
    again = admin.post("/api/core/stock-locations", json={"name": "Dry store", "site_id": bond["id"]})
    assert again.status_code == 409 and again.get_json()["error"] == "This site already has an area with that name"
    # With no site named the area lands on the default site, which already has one.
    assert admin.post("/api/core/stock-locations", json={"name": "Dry store"}).status_code == 409


def test_area_name_migration_round_trip_in_an_isolated_schema():
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    from app.core.db import engine
    from app.core.db.migrations.versions import site_area_names_001 as migration

    schema = "area_names_" + uuid4().hex
    org, site_a, site_b = uuid4(), uuid4(), uuid4()
    with engine.connect() as connection, connection.begin():
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        connection.execute(
            text(
                "CREATE TABLE stock_locations (id uuid PRIMARY KEY, org_id uuid NOT NULL, site_id uuid, "
                "name varchar(120) NOT NULL, CONSTRAINT uq_stock_locations_org_name UNIQUE (org_id, name))"
            )
        )
        insert = text("INSERT INTO stock_locations VALUES (:id, :org, :site, :name)")
        connection.execute(insert, {"id": uuid4(), "org": org, "site": site_a, "name": "Dry store"})
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            connection.execute(insert, {"id": uuid4(), "org": org, "site": site_b, "name": "Dry store"})
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(insert, {"id": uuid4(), "org": org, "site": site_b, "name": "Dry store"})
            # Areas without a site still share one name space.
            connection.execute(insert, {"id": uuid4(), "org": org, "site": None, "name": "Shed"})
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(insert, {"id": uuid4(), "org": org, "site": None, "name": "Shed"})
            # Going back would need one name per organisation: refused, nothing renamed.
            with pytest.raises(RuntimeError, match="Dry store"):
                migration.downgrade()
            connection.execute(text("DELETE FROM stock_locations WHERE site_id = :site"), {"site": site_b})
            migration.downgrade()
            assert connection.execute(text("SELECT count(*) FROM stock_locations")).scalar_one() == 2
        connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
