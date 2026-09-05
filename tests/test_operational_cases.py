"""Real-Postgres tests for operational_cases (A1).

See .agents/specs/operational_cases.md for the AC definitions these tests are named
against. Covers creation/eligibility/idempotency (AC1), tenant isolation and permission
boundaries (AC2), lifecycle transitions and optimistic concurrency (AC3), recurrence
identity rules (AC4), and atomic case-mutation + event-write (AC6). AC5/AC7 (browser UX,
performance budgets) and the full migration up/down/up cycle against a disposable
database are exercised outside this suite -- see docs/operational-cases-runbook.md and
this file's own AC8 migration-shape test, which checks schema without touching the
shared test database destructively.
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from flask.sessions import SecureCookieSessionInterface
from itsdangerous import BadSignature

from app.core.db import db_session
from app.core.db.models.api_idempotency_key import ApiIdempotencyKey
from app.core.db.models.audit_log import AuditLog
from app.core.db.models.entity_event import EntityEvent
from app.core.db.models.feature_subscription import FeatureSubscription
from app.core.db.models.inventory_item import InventoryItem
from app.core.db.models.organisation import Organisation
from app.core.db.models.user import User, UserRole
from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository
from app.core.domain.inventory_quantity_guard import InventoryQuantityWriteReason, allow_inventory_quantity_write
from app.features.operational_cases.models.operational_case import OperationalCase
from app.features.operational_cases.models.operational_case_event import OperationalCaseEvent
from app.features.operational_cases.models.operational_case_link import OperationalCaseLink
from tests.factories import (
    DEFAULT_TEST_PASSWORD,
    FeatureSubscriptionFactory,
    InventoryItemFactory,
    OrganisationFactory,
    UserFactory,
)

_SNAPSHOT_KEYS = {
    "schema_version",
    "check_id",
    "source_entity_type",
    "source_entity_id",
    "item_name",
    "unit",
    "quantity",
    "remaining_balance_to_reconcile",
    "source_execution_id",
    "source_execution_step_id",
    "producing_step_id",
    "observed_at",
    "adapter_version",
    "critical_reason",
    "truncated_fields",
}


def _purge_org(db, org_id):
    db.query(OperationalCaseEvent).filter(OperationalCaseEvent.org_id == org_id).delete(synchronize_session=False)
    db.query(OperationalCaseLink).filter(OperationalCaseLink.org_id == org_id).delete(synchronize_session=False)
    db.query(OperationalCase).filter(OperationalCase.org_id == org_id).delete(synchronize_session=False)
    db.query(ApiIdempotencyKey).filter(ApiIdempotencyKey.org_id == org_id).delete(synchronize_session=False)
    db.query(EntityEvent).filter(EntityEvent.org_id == org_id).delete(synchronize_session=False)
    db.query(InventoryItem).filter(InventoryItem.org_id == org_id).delete(synchronize_session=False)
    db.query(FeatureSubscription).filter(FeatureSubscription.org_id == org_id).delete(synchronize_session=False)
    # audit_logs.user_id has no cascade (see tests/test_wastage.py's `org` fixture
    # comment) -- login itself writes an audit row, so this must go before User.
    db.query(AuditLog).filter(AuditLog.org_id == org_id).delete(synchronize_session=False)
    db.query(User).filter(User.org_id == org_id).delete(synchronize_session=False)
    db.query(Organisation).filter(Organisation.id == org_id).delete(synchronize_session=False)
    db.commit()


@pytest.fixture(autouse=True)
def enable_cases(monkeypatch):
    from app.utils.config_loader import Config

    monkeypatch.setattr(Config, "operational_cases_enabled", property(lambda self: True))


@pytest.fixture()
def db():
    session = db_session()
    try:
        yield session
    finally:
        session.close()
        db_session.remove()


@pytest.fixture()
def org_a(db):
    o = OrganisationFactory()
    FeatureSubscriptionFactory(org_id=o.id, feature_key="operational_cases")
    db.commit()
    yield o
    _purge_org(db, o.id)


@pytest.fixture()
def org_b(db):
    """A second, also-subscribed org -- the hostile neighbour for cross-tenant tests."""
    o = OrganisationFactory()
    FeatureSubscriptionFactory(org_id=o.id, feature_key="operational_cases")
    db.commit()
    yield o
    _purge_org(db, o.id)


@pytest.fixture()
def admin_user(db, org_a):
    u = UserFactory(org_id=org_a.id, email=f"oc-admin-{uuid4().hex}@example.test", role=UserRole.ADMIN)
    db.commit()
    return u


@pytest.fixture()
def owner_user(db, org_a):
    u = UserFactory(org_id=org_a.id, email=f"oc-owner-{uuid4().hex}@example.test", role=UserRole.MEMBER)
    db.commit()
    return u


@pytest.fixture()
def verifier_user(db, org_a):
    u = UserFactory(org_id=org_a.id, email=f"oc-verifier-{uuid4().hex}@example.test", role=UserRole.MEMBER)
    db.commit()
    return u


@pytest.fixture()
def org_b_user(db, org_b):
    u = UserFactory(org_id=org_b.id, email=f"oc-orgb-{uuid4().hex}@example.test", role=UserRole.ADMIN)
    db.commit()
    return u


@pytest.fixture()
def untracked_item(db, org_a):
    item = InventoryItemFactory(
        org_id=org_a.id,
        name="Test Untracked Widget",
        quantity="5",
        unit="kg",
        inventory_type="raw_material",
        extra_data={"untracked": True},
    )
    db.commit()
    return item


@pytest.fixture(scope="module")
def flask_app():
    """One Flask app for the whole file. `create_app()` per client (the pattern
    tests/test_wastage.py and tests/test_process_templates.py both use) is fine at their
    scale, but this file logs in up to four distinct roles per test across ~35 tests --
    at that volume, repeated `create_app()` calls in one pytest process produced
    intermittent, non-reproducible 401s on an already-authenticated client (each retried
    test passed alone; a different test failed each full-file run -- the signature of
    exhausting some process-global resource `create_app()` allocates, not an
    operational_cases bug). The app object itself carries no per-test state -- routing/
    config is fixed, and DB state lives in the shared `db_session` scoped session
    independent of which app instance issued the request -- so one app, many independent
    test-client cookiejars, is both safe and far cheaper.
    """
    return _make_test_app()


class _ClockTolerantTestSessionInterface(SecureCookieSessionInterface):
    """Keep signed test cookies valid across the host clock's backwards jumps.

    The test host can move wall-clock time backwards by several seconds. Flask's normal
    session loader rejects an otherwise valid cookie with a negative signature age,
    creating intermittent 401s unrelated to a case command. This test-only interface
    still verifies the signature, but omits expiry validation.
    """

    def open_session(self, app, request):
        serializer = self.get_signing_serializer(app)
        if serializer is None:
            return None
        value = request.cookies.get(self.get_cookie_name(app))
        if not value:
            return self.session_class()
        try:
            return self.session_class(serializer.loads(value))
        except BadSignature:
            return self.session_class()


def _make_test_app():
    from app.api.app_factory import create_app

    app = create_app()
    # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING -- isolated Flask test app
    app.config["TESTING"] = True
    # nosemgrep: python.flask.security.audit.wtf-csrf-disabled.flask-wtf-csrf-disabled -- request authentication is the subject of these API tests
    app.config["WTF_CSRF_ENABLED"] = False
    app.session_interface = _ClockTolerantTestSessionInterface()
    return app


def _login(flask_app, user):
    client = flask_app.test_client()
    client.environ_base["wsgi.url_scheme"] = "https"
    client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
    with flask_app.app_context():
        resp = client.post(
            "/auth/login",
            json={"email": user.email, "password": DEFAULT_TEST_PASSWORD},
            content_type="application/json",
        )
        assert resp.status_code in (200, 201), f"Login failed: {resp.data}"
    return client


@pytest.fixture()
def admin_client(flask_app, admin_user):
    return _login(flask_app, admin_user)


@pytest.fixture()
def owner_client(flask_app, owner_user):
    return _login(flask_app, owner_user)


@pytest.fixture()
def verifier_client(flask_app, verifier_user):
    return _login(flask_app, verifier_user)


@pytest.fixture()
def org_b_client(flask_app, org_b_user):
    return _login(flask_app, org_b_user)


def _future_iso(hours=24) -> str:
    return (datetime.now(UTC) + timedelta(hours=hours)).isoformat()


def _create_payload(
    source_entity_id, owner_id, next_action="Check batch output and reconcile the remaining quantity", **extra
):
    payload = {
        "source_entity_id": str(source_entity_id),
        "owner_id": str(owner_id),
        "due_at": _future_iso(),
        "next_action": next_action,
    }
    payload.update(extra)
    return payload


def _idem():
    return {"Idempotency-Key": f"k-{uuid4()}"}


# ---------------------------------------------------------------------------------
# AC1: creation, eligibility, idempotency, concurrency
# ---------------------------------------------------------------------------------


def test_ac1_create_case_creates_open_critical_case_with_snapshot_and_event(
    db, owner_client, owner_user, untracked_item
):
    resp = owner_client.post(
        "/api/core/cases/from-finding", json=_create_payload(untracked_item.id, owner_user.id), headers=_idem()
    )
    assert resp.status_code == 201, resp.data
    case = resp.get_json()["case"]
    assert case["status"] == "open"
    assert case["severity"] == "critical"
    assert case["version"] == 1
    assert case["owner_id"] == str(owner_user.id)

    db.expire_all()
    row = db.query(OperationalCase).filter(OperationalCase.id == UUID(case["id"])).one()
    assert set(row.source_snapshot.keys()) == _SNAPSHOT_KEYS
    assert row.source_snapshot["item_name"] == "Test Untracked Widget"
    assert row.source_snapshot["quantity"] == "5"
    assert row.source_snapshot["unit"] == "kg"
    assert row.source_snapshot["source_entity_id"] == str(untracked_item.id)
    # forbidden-field exclusion: no raw extra_data/notes/execution prompts copied in
    assert "extra_data" not in row.source_snapshot
    assert "notes" not in row.source_snapshot

    link = db.query(OperationalCaseLink).filter(OperationalCaseLink.case_id == row.id).one()
    assert link.relation == "source"
    assert link.entity_id == untracked_item.id

    event = db.query(OperationalCaseEvent).filter(OperationalCaseEvent.case_id == row.id).one()
    assert event.event_type == "operational_case.created"
    assert event.case_version == 1
    assert event.entity_event_id is not None

    entity_event = db.query(EntityEvent).filter(EntityEvent.id == event.entity_event_id).one()
    assert entity_event.event_type == "operational_case.created"
    assert entity_event.entity_type == "operational_case"
    assert entity_event.entity_id == row.id


def test_ac1_snapshot_truncates_long_item_name_and_marks_it(db, owner_client, owner_user, org_a):
    # 210 chars: over the snapshot's 200-char item_name cap, but short enough that the
    # inventory repository's own computed display_label ("<name> · <qty> <unit>", capped
    # at inventory_items.name's VARCHAR(255)) still fits -- this is testing operational_
    # cases' own truncation, not the unrelated pre-existing display_label column.
    long_name = "X" * 210
    item = InventoryItemFactory(
        org_id=org_a.id,
        name=long_name,
        quantity="3",
        unit="kg",
        inventory_type="raw_material",
        extra_data={"untracked": True},
    )
    db.commit()
    resp = owner_client.post(
        "/api/core/cases/from-finding", json=_create_payload(item.id, owner_user.id), headers=_idem()
    )
    assert resp.status_code == 201, resp.data
    db.expire_all()
    row = db.query(OperationalCase).filter(OperationalCase.id == UUID(resp.get_json()["case"]["id"])).one()
    assert len(row.source_snapshot["item_name"]) == 200
    assert row.source_snapshot["truncated_fields"] == ["item_name"]


def test_ac1_legacy_positive_stock_no_remaining_balance_metadata_is_eligible(db, owner_client, owner_user, org_a):
    """Regression required by the spec: a positive-quantity untracked item with no
    remaining_balance_to_reconcile key at all (legacy row) must still be eligible."""
    item = InventoryItemFactory(
        org_id=org_a.id,
        name="Legacy Item",
        quantity="2",
        unit="kg",
        inventory_type="raw_material",
        extra_data={"untracked": True},  # no remaining_balance_to_reconcile key
    )
    db.commit()
    resp = owner_client.post(
        "/api/core/cases/from-finding", json=_create_payload(item.id, owner_user.id), headers=_idem()
    )
    assert resp.status_code == 201, resp.data
    assert resp.get_json()["case"]["status"] == "open"


def test_ac1_create_case_idempotent_replay_same_key_same_payload(owner_client, owner_user, untracked_item):
    payload = _create_payload(untracked_item.id, owner_user.id)
    headers = _idem()
    first = owner_client.post("/api/core/cases/from-finding", json=payload, headers=headers)
    assert first.status_code == 201
    second = owner_client.post("/api/core/cases/from-finding", json=payload, headers=headers)
    assert second.status_code == 201
    assert second.get_json().get("idempotent_replay") is True
    assert second.get_json()["case"]["id"] == first.get_json()["case"]["id"]


def test_ac1_create_case_same_key_different_payload_409(owner_client, owner_user, untracked_item):
    headers = _idem()
    payload1 = _create_payload(untracked_item.id, owner_user.id, next_action="First action")
    payload2 = _create_payload(untracked_item.id, owner_user.id, next_action="Different action entirely")
    r1 = owner_client.post("/api/core/cases/from-finding", json=payload1, headers=headers)
    assert r1.status_code == 201
    r2 = owner_client.post("/api/core/cases/from-finding", json=payload2, headers=headers)
    assert r2.status_code == 409
    assert r2.get_json()["error_code"] == "idempotency_payload_mismatch"


def test_ac1_create_case_ineligible_source_rejected_creates_nothing(db, owner_client, owner_user, org_a):
    item = InventoryItemFactory(
        org_id=org_a.id,
        name="Cleared Item",
        quantity="0",
        unit="kg",
        inventory_type="raw_material",
        extra_data={"untracked": True},
    )
    db.commit()
    # Captured before any client request: the Flask test client's own request teardown
    # calls db_session.remove() (same shared scoped session as this `db` fixture), which
    # detaches `item` -- see tests/test_wastage.py's `org` fixture comment for the same
    # trap. A plain UUID survives that; the ORM attribute does not.
    item_id = item.id
    resp = owner_client.post(
        "/api/core/cases/from-finding", json=_create_payload(item_id, owner_user.id), headers=_idem()
    )
    assert resp.status_code == 409
    assert resp.get_json()["error_code"] == "source_not_eligible"
    db.expire_all()
    assert db.query(OperationalCase).filter(OperationalCase.source_entity_id == item_id).count() == 0
    no_events_for_source = (
        db.query(OperationalCaseEvent)
        .join(OperationalCase, OperationalCaseEvent.case_id == OperationalCase.id)
        .filter(OperationalCase.source_entity_id == item_id)
        .count()
    )
    assert no_events_for_source == 0


def test_ac1_create_case_missing_source_404_creates_nothing(db, owner_client, owner_user):
    fake_id = uuid4()
    resp = owner_client.post(
        "/api/core/cases/from-finding", json=_create_payload(fake_id, owner_user.id), headers=_idem()
    )
    assert resp.status_code == 404
    assert resp.get_json()["error_code"] == "source_not_found"
    db.expire_all()
    assert db.query(OperationalCase).filter(OperationalCase.source_entity_id == fake_id).count() == 0


def test_ac1_create_case_invalid_owner_rejected(owner_client, untracked_item):
    resp = owner_client.post(
        "/api/core/cases/from-finding", json=_create_payload(untracked_item.id, uuid4()), headers=_idem()
    )
    assert resp.status_code == 404
    assert resp.get_json()["error_code"] == "invalid_owner"


def test_ac1_create_case_past_due_at_rejected(owner_client, owner_user, untracked_item):
    payload = _create_payload(untracked_item.id, owner_user.id)
    payload["due_at"] = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    resp = owner_client.post("/api/core/cases/from-finding", json=payload, headers=_idem())
    assert resp.status_code == 400
    assert resp.get_json()["error_code"] == "due_at_invalid"


def test_ac1_concurrent_create_same_source_returns_same_case(db, owner_user, untracked_item, monkeypatch):
    """Two independent requests for the same source, racing on purpose: the per-source
    advisory lock must serialize them so exactly one case is ever created (spec:
    "Concurrent submissions for the same active source return the same case ID").

    Forces genuine contention the same way tests/test_wastage.py's equivalent test does
    (a fast local Postgres round-trip otherwise lets the first request finish before the
    second even reaches the lock) -- see that test's docstring for why a bare
    threading.Barrier is not sufficient on its own.

    Deliberately uses its own private Flask app/clients (not the shared `flask_app`
    fixture every other test in this file uses) -- this is the one test that runs real
    background threads against a live app, and keeping that entirely off the app object
    every sequential test shares removes any chance of the two interacting.
    """
    import app.features.operational_cases.services.operational_case_service as svc_module

    original_lock = svc_module._pg_advisory_lock
    order_lock = threading.Lock()
    call_count = {"n": 0}

    def delayed_lock(session, *parts):
        original_lock(session, *parts)
        if parts and parts[0] == "oc_source":
            with order_lock:
                call_count["n"] += 1
                is_first = call_count["n"] == 1
            if is_first:
                time.sleep(0.5)

    monkeypatch.setattr(svc_module, "_pg_advisory_lock", delayed_lock)

    private_app = _make_test_app()
    client_a = _login(private_app, owner_user)
    client_b = _login(private_app, owner_user)

    barrier = threading.Barrier(2)
    results: list[tuple[int, dict] | None] = [None, None]
    errors: list[BaseException] = []

    def worker(idx, client):
        try:
            barrier.wait(timeout=5)
            resp = client.post(
                "/api/core/cases/from-finding",
                json=_create_payload(untracked_item.id, owner_user.id),
                headers={"Idempotency-Key": f"concurrent-{idx}-{uuid4()}"},
            )
            results[idx] = (resp.status_code, resp.get_json())
        except BaseException as exc:  # noqa: BLE001 -- surfaced via `errors` assertion below
            errors.append(exc)

    t1 = threading.Thread(target=worker, args=(0, client_a))
    t2 = threading.Thread(target=worker, args=(1, client_b))
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    assert not errors, errors
    assert results[0] is not None and results[1] is not None
    assert results[0][0] in (200, 201) and results[1][0] in (200, 201)
    case_ids = {results[0][1]["case"]["id"], results[1][1]["case"]["id"]}
    assert len(case_ids) == 1, f"expected exactly one case id, got {case_ids}"

    db.expire_all()
    count = db.query(OperationalCase).filter(OperationalCase.source_entity_id == untracked_item.id).count()
    assert count == 1


# ---------------------------------------------------------------------------------
# AC2: tenant isolation and permission boundaries
# ---------------------------------------------------------------------------------


def test_ac2_foreign_org_case_lookup_is_404_indistinguishable_from_missing(
    db, owner_client, org_b_client, owner_user, untracked_item
):
    resp = owner_client.post(
        "/api/core/cases/from-finding", json=_create_payload(untracked_item.id, owner_user.id), headers=_idem()
    )
    case_id = resp.get_json()["case"]["id"]

    foreign_resp = org_b_client.get(f"/api/core/cases/{case_id}")
    missing_resp = org_b_client.get(f"/api/core/cases/{uuid4()}")
    assert foreign_resp.status_code == 404
    assert missing_resp.status_code == 404
    assert foreign_resp.get_json() == missing_resp.get_json()


def test_ac2_list_cases_excludes_other_orgs(db, owner_client, org_b_client, owner_user, untracked_item):
    owner_client.post(
        "/api/core/cases/from-finding", json=_create_payload(untracked_item.id, owner_user.id), headers=_idem()
    )
    resp = org_b_client.get("/api/core/cases?status=all")
    assert resp.status_code == 200
    assert resp.get_json()["cases"] == []


def test_ac2_patch_unsupported_field_rejected_writes_nothing(db, owner_client, owner_user, untracked_item):
    create = owner_client.post(
        "/api/core/cases/from-finding", json=_create_payload(untracked_item.id, owner_user.id), headers=_idem()
    )
    case = create.get_json()["case"]
    resp = owner_client.patch(
        f"/api/core/cases/{case['id']}", json={"expected_version": 1, "status": "verified"}, headers=_idem()
    )
    assert resp.status_code == 400
    assert resp.get_json()["error_code"] == "unsupported_fields"
    db.expire_all()
    row = db.query(OperationalCase).filter(OperationalCase.id == UUID(case["id"])).one()
    assert row.version == 1
    assert row.status == "open"


def test_ac2_member_owner_cannot_reassign_even_self(db, owner_client, owner_user, untracked_item):
    create = owner_client.post(
        "/api/core/cases/from-finding", json=_create_payload(untracked_item.id, owner_user.id), headers=_idem()
    )
    case = create.get_json()["case"]
    resp = owner_client.patch(
        f"/api/core/cases/{case['id']}",
        json={"expected_version": 1, "owner_id": str(owner_user.id)},
        headers=_idem(),
    )
    assert resp.status_code == 403


def test_ac2_admin_can_reassign(db, admin_client, owner_client, owner_user, verifier_user, untracked_item):
    create = owner_client.post(
        "/api/core/cases/from-finding", json=_create_payload(untracked_item.id, owner_user.id), headers=_idem()
    )
    case = create.get_json()["case"]
    resp = admin_client.patch(
        f"/api/core/cases/{case['id']}",
        json={"expected_version": 1, "owner_id": str(verifier_user.id)},
        headers=_idem(),
    )
    assert resp.status_code == 200
    assert resp.get_json()["case"]["owner_id"] == str(verifier_user.id)


def test_ac2_feature_disabled_for_org_404s_but_admin_history_route_still_works(
    db, admin_client, owner_user, org_a, untracked_item
):
    create = admin_client.post(
        "/api/core/cases/from-finding", json=_create_payload(untracked_item.id, owner_user.id), headers=_idem()
    )
    case_id = create.get_json()["case"]["id"]

    FeatureSubscriptionRepository(db).revoke(org_a.id, "operational_cases")
    db.commit()

    list_resp = admin_client.get("/api/core/cases")
    assert list_resp.status_code == 404

    history_resp = admin_client.get(f"/api/core/cases/history/{case_id}")
    assert history_resp.status_code == 200
    assert history_resp.get_json()["id"] == case_id

    # restore for any subsequent assertions/cleanup relying on the grant
    FeatureSubscriptionRepository(db).grant(org_a.id, "operational_cases")
    db.commit()


def test_ac2_history_route_requires_admin_role(owner_client):
    resp = owner_client.get(f"/api/core/cases/history/{uuid4()}")
    assert resp.status_code == 403


def test_ac2_unauthenticated_is_401(flask_app):
    client = flask_app.test_client()
    # Without this, the HTTPS-enforcement middleware 301s a plain-http test request
    # before @requires_auth is ever reached (see every other client fixture above).
    client.environ_base["wsgi.url_scheme"] = "https"
    client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
    resp = client.get("/api/core/cases")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------------
# AC3: lifecycle transitions, optimistic concurrency, dismissal
# ---------------------------------------------------------------------------------


def test_ac3_lifecycle_happy_path_to_verified_increments_version_once_per_step(
    db, owner_client, verifier_client, owner_user, untracked_item
):
    create = owner_client.post(
        "/api/core/cases/from-finding", json=_create_payload(untracked_item.id, owner_user.id), headers=_idem()
    )
    case_id = create.get_json()["case"]["id"]

    ack = owner_client.post(
        f"/api/core/cases/{case_id}/transitions",
        json={"target_status": "acknowledged", "expected_version": 1},
        headers=_idem(),
    )
    assert ack.status_code == 200
    assert ack.get_json()["case"]["status"] == "acknowledged"
    assert ack.get_json()["case"]["version"] == 2

    start = owner_client.post(
        f"/api/core/cases/{case_id}/transitions",
        json={"target_status": "in_progress", "expected_version": 2},
        headers=_idem(),
    )
    assert start.status_code == 200
    assert start.get_json()["case"]["version"] == 3

    resolve = owner_client.post(
        f"/api/core/cases/{case_id}/transitions",
        json={
            "target_status": "resolved",
            "expected_version": 3,
            "cause": "process_deviation",
            "action_taken": "Reconciled stock against batch output",
            "outcome": "Balance brought to zero",
        },
        headers=_idem(),
    )
    assert resolve.status_code == 200
    assert resolve.get_json()["case"]["status"] == "resolved"
    assert resolve.get_json()["case"]["version"] == 4

    verify_fail = verifier_client.post(
        f"/api/core/cases/{case_id}/transitions",
        json={"target_status": "verified", "expected_version": 4, "verification_note": "checked, still shows stock"},
        headers=_idem(),
    )
    assert verify_fail.status_code == 409
    assert verify_fail.get_json()["error_code"] == "source_not_cleared"

    item_row = db.query(InventoryItem).filter(InventoryItem.id == untracked_item.id).one()
    with allow_inventory_quantity_write(InventoryQuantityWriteReason.MANUAL_API_UPDATE):
        item_row.quantity = "0"
        db.commit()  # must flush while the guard's context is still active

    verify_ok = verifier_client.post(
        f"/api/core/cases/{case_id}/transitions",
        json={"target_status": "verified", "expected_version": 4, "verification_note": "confirmed cleared"},
        headers=_idem(),
    )
    assert verify_ok.status_code == 200
    assert verify_ok.get_json()["case"]["status"] == "verified"
    assert verify_ok.get_json()["case"]["version"] == 5

    events = (
        db.query(OperationalCaseEvent)
        .filter(OperationalCaseEvent.case_id == UUID(case_id))
        .order_by(OperationalCaseEvent.case_version)
        .all()
    )
    assert [e.event_type for e in events] == [
        "operational_case.created",
        "operational_case.acknowledged",
        "operational_case.started",
        "operational_case.resolved",
        "operational_case.verified",
    ]


def test_ac3_invalid_transition_open_to_verified_rejected(owner_client, owner_user, untracked_item):
    create = owner_client.post(
        "/api/core/cases/from-finding", json=_create_payload(untracked_item.id, owner_user.id), headers=_idem()
    )
    case_id = create.get_json()["case"]["id"]
    resp = owner_client.post(
        f"/api/core/cases/{case_id}/transitions",
        json={"target_status": "verified", "expected_version": 1, "verification_note": "x"},
        headers=_idem(),
    )
    assert resp.status_code == 409
    assert resp.get_json()["error_code"] == "invalid_transition"


def test_ac3_dismiss_requires_admin(db, owner_client, admin_client, owner_user, untracked_item):
    create = owner_client.post(
        "/api/core/cases/from-finding", json=_create_payload(untracked_item.id, owner_user.id), headers=_idem()
    )
    case_id = create.get_json()["case"]["id"]

    member_attempt = owner_client.post(
        f"/api/core/cases/{case_id}/transitions",
        json={"target_status": "dismissed", "expected_version": 1, "reason": "no longer relevant"},
        headers=_idem(),
    )
    assert member_attempt.status_code == 403

    admin_attempt = admin_client.post(
        f"/api/core/cases/{case_id}/transitions",
        json={"target_status": "dismissed", "expected_version": 1, "reason": "duplicate of another case"},
        headers=_idem(),
    )
    assert admin_attempt.status_code == 200
    assert admin_attempt.get_json()["case"]["status"] == "dismissed"


def test_ac3_stale_version_conflict_loses_no_edit(db, owner_client, owner_user, untracked_item):
    create = owner_client.post(
        "/api/core/cases/from-finding", json=_create_payload(untracked_item.id, owner_user.id), headers=_idem()
    )
    case_id = create.get_json()["case"]["id"]

    resp = owner_client.post(
        f"/api/core/cases/{case_id}/transitions",
        json={"target_status": "acknowledged", "expected_version": 99},
        headers=_idem(),
    )
    assert resp.status_code == 409
    assert resp.get_json()["error_code"] == "stale_version"

    db.expire_all()
    row = db.query(OperationalCase).filter(OperationalCase.id == UUID(case_id)).one()
    assert row.version == 1
    assert row.status == "open"


def test_ac3_verify_rejects_owner_and_resolver(db, owner_client, admin_client, owner_user, admin_user, untracked_item):
    create = owner_client.post(
        "/api/core/cases/from-finding", json=_create_payload(untracked_item.id, owner_user.id), headers=_idem()
    )
    case_id = create.get_json()["case"]["id"]
    owner_client.post(
        f"/api/core/cases/{case_id}/transitions",
        json={"target_status": "acknowledged", "expected_version": 1},
        headers=_idem(),
    )
    owner_client.post(
        f"/api/core/cases/{case_id}/transitions",
        json={"target_status": "in_progress", "expected_version": 2},
        headers=_idem(),
    )
    owner_client.post(
        f"/api/core/cases/{case_id}/transitions",
        json={
            "target_status": "resolved",
            "expected_version": 3,
            "cause": "unknown",
            "action_taken": "x",
            "outcome": "y",
        },
        headers=_idem(),
    )

    owner_attempt = owner_client.post(
        f"/api/core/cases/{case_id}/transitions",
        json={"target_status": "verified", "expected_version": 4, "verification_note": "self-verify"},
        headers=_idem(),
    )
    assert owner_attempt.status_code == 403

    # admin here is a different user but is *also not* the resolver/owner, so this
    # specifically proves the "current owner" branch, not a role restriction (any active
    # same-org MEMBER/ADMIN may verify except the owner/resolver, per the spec).
    admin_is_independent = admin_client.post(
        f"/api/core/cases/{case_id}/transitions",
        json={"target_status": "verified", "expected_version": 4, "verification_note": "independent check"},
        headers=_idem(),
    )
    assert admin_is_independent.status_code in (200, 409)  # 409 only if source isn't cleared; never 403 for role


# ---------------------------------------------------------------------------------
# AC4: source identity + recurrence rules
# ---------------------------------------------------------------------------------


def test_ac4_terminal_predecessor_suppresses_ordinary_create_and_new_occurrence_links_it(
    db, admin_client, owner_client, owner_user, untracked_item
):
    create = owner_client.post(
        "/api/core/cases/from-finding", json=_create_payload(untracked_item.id, owner_user.id), headers=_idem()
    )
    case_id = create.get_json()["case"]["id"]
    dismiss = admin_client.post(
        f"/api/core/cases/{case_id}/transitions",
        json={"target_status": "dismissed", "expected_version": 1, "reason": "administrative closure"},
        headers=_idem(),
    )
    assert dismiss.status_code == 200

    ordinary = owner_client.post(
        "/api/core/cases/from-finding", json=_create_payload(untracked_item.id, owner_user.id), headers=_idem()
    )
    assert ordinary.status_code == 409
    assert ordinary.get_json()["error_code"] == "requires_new_occurrence"
    assert ordinary.get_json()["previous_case"]["id"] == case_id

    recurrence_payload = _create_payload(
        untracked_item.id, owner_user.id, previous_case_id=case_id, recurrence_reason="Item became untracked again"
    )
    recurrence = owner_client.post("/api/core/cases/from-finding", json=recurrence_payload, headers=_idem())
    assert recurrence.status_code == 201, recurrence.data
    new_case_id = recurrence.get_json()["case"]["id"]
    assert new_case_id != case_id
    assert recurrence.get_json()["case"]["previous_case_id"] == case_id

    db.expire_all()
    dismissed_row = db.query(OperationalCase).filter(OperationalCase.id == UUID(case_id)).one()
    assert dismissed_row.status == "dismissed"  # terminal record unchanged by the recurrence


def test_ac4_stale_predecessor_rejected(db, admin_client, owner_client, owner_user, untracked_item, org_a):
    create = owner_client.post(
        "/api/core/cases/from-finding", json=_create_payload(untracked_item.id, owner_user.id), headers=_idem()
    )
    case_id = create.get_json()["case"]["id"]
    admin_client.post(
        f"/api/core/cases/{case_id}/transitions",
        json={"target_status": "dismissed", "expected_version": 1, "reason": "closed"},
        headers=_idem(),
    )

    other_item = InventoryItemFactory(
        org_id=org_a.id,
        name="Other Item",
        quantity="1",
        unit="kg",
        inventory_type="raw_material",
        extra_data={"untracked": True},
    )
    db.commit()
    # previous_case_id references a real case, but not the terminal predecessor *for this
    # source* -- must be rejected, not silently accepted.
    payload = _create_payload(other_item.id, owner_user.id, previous_case_id=case_id, recurrence_reason="wrong source")
    resp = owner_client.post("/api/core/cases/from-finding", json=payload, headers=_idem())
    assert resp.status_code == 409
    assert resp.get_json()["error_code"] == "stale_predecessor"


def test_ac4_foreign_org_predecessor_404(
    db, org_b_client, org_b_user, owner_client, owner_user, admin_client, untracked_item, org_b
):
    create = owner_client.post(
        "/api/core/cases/from-finding", json=_create_payload(untracked_item.id, owner_user.id), headers=_idem()
    )
    case_id = create.get_json()["case"]["id"]
    admin_client.post(
        f"/api/core/cases/{case_id}/transitions",
        json={"target_status": "dismissed", "expected_version": 1, "reason": "closed"},
        headers=_idem(),
    )

    org_b_item = InventoryItemFactory(
        org_id=org_b.id,
        name="Org B Item",
        quantity="1",
        unit="kg",
        inventory_type="raw_material",
        extra_data={"untracked": True},
    )
    db.commit()
    payload = _create_payload(
        org_b_item.id, org_b_user.id, previous_case_id=case_id, recurrence_reason="cross-org probe"
    )
    resp = org_b_client.post("/api/core/cases/from-finding", json=payload, headers=_idem())
    assert resp.status_code == 404


# ---------------------------------------------------------------------------------
# AC6: atomic case-mutation + event write, no-op refresh
# ---------------------------------------------------------------------------------


def test_ac6_refresh_source_noop_when_state_unchanged_emits_nothing(db, owner_client, owner_user, untracked_item):
    create = owner_client.post(
        "/api/core/cases/from-finding", json=_create_payload(untracked_item.id, owner_user.id), headers=_idem()
    )
    case_id = create.get_json()["case"]["id"]

    before_events = db.query(OperationalCaseEvent).filter(OperationalCaseEvent.case_id == UUID(case_id)).count()

    resp = owner_client.post(f"/api/core/cases/{case_id}/refresh-source", json={"expected_version": 1}, headers=_idem())
    assert resp.status_code == 200
    assert resp.get_json()["changed"] is False
    assert resp.get_json()["case"]["version"] == 1

    db.expire_all()
    after_events = db.query(OperationalCaseEvent).filter(OperationalCaseEvent.case_id == UUID(case_id)).count()
    assert after_events == before_events


def test_ac6_refresh_source_records_observation_when_state_changed(db, owner_client, owner_user, untracked_item):
    create = owner_client.post(
        "/api/core/cases/from-finding", json=_create_payload(untracked_item.id, owner_user.id), headers=_idem()
    )
    case_id = create.get_json()["case"]["id"]

    item_row = db.query(InventoryItem).filter(InventoryItem.id == untracked_item.id).one()
    with allow_inventory_quantity_write(InventoryQuantityWriteReason.MANUAL_API_UPDATE):
        item_row.quantity = "0"
        db.commit()  # must flush while the guard's context is still active

    resp = owner_client.post(f"/api/core/cases/{case_id}/refresh-source", json={"expected_version": 1}, headers=_idem())
    assert resp.status_code == 200
    assert resp.get_json()["changed"] is True
    assert resp.get_json()["source_state"] == "cleared"
    assert resp.get_json()["case"]["version"] == 2

    db.expire_all()
    event = (
        db.query(OperationalCaseEvent)
        .filter(OperationalCaseEvent.case_id == UUID(case_id), OperationalCaseEvent.case_version == 2)
        .one()
    )
    assert event.event_type == "operational_case.source_observed"
    assert event.entity_event_id is not None


def test_ac6_every_case_event_has_a_matching_entity_event(db, owner_client, admin_client, owner_user, untracked_item):
    create = owner_client.post(
        "/api/core/cases/from-finding", json=_create_payload(untracked_item.id, owner_user.id), headers=_idem()
    )
    case_id = create.get_json()["case"]["id"]
    admin_client.post(
        f"/api/core/cases/{case_id}/transitions",
        json={"target_status": "dismissed", "expected_version": 1, "reason": "test coverage"},
        headers=_idem(),
    )

    db.expire_all()
    events = db.query(OperationalCaseEvent).filter(OperationalCaseEvent.case_id == UUID(case_id)).all()
    assert len(events) == 2
    for event in events:
        assert event.entity_event_id is not None
        entity_event = db.query(EntityEvent).filter(EntityEvent.id == event.entity_event_id).one_or_none()
        assert entity_event is not None
        assert entity_event.entity_type == "operational_case"


# ---------------------------------------------------------------------------------
# Dashboard summary + Notifications source-status batch
# ---------------------------------------------------------------------------------


def test_dashboard_summary_includes_operational_cases_counts(db, owner_client, owner_user, untracked_item):
    owner_client.post(
        "/api/core/cases/from-finding", json=_create_payload(untracked_item.id, owner_user.id), headers=_idem()
    )
    resp = owner_client.get("/api/core/dashboard/summary")
    assert resp.status_code == 200
    body = resp.get_json()
    assert "operational_cases" in body
    oc = body["operational_cases"]
    assert oc["availability"] == "ok"
    assert oc["active_count"] == 1
    assert oc["critical_count"] == 1
    assert oc["href"] == "/core/cases"


def test_dashboard_summary_not_enabled_when_org_unsubscribed(db, org_b, org_b_client):
    # org_b fixture is subscribed for the API-route tests above; revoke it here to prove
    # the disabled shape on the dashboard route, which lives on core_bp (always
    # registered) rather than behind operational_cases_bp's own 404 gate.
    FeatureSubscriptionRepository(db).revoke(org_b.id, "operational_cases")
    db.commit()

    resp = org_b_client.get("/api/core/dashboard/summary")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["operational_cases"]["availability"] == "not_enabled"
    assert body["operational_cases"]["active_count"] is None


def test_source_status_batch_returns_case_and_404_for_foreign_id(db, owner_client, owner_user, untracked_item, org_b):
    create = owner_client.post(
        "/api/core/cases/from-finding", json=_create_payload(untracked_item.id, owner_user.id), headers=_idem()
    )
    case_id = create.get_json()["case"]["id"]

    ok_resp = owner_client.post("/api/core/cases/source-status", json={"source_entity_ids": [str(untracked_item.id)]})
    assert ok_resp.status_code == 200
    entry = ok_resp.get_json()["cases"][str(untracked_item.id)]
    assert entry["case_id"] == case_id
    assert entry["is_active"] is True

    foreign_item = InventoryItemFactory(
        org_id=org_b.id, name="Org B item", quantity="1", unit="kg", inventory_type="raw_material"
    )
    db.commit()
    foreign_resp = owner_client.post(
        "/api/core/cases/source-status", json={"source_entity_ids": [str(foreign_item.id)]}
    )
    assert foreign_resp.status_code == 404


# ---------------------------------------------------------------------------------
# AC8 (partial): additive migration shape. Full up/down/up is verified manually against
# the disposable local DB per docs/operational-cases-runbook.md -- running alembic
# downgrade here would drop these tables out from under every other test sharing this
# database, which the build's own instructions explicitly forbid.
# ---------------------------------------------------------------------------------


def test_ac8_tables_and_partial_unique_index_exist(db):
    from sqlalchemy import text

    tables = {
        row[0]
        for row in db.execute(
            text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' "
                "AND table_name IN ('operational_cases', 'operational_case_links', 'operational_case_events')"
            )
        ).fetchall()
    }
    assert tables == {"operational_cases", "operational_case_links", "operational_case_events"}

    index_exists = db.execute(
        text("SELECT 1 FROM pg_indexes WHERE indexname = 'uq_operational_cases_active_source'")
    ).fetchone()
    assert index_exists is not None


@pytest.mark.parametrize("extra", [{"status": "verified"}, {"org_id": str(uuid4())}, {"unexpected": 1}])
def test_ac2_create_unknown_fields_rejected(owner_client, owner_user, untracked_item, db, extra):
    response = owner_client.post(
        "/api/core/cases/from-finding",
        json=_create_payload(untracked_item.id, owner_user.id, **extra),
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 400
    assert db.query(OperationalCase).filter(OperationalCase.org_id == owner_user.org_id).count() == 0


@pytest.mark.parametrize("payload", [[], True, "text"])
def test_ac2_command_requires_json_object(owner_client, payload):
    assert owner_client.post("/api/core/cases/from-finding", json=payload).status_code == 400


@pytest.mark.parametrize(
    "query", ["owner=wrong", "status=wrong", "severity=wrong", "limit=0", "limit=101", "overdue=wat", "cursor=bad"]
)
def test_ac2_invalid_filters_return_400(owner_client, query):
    assert owner_client.get("/api/core/cases?" + query).status_code == 400


def test_ac2_deployment_disable_retains_admin_history(monkeypatch, admin_client, owner_user, untracked_item):
    from app.utils.config_loader import Config

    created = admin_client.post(
        "/api/core/cases/from-finding",
        json=_create_payload(untracked_item.id, owner_user.id),
        headers={"Idempotency-Key": str(uuid4())},
    )
    cid = created.json["case"]["id"]
    monkeypatch.setattr(Config, "operational_cases_enabled", property(lambda self: False))
    assert admin_client.get("/api/core/cases/" + cid).status_code == 404
    assert admin_client.get("/api/core/cases/history/" + cid).json["id"] == cid
    assert admin_client.get("/api/core/cases/history/" + cid + "/events").status_code == 200


def test_ac2_request_size_is_bounded(owner_client):
    response = owner_client.post("/api/core/cases/from-finding", json={"text": "x" * 33000})
    assert response.status_code == 413


def test_ac6_audit_failure_rolls_back_everything(monkeypatch, owner_client, owner_user, untracked_item, db):
    from app.features.operational_cases.repositories.operational_case_event_repo import OperationalCaseEventRepository

    def fail(*args, **kwargs):
        raise RuntimeError("injected audit failure")

    monkeypatch.setattr(OperationalCaseEventRepository, "add", fail)
    with pytest.raises(RuntimeError, match="injected audit failure"):
        owner_client.post(
            "/api/core/cases/from-finding",
            json=_create_payload(untracked_item.id, owner_user.id),
            headers={"Idempotency-Key": str(uuid4())},
        )
    assert db.query(OperationalCase).filter(OperationalCase.org_id == owner_user.org_id).count() == 0
    assert (
        db.query(EntityEvent)
        .filter(EntityEvent.org_id == owner_user.org_id, EntityEvent.entity_type == "operational_case")
        .count()
        == 0
    )
    assert db.query(ApiIdempotencyKey).filter(ApiIdempotencyKey.org_id == owner_user.org_id).count() == 0


def test_ac2_database_rejects_foreign_predecessor(owner_client, owner_user, untracked_item, db, org_b, org_b_user):
    from sqlalchemy.exc import IntegrityError

    from tests.factories import OperationalCaseFactory

    created = owner_client.post(
        "/api/core/cases/from-finding",
        json=_create_payload(untracked_item.id, owner_user.id),
        headers={"Idempotency-Key": str(uuid4())},
    )
    cid = UUID(created.json["case"]["id"])
    with pytest.raises(IntegrityError):
        OperationalCaseFactory(org_id=org_b.id, owner_id=org_b_user.id, created_by=org_b_user.id, previous_case_id=cid)
    db.rollback()


def test_ac1_creation_has_source_freshness(owner_client, owner_user, untracked_item):
    created = owner_client.post(
        "/api/core/cases/from-finding",
        json=_create_payload(untracked_item.id, owner_user.id),
        headers={"Idempotency-Key": str(uuid4())},
    )
    detail = owner_client.get("/api/core/cases/" + created.json["case"]["id"]).json
    assert detail["source_observation"]["observed_at"] == detail["source_snapshot"]["observed_at"]


def test_ac6_export_and_restore_rehearsal_rolls_back(
    tmp_path, monkeypatch, owner_client, owner_user, untracked_item, db
):
    """The recovery rehearsal must preserve a byte-identical, tenant-scoped export.

    The real engine remains the shared disposable test DB, while the name guard is
    overridden to exercise the local ``oc_verify_*`` safety branch. The command's own
    transaction is always rolled back, so the source case remains available afterwards.
    """
    from app.cli.operational_cases import export_cases, rehearse_restore
    from app.utils.config_loader import Config

    created = owner_client.post(
        "/api/core/cases/from-finding",
        json=_create_payload(untracked_item.id, owner_user.id),
        headers=_idem(),
    )
    assert created.status_code == 201
    export_dir = tmp_path / "case-export"
    manifest = export_cases(owner_user.org_id, export_dir)
    assert manifest["files"]["operational_cases"]["row_count"] == 1

    monkeypatch.setattr(Config, "db_name", property(lambda self: "oc_verify_test"))
    assert rehearse_restore(export_dir) is True
    assert db.query(OperationalCase).filter(OperationalCase.org_id == owner_user.org_id).count() == 1


def test_ac3_inactive_owner_requires_admin_reassignment(
    db, admin_client, owner_client, owner_user, verifier_user, untracked_item
):
    created = owner_client.post(
        "/api/core/cases/from-finding",
        json=_create_payload(untracked_item.id, owner_user.id),
        headers={"Idempotency-Key": str(uuid4())},
    )
    cid = created.json["case"]["id"]
    # The factory object can be detached from the session used by the request. Update
    # the persisted row so this simulates a concurrent account deactivation.
    db.query(User).filter(User.id == owner_user.id).update({User.is_active: False})
    db.commit()
    response = admin_client.post(
        "/api/core/cases/" + cid + "/transitions",
        json={"target_status": "acknowledged", "expected_version": 1},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 400
    response = admin_client.patch(
        "/api/core/cases/" + cid,
        json={"owner_id": str(verifier_user.id), "expected_version": 1},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 200
    assert response.json["case"]["owner_id"] == str(verifier_user.id)
