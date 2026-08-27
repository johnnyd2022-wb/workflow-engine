"""Tests for GET /api/core/hub/overview and its repository helpers.

This endpoint is the new single call the /core hub makes on first paint, replacing the
four-call fan-out (metrics + full processes + fully-enriched inventory + full execution
history). The risks it introduces, and what each test pins:

- tenant isolation on a brand-new aggregate surface -> `*_excludes_other_org`
- payload staying bounded as history grows -> `active_executions_capped`
- the SQL aggregates matching the predicates the old client-side JS used
  (non-zero quantity filter, expiry buckets, execution-link vs supplier-batch) ->
  `inventory_aggregates_*`
"""

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest

from app.core.db.models.execution import Execution, ExecutionStatus
from app.core.db.models.inventory_item import InventoryItem
from app.core.db.models.organisation import Organisation
from app.core.db.models.process import Process
from app.core.db.repositories.execution_repo import ExecutionRepository
from app.core.db.repositories.inventory_repo import InventoryRepository
from app.core.db.repositories.user_repo import UserRepository
from app.core.security.auth_service import AuthService
from tests.factories import (
    DEFAULT_TEST_PASSWORD,
    ExecutionFactory,
    InventoryItemFactory,
    OrganisationFactory,
    ProcessFactory,
)

PASSWORD = DEFAULT_TEST_PASSWORD
OVERVIEW = "/api/core/hub/overview"


def _make_org_and_client(db, flask_app):
    org = OrganisationFactory()
    db.commit()
    email = f"user_{uuid4()}@test.com"
    UserRepository(db).create_user(
        org_id=org.id,
        email=email,
        password_hash=AuthService.hash_password(PASSWORD),
        is_active=True,
    )
    db.commit()
    client = flask_app.test_client()
    client.environ_base["wsgi.url_scheme"] = "https"
    client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
    resp = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 200, resp.data
    return org, client


@pytest.fixture
def flask_app():
    from app.api.app_factory import create_app

    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.app_context():
        yield app


def _cleanup(db, org_ids):
    db.rollback()
    # inventory_items.source_execution_id FK-references executions, so items go first.
    db.query(InventoryItem).filter(InventoryItem.org_id.in_(org_ids)).delete(synchronize_session=False)
    db.query(Execution).filter(Execution.org_id.in_(org_ids)).delete(synchronize_session=False)
    db.query(Process).filter(Process.org_id.in_(org_ids)).delete(synchronize_session=False)
    db.query(Organisation).filter(Organisation.id.in_(org_ids)).delete(synchronize_session=False)
    db.commit()


@pytest.fixture
def authed(db, flask_app):
    org, client = _make_org_and_client(db, flask_app)
    yield org, client
    _cleanup(db, [org.id])


@pytest.fixture
def two_orgs(db, flask_app):
    org_a, client_a = _make_org_and_client(db, flask_app)
    org_b, client_b = _make_org_and_client(db, flask_app)
    yield {"org_a": org_a, "client_a": client_a, "org_b": org_b, "client_b": client_b}
    _cleanup(db, [org_a.id, org_b.id])


# --- route: auth + shape ---------------------------------------------------------------


def test_hub_overview_requires_auth(flask_app):
    client = flask_app.test_client()
    client.environ_base["wsgi.url_scheme"] = "https"
    client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
    assert client.get(OVERVIEW).status_code == 401


def test_hub_overview_shape_on_empty_org(authed):
    _org, client = authed
    body = client.get(OVERVIEW).get_json()

    assert set(body) == {"generated_at", "metrics", "journey", "inventory", "workflows"}
    assert body["metrics"]["inventory_items"] == {
        "total": 0,
        "raw_materials": 0,
        "work_in_progress": 0,
        "final_products": 0,
    }
    assert body["journey"] == {"has_inventory": False, "has_process": False, "has_execution": False}
    assert body["inventory"]["expiry"] == {"expired": 0, "d0_7": 0, "d8_30": 0, "d31_90": 0}
    assert body["inventory"]["traceability_gaps"] == []
    assert body["workflows"]["active_executions"] == []
    assert body["workflows"]["processes_min"] == []


def test_hub_overview_counts_reflect_seeded_data(db, authed):
    org, client = authed
    proc = ProcessFactory(org_id=org.id)
    ExecutionFactory(org_id=org.id, process_id=proc.id)  # PENDING == in-flight
    InventoryItemFactory(org_id=org.id, quantity="5", inventory_type="raw_material")
    InventoryItemFactory(org_id=org.id, quantity="0", inventory_type="final_product")  # empty -> excluded
    db.commit()

    body = client.get(OVERVIEW).get_json()
    assert body["metrics"]["total_processes"] == 1
    assert body["metrics"]["inventory_items"]["total"] == 2  # type counts are all rows...
    assert body["inventory"]["nonzero_lines"] == 1  # ...but aggregates drop the empty one
    assert body["workflows"]["in_flight"] == 1
    assert body["workflows"]["process_count"] == 1
    assert body["journey"] == {"has_inventory": True, "has_process": True, "has_execution": True}
    assert [p["name"] for p in body["workflows"]["processes_min"]] == [proc.name]


def test_hub_overview_active_executions_capped_and_slim(db, authed):
    org, client = authed
    proc = ProcessFactory(org_id=org.id)
    for _ in range(25):
        ExecutionFactory(org_id=org.id, process_id=proc.id)
    db.query(Execution).filter(Execution.org_id == org.id).update(
        {Execution.status: ExecutionStatus.IN_PROGRESS}, synchronize_session=False
    )
    db.commit()

    body = client.get(OVERVIEW).get_json()
    active = body["workflows"]["active_executions"]
    assert len(active) == 20, "payload must not grow with execution history"
    assert set(active[0]) == {
        "id",
        "process_id",
        "process_name",
        "status",
        "started_at",
        "current_step",
        "steps",
        "total_steps",
        "progress",
    }
    # completed count still reflects ALL rows, not the capped list
    assert body["metrics"]["active_executions"] == 25


# --- tenant isolation ----------------------------------------------------------------


def test_hub_overview_excludes_other_org(db, two_orgs):
    b = two_orgs["org_b"]
    proc_b = ProcessFactory(org_id=b.id)
    ExecutionFactory(org_id=b.id, process_id=proc_b.id)
    InventoryItemFactory(org_id=b.id, quantity="9", supplier_batch_number=None, source_execution_id=None)
    db.commit()

    body = two_orgs["client_a"].get(OVERVIEW).get_json()
    assert body["metrics"]["total_processes"] == 0
    assert body["metrics"]["inventory_items"]["total"] == 0
    assert body["workflows"]["in_flight"] == 0
    assert body["workflows"]["active_executions"] == []
    assert body["workflows"]["processes_min"] == []
    assert body["inventory"]["nonzero_lines"] == 0
    assert body["inventory"]["traceability_gaps"] == []

    # control: org B does see its own row
    body_b = two_orgs["client_b"].get(OVERVIEW).get_json()
    assert body_b["metrics"]["total_processes"] == 1
    assert body_b["workflows"]["in_flight"] == 1


# --- inventory aggregates (repo level, faster to assert precisely) ------------------


def test_inventory_aggregates_nonzero_and_link_predicates(db):
    org = OrganisationFactory()
    db.commit()
    exec_owner = ProcessFactory(org_id=org.id)
    ex = ExecutionFactory(org_id=org.id, process_id=exec_owner.id)
    db.commit()

    InventoryItemFactory(org_id=org.id, quantity="4", source_execution_id=ex.id)  # allocated + linked
    InventoryItemFactory(org_id=org.id, quantity="4", supplier_batch_number="LOT-1")  # linked only
    InventoryItemFactory(org_id=org.id, quantity="4")  # gap
    InventoryItemFactory(org_id=org.id, quantity="0", source_execution_id=ex.id)  # empty -> ignored
    db.commit()

    agg = InventoryRepository(db).hub_overview_aggregates(org.id, date.today())
    assert agg["nonzero_lines"] == 3
    assert agg["allocated"] == 1
    assert agg["linked"] == 2
    assert agg["low_stock"] == 0

    gaps = InventoryRepository(db).list_traceability_gap_items(org.id, limit=6)
    assert len(gaps) == 1

    _cleanup_repo(db, org.id)


def test_inventory_aggregates_expiry_buckets(db):
    org = OrganisationFactory()
    db.commit()
    today = date.today()
    for days in (-3, 2, 20, 60, 200):
        InventoryItemFactory(org_id=org.id, quantity="2", expiry_date=today + timedelta(days=days))
    InventoryItemFactory(org_id=org.id, quantity="0", expiry_date=today - timedelta(days=1))  # empty
    db.commit()

    expiry = InventoryRepository(db).hub_overview_aggregates(org.id, today)["expiry"]
    assert expiry == {"expired": 1, "d0_7": 1, "d8_30": 1, "d31_90": 1}  # the +200 one is in no bucket
    _cleanup_repo(db, org.id)


def test_active_execution_summaries_orders_by_recency_and_limits(db):
    org = OrganisationFactory()
    db.commit()
    proc = ProcessFactory(org_id=org.id)
    for _ in range(5):
        ExecutionFactory(org_id=org.id, process_id=proc.id)
    db.query(Execution).filter(Execution.org_id == org.id).update(
        {Execution.status: ExecutionStatus.IN_PROGRESS}, synchronize_session=False
    )
    db.commit()

    got = ExecutionRepository(db).list_active_execution_summaries(org.id, limit=3)
    assert len(got) == 3
    updated = [e.updated_at for e in got]
    assert updated == sorted(updated, reverse=True)
    _cleanup_repo(db, org.id)


def test_movement_totals_since_is_org_scoped_and_windowed(db):
    from app.core.db.models.inventory_movement import InventoryMovement

    org = OrganisationFactory()
    other = OrganisationFactory()
    db.commit()
    item = InventoryItemFactory(org_id=org.id, quantity="10")
    db.commit()
    now = datetime.now(UTC)
    db.add_all(
        [
            InventoryMovement(
                org_id=org.id,
                inventory_item_id=item.id,
                movement_type="adjustment",
                quantity=5,
                unit="kg",
                created_at=now - timedelta(hours=1),
            ),
            InventoryMovement(
                org_id=org.id,
                inventory_item_id=item.id,
                movement_type="adjustment",
                quantity=-2,
                unit="kg",
                created_at=now - timedelta(hours=2),
            ),
            InventoryMovement(
                org_id=org.id,
                inventory_item_id=item.id,
                movement_type="adjustment",
                quantity=99,
                unit="kg",
                created_at=now - timedelta(days=3),  # outside 24h window
            ),
        ]
    )
    db.commit()

    totals = InventoryRepository(db).movement_totals_since(org.id, now - timedelta(days=1))
    assert totals == {"net": 3.0, "abs": 7.0, "events": 2}
    assert InventoryRepository(db).movement_totals_since(other.id, now - timedelta(days=1)) == {
        "net": 0.0,
        "abs": 0.0,
        "events": 0,
    }

    db.query(InventoryMovement).filter(InventoryMovement.org_id == org.id).delete(synchronize_session=False)
    db.commit()
    _cleanup_repo(db, org.id)
    _cleanup_repo(db, other.id)


def test_throughput_7d_is_keyed_by_process_id_not_name(db, authed):
    """Two processes sharing a name must not have their 7-day completions merged into one
    row -- the graph attributes throughput by process_id, and names are not unique."""
    org, client = authed
    p1 = ProcessFactory(org_id=org.id, name="Gin Run")
    p2 = ProcessFactory(org_id=org.id, name="Gin Run")  # same name, different id
    for proc, n in ((p1, 1), (p2, 3)):
        for _ in range(n):
            ExecutionFactory(org_id=org.id, process_id=proc.id)
    db.query(Execution).filter(Execution.org_id == org.id).update(
        {Execution.status: ExecutionStatus.COMPLETED, Execution.completed_at: datetime.now(UTC)},
        synchronize_session=False,
    )
    db.commit()

    rows = client.get(OVERVIEW).get_json()["workflows"]["throughput_7d"]
    by_id = {r["process_id"]: r["count"] for r in rows}
    assert by_id[str(p1.id)] == 1
    assert by_id[str(p2.id)] == 3
    assert all("process_id" in r and "name" in r and "count" in r for r in rows)


def test_processes_min_always_contains_active_execution_processes(db, authed, monkeypatch):
    """A process that owns an active execution must be in processes_min even when it is
    older than the newest HUB_PROCESSES_MIN_CAP processes -- otherwise the active-batches
    panel shows a batch the picker cannot select."""
    from app.core.backend import backend as backend_mod

    monkeypatch.setattr(backend_mod, "HUB_PROCESSES_MIN_CAP", 3)
    org, client = authed

    old_proc = ProcessFactory(org_id=org.id, name="Legacy line")
    ex = ExecutionFactory(org_id=org.id, process_id=old_proc.id)
    db.query(Execution).filter(Execution.id == ex.id).update(
        {Execution.status: ExecutionStatus.IN_PROGRESS}, synchronize_session=False
    )
    # 5 newer processes -> old_proc is well outside the cap of 3
    for _ in range(5):
        ProcessFactory(org_id=org.id)
    db.commit()

    wf = client.get(OVERVIEW).get_json()["workflows"]
    ids = {p["id"] for p in wf["processes_min"]}
    assert str(old_proc.id) in ids, "active execution's process dropped from the picker"
    # cap still bounds the newest-process fill (1 forced active + up to 3 newest here)
    assert len(wf["processes_min"]) <= 4


def _cleanup_repo(db, org_id):
    db.rollback()
    db.query(InventoryItem).filter(InventoryItem.org_id == org_id).delete(synchronize_session=False)
    db.query(Execution).filter(Execution.org_id == org_id).delete(synchronize_session=False)
    db.query(Process).filter(Process.org_id == org_id).delete(synchronize_session=False)
    db.query(Organisation).filter(Organisation.id == org_id).delete(synchronize_session=False)
    db.commit()
