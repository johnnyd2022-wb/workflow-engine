"""Opt-in site foundations, isolation and staged operational safety (plan 7.1)."""

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError

from app.core.db.models.execution import Execution
from app.core.db.models.inventory_item import InventoryItem
from app.core.db.models.organisation import Organisation
from app.core.db.models.stock_location import StockLocation, StockTransfer
from app.core.db.models.user import UserRole
from app.core.db.repositories.execution_repo import ExecutionRepository
from app.core.db.repositories.inventory_repo import InventoryRepository
from app.core.db.site_guard import SiteScopeError
from app.core.security.tenant_scope import unscoped
from app.features.sites import service
from tests.dag_traversal_helpers import clear_org_synthetic_data
from tests.factories import InventoryItemFactory, ProcessFactory, UserFactory
from tests.test_compliant_routes import _admin_client, flask_app  # noqa: F401 -- fixture re-export


@pytest.fixture
def world(db, flask_app):  # noqa: F811
    org, admin = _admin_client(db, flask_app)
    other, neighbour = _admin_client(db, flask_app)
    yield org, admin, other, neighbour
    db.rollback()
    with unscoped():
        for org_id in (org.id, other.id):
            db.query(StockTransfer).filter(StockTransfer.org_id == org_id).delete(synchronize_session=False)
            clear_org_synthetic_data(db, org_id)
            db.query(StockLocation).filter(StockLocation.org_id == org_id).delete(synchronize_session=False)
            db.query(Organisation).filter(Organisation.id == org_id).delete(synchronize_session=False)
        db.commit()


def _enable(client):
    response = client.put("/api/core/sites/settings", json={"enabled": True})
    assert response.status_code == 200, response.get_json()
    return response.get_json()["sites"][0]


def _add(client, name="Bond store", **fields):
    response = client.post("/api/core/sites", json={"name": name, "kind": "storage", **fields})
    assert response.status_code == 201, response.get_json()
    return response.get_json()


def test_off_is_default_and_enabling_backfills_without_changing_stock(world, db):
    org, admin, other, _ = world
    initial = admin.get("/api/core/sites").get_json()
    assert initial["enabled"] is False and initial["sites"] == []
    assert admin.post("/api/core/sites", json={"name": "Bond"}).status_code == 400
    with unscoped():
        item = InventoryItemFactory(org_id=org.id, name="Opening bottles", quantity="40", unit="bottles")
        process = ProcessFactory(org_id=org.id)
        execution = ExecutionRepository(db).create_execution(org.id, process.id)
        location = StockLocation(org_id=org.id, name="Rep's car", inside_licensed_area=False)
        db.add(location)
        db.commit()
        # Simulate legacy rows awaiting enablement's compatibility backfill.
        for table in ("inventory_items", "executions", "stock_locations"):
            db.execute(text(f"UPDATE {table} SET site_id = NULL WHERE org_id = :org"), {"org": org.id})
        db.commit()
        db.expire_all()
        assert item.site_id is None and execution.site_id is None and location.site_id is None
    site = _enable(admin)
    with unscoped():
        db.expire_all()
        assert str(db.get(InventoryItem, item.id).site_id) == site["id"]
        assert str(db.get(Execution, execution.id).site_id) == site["id"]
        assert str(db.get(StockLocation, location.id).site_id) == site["id"]
        assert not db.get(StockLocation, location.id).inside_licensed_area
        assert db.get(InventoryItem, item.id).quantity == 40
        assert not db.get(Organisation, other.id).multiple_sites_enabled
    assert _enable(admin)["id"] == site["id"]
    position = admin.get(f"/api/core/sites/{site['id']}/position").get_json()
    assert position["stock"] == [
        {"inventory_type": "raw_material", "unit": "bottles", "quantity": "40.0000", "lots": 1}
    ]
    assert admin.put("/api/core/sites/settings", json={"enabled": False}).status_code == 200
    assert admin.get("/api/core/sites").get_json()["sites"] == []
    assert admin.get(f"/api/core/sites/{site['id']}/position").status_code == 400


def test_register_validates_fields_defaults_and_archiving(world):
    _, admin, _, _ = world
    default = _enable(admin)
    made = _add(admin, "  Bond store  ", address="18 Store Road")
    assert made["name"] == "Bond store" and made["operations_available"] is False
    for body in (
        {"name": "bond STORE"},
        {"name": ""},
        {"name": "x", "kind": "bad"},
        {"name": "x", "kind": []},
        {"name": "x", "address": 123},
        {"name": "x", "is_active": "false"},
        {"name": "x", "org_id": str(uuid4())},
        {"name": "x", "licence": "made up"},
    ):
        assert admin.post("/api/core/sites", json=body).status_code == 400
    assert admin.patch(f"/api/core/sites/{default['id']}", json={"is_active": False}).status_code == 400
    assert admin.patch(f"/api/core/sites/{default['id']}", json={"is_default": False}).status_code == 400
    assert admin.patch(f"/api/core/sites/{made['id']}", json={"is_active": False}).status_code == 200
    assert admin.patch(f"/api/core/sites/{made['id']}", json={"is_default": True}).status_code == 400
    switched = admin.patch(f"/api/core/sites/{made['id']}", json={"is_default": True, "is_active": True})
    assert switched.status_code == 200, switched.get_json()
    assert sum(site["is_default"] for site in admin.get("/api/core/sites").get_json()["sites"]) == 1
    # Percent/underscore in names are literal text, not ILIKE wildcards.
    assert admin.post("/api/core/sites", json={"name": "%"}).status_code == 201
    assert admin.post("/api/core/sites", json={"name": "_"}).status_code == 201


def test_default_cannot_change_after_any_operational_data(world, db):
    org, admin, _, _ = world
    default = _enable(admin)
    another = _add(admin)
    with unscoped():
        item = InventoryItemFactory(org_id=org.id)
        assert str(item.site_id) == default["id"]
    response = admin.patch(f"/api/core/sites/{another['id']}", json={"is_default": True})
    assert response.status_code == 400 and "cannot change" in response.get_json()["error"]
    assert admin.get("/api/core/sites").get_json()["sites"][0]["id"] == default["id"]


def test_site_register_and_position_are_tenant_scoped(world):
    _, admin, _, neighbour = world
    _enable(admin)
    theirs = _enable(neighbour)
    assert admin.patch(f"/api/core/sites/{theirs['id']}", json={"name": "Mine"}).status_code == 404
    assert admin.get(f"/api/core/sites/{theirs['id']}/position").status_code == 404
    assert admin.patch("/api/core/sites/not-a-uuid", json={"name": "x"}).status_code == 400
    for enabled in ("true", 1, None, []):
        assert admin.put("/api/core/sites/settings", json={"enabled": enabled}).status_code == 400
    assert admin.put("/api/core/sites/settings", json={"enabled": True, "org_id": str(uuid4())}).status_code == 400


def test_first_stock_and_default_switch_serialize(world):
    from app.core.db import SessionLocal

    org, admin, _, _ = world
    default = _enable(admin)
    another = _add(admin)
    with SessionLocal() as stock, SessionLocal() as settings, unscoped():
        location = StockLocation(org_id=org.id, name="First tank")
        stock.add(location)
        stock.flush()
        # A second connection cannot switch the default while first stock is pending.
        settings.execute(text("SET LOCAL statement_timeout = '400ms'"))
        target = service.get_site(settings, org.id, service.parse_id(another["id"]))
        with pytest.raises(OperationalError) as blocked:
            service.save_site(settings, org.id, {"is_default": True}, target)
        assert blocked.value.orig.pgcode == "57014"
        settings.rollback()
        stock.commit()
        target = service.get_site(settings, org.id, service.parse_id(another["id"]))
        with pytest.raises(SiteScopeError, match="cannot change"):
            service.save_site(settings, org.id, {"is_default": True}, target)
        settings.rollback()
        assert str(location.site_id) == default["id"]


def test_unsupported_site_hints_are_rejected_instead_of_ignored(world, db):
    org, admin, _, neighbour = world
    theirs = _enable(neighbour)
    assert admin.post("/api/core/inventory", json={"site_id": theirs["id"]}).status_code == 400
    default = _enable(admin)
    another = _add(admin)
    for site_id in (theirs["id"], another["id"], "bad", None):
        for path in ("/api/core/inventory", "/api/core/executions", "/api/core/stock-locations"):
            response = admin.post(path, json={"site_id": site_id})
            assert response.status_code == 400 and response.get_json()["code"] == "invalid_site_scope"
    location = admin.post(
        "/api/core/stock-locations", json={"name": "Tank bay", "site_id": default["id"], "inside_licensed_area": True}
    )
    assert location.status_code == 201
    with unscoped():
        assert str(db.get(StockLocation, location.get_json()["id"]).site_id) == default["id"]
        assert db.query(InventoryItem).filter(InventoryItem.org_id == org.id).count() == 0


def test_repository_and_flush_tags_cannot_bypass_staging_or_tenant(world, db):
    org, admin, other, neighbour = world
    default = _enable(admin)
    additional = _add(admin)
    theirs = _enable(neighbour)
    with unscoped():
        item = InventoryItemFactory(org_id=org.id)
        process = ProcessFactory(org_id=org.id)
        execution = ExecutionRepository(db).create_execution(org.id, process.id)
        assert str(item.site_id) == str(execution.site_id) == default["id"]
        assert InventoryRepository(db).list_inventory_items(org.id, site_id=service.parse_id(additional["id"])) == []
        assert ExecutionRepository(db).list_executions(org.id, site_id=service.parse_id(additional["id"])) == []
        for site_id in (service.parse_id(additional["id"]), service.parse_id(theirs["id"])):
            with pytest.raises(SiteScopeError):
                InventoryItemFactory(org_id=org.id, site_id=site_id)
            db.rollback()
            with pytest.raises(SiteScopeError):
                ExecutionRepository(db).create_execution(org.id, process.id, site_id=site_id)
            db.rollback()
        item = db.get(InventoryItem, item.id)
        item.site_id = None
        with pytest.raises(SiteScopeError, match="cannot be changed"):
            db.flush()
        db.rollback()
        bad = StockLocation(org_id=org.id, name="Wrong site", site_id=service.parse_id(theirs["id"]))
        db.add(bad)
        with pytest.raises(SiteScopeError):
            db.flush()
        db.rollback()


def test_database_rejects_cross_org_site_and_mismatched_location(world, db):
    org, admin, other, neighbour = world
    default = _enable(admin)
    theirs = _enable(neighbour)
    with unscoped():
        item = InventoryItemFactory(org_id=org.id)
        location = StockLocation(org_id=other.id, name="Other place")
        db.add(location)
        db.commit()
        for assignments in ("site_id = :site_id", "location_id = :location_id"):
            with pytest.raises(IntegrityError):
                db.execute(
                    text(f"UPDATE inventory_items SET {assignments} WHERE id = :id"),
                    {
                        "site_id": theirs["id"],
                        "location_id": location.id,
                        "id": item.id,
                    },
                )
                db.commit()
            db.rollback()
        assert str(db.get(InventoryItem, item.id).site_id) == default["id"]


def test_permissions_and_settings_page_link(world, db, flask_app):  # noqa: F811
    org, admin, _, _ = world
    default = _enable(admin)
    with unscoped():
        production = UserFactory(org_id=org.id, role=UserRole.PRODUCTION, email=f"floor-{uuid4()}@test.com")
    client = flask_app.test_client()
    client.environ_base["wsgi.url_scheme"] = "https"
    client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
    with client.session_transaction() as session:
        session["user_id"] = str(production.id)
    assert client.get("/api/core/sites").status_code == 200
    assert client.get(f"/api/core/sites/{default['id']}/position").status_code == 200
    assert client.put("/api/core/sites/settings", json={"enabled": False}).status_code == 403
    assert client.post("/api/core/sites", json={"name": "Forbidden"}).status_code == 403
    assert b"/core/sites" in admin.get("/core/settings").data
    assert b"/core/sites" not in client.get("/core/settings").data
    assert admin.get("/core/sites").status_code == 200
    assert admin.get("/static/sites/sites.js").status_code == 200


def test_migration_backfill_and_round_trip_in_an_isolated_schema():
    """Real DDL and old stock, without changing the application's current schema."""
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    from app.core.db import engine
    from app.core.db.migrations.versions import multiple_sites_001 as migration

    schema = "sites_migration_" + uuid4().hex
    org_id, item_id, location_id, execution_id = [uuid4() for _ in range(4)]
    with engine.connect() as connection, connection.begin():
        # The generated identifier contains only a fixed prefix and UUID hex.
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        connection.execute(text("CREATE TABLE organisations (id uuid PRIMARY KEY, name text NOT NULL)"))
        for table in ("stock_locations", "executions"):
            connection.execute(
                text(f"CREATE TABLE {table} (id uuid PRIMARY KEY, org_id uuid NOT NULL REFERENCES organisations(id))")
            )
        connection.execute(
            text(
                "CREATE TABLE inventory_items (id uuid PRIMARY KEY, org_id uuid NOT NULL REFERENCES organisations(id), location_id uuid REFERENCES stock_locations(id), quantity numeric(18,4))"
            )
        )
        connection.execute(text("INSERT INTO organisations VALUES (:id, 'Existing producer')"), {"id": org_id})
        connection.execute(text("INSERT INTO stock_locations VALUES (:id, :org)"), {"id": location_id, "org": org_id})
        connection.execute(text("INSERT INTO executions VALUES (:id, :org)"), {"id": execution_id, "org": org_id})
        connection.execute(
            text("INSERT INTO inventory_items VALUES (:id, :org, :location, 24)"),
            {"id": item_id, "org": org_id, "location": location_id},
        )
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            site_id = connection.execute(
                text("SELECT id FROM sites WHERE org_id = :org AND is_default"), {"org": org_id}
            ).scalar_one()
            for table in ("inventory_items", "executions", "stock_locations"):
                assert connection.execute(text(f"SELECT site_id FROM {table}")).scalar_one() == site_id
            assert connection.execute(text("SELECT quantity FROM inventory_items")).scalar_one() == 24
            assert connection.execute(text("SELECT multiple_sites_enabled FROM organisations")).scalar_one() is False
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    text("INSERT INTO sites (id, org_id, name, is_default) VALUES (:id, :org, 'Second default', true)"),
                    {"id": uuid4(), "org": org_id},
                )
            migration.downgrade()
            assert connection.execute(text("SELECT quantity FROM inventory_items")).scalar_one() == 24
            migration.upgrade()
        connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
