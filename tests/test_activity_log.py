"""Regression tests for the activity-log audit (review-feature, spec
.agents/specs/activity-log.md).

No test file existed for this slice before this review (`test_finding_history`'s apparent
match on grep was a false positive on the substring "history" in its own docstring, not a
reference to this feature — confirmed empty on a real grep for EntityEvent/audit_repo/
AuditLog). `[REGRESSION]`-tagged tests reproduce a finding from
`.agents/reports/activity-log/security-audit.md`, verified RED against the code at the
review baseline (branch review/activity-log, base dd8c061) before the fix in this same
review. AC7 is the headline finding — a cross-tenant summary leak, CWE-639 — verified at
the API level here since it has zero UI callers (grepped, confirmed in the security report);
there is nothing for a browser test to click through.

Fixtures follow the local org/other_org/user/app_client pattern from
tests/test_traceability.py rather than the shared two_org_two_user fixture, because that
fixture (and the traceability e2e suite's two_tenants_with_chains) seed a real Process/Step
DAG via build_linear_dag, which currently fails on this shared test DB — a `steps.org_id`
NOT NULL violation the schema picked up from a migration (`tenant_org_id_notnull_001`) that
exists on the DB's alembic_version but not in this worktree's migration files (a concurrent
worktree's in-flight migration, unrelated to this slice). Activity-log's own routes never
touch Process/Step, so avoiding that fixture sidesteps the contamination entirely rather
than working around it.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.core.db.models.entity_event import EntityEvent
from app.core.db.models.entity_event_summary import EntityEventSummary
from app.core.db.models.organisation import Organisation
from app.core.security.auth_service import AuthService
from tests.factories import InventoryItemFactory, OrganisationFactory


@pytest.fixture
def org(db):
    organisation = OrganisationFactory(name=f"Activity Log Audit Org {uuid4()}")
    db.commit()
    org_id = organisation.id
    yield organisation
    db.rollback()
    _purge_org(db, org_id)


@pytest.fixture
def other_org(db):
    organisation = OrganisationFactory(name=f"Activity Log Audit Neighbour {uuid4()}")
    db.commit()
    org_id = organisation.id
    yield organisation
    db.rollback()
    _purge_org(db, org_id)


def _purge_org(db, org_id):
    from app.core.db.models.audit_log import AuditLog
    from app.core.db.models.inventory_item import InventoryItem
    from app.core.db.models.user import User

    # AuditLog before User: audit_logs.user_id has no ON DELETE action, so deleting a user that
    # has logged anything (every login does) raises, the except below swallows it, and the org
    # row is left behind in the shared test DB (1,170 of them by 2026-10-08).
    try:
        for model in (EntityEvent, EntityEventSummary, InventoryItem, AuditLog, User):
            db.query(model).filter(model.org_id == org_id).delete(synchronize_session=False)
        db.query(Organisation).filter(Organisation.id == org_id).delete(synchronize_session=False)
        db.commit()
    except Exception:
        db.rollback()


@pytest.fixture
def user(db, org):
    from app.core.db.repositories.user_repo import UserRepository

    u = UserRepository(db).create_user(
        org_id=org.id,
        email=f"activity_log_{uuid4()}@test.com",
        password_hash=AuthService.hash_password("TestPass123!"),
    )
    db.commit()
    yield u


@pytest.fixture
def other_user(db, other_org):
    from app.core.db.repositories.user_repo import UserRepository

    u = UserRepository(db).create_user(
        org_id=other_org.id,
        email=f"activity_log_neighbour_{uuid4()}@test.com",
        password_hash=AuthService.hash_password("TestPass123!"),
    )
    db.commit()
    yield u


def _make_client(user, password="TestPass123!"):
    from app.api.app_factory import create_app

    flask_app = create_app()
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False
    client = flask_app.test_client()
    client.environ_base["wsgi.url_scheme"] = "https"
    client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
    with flask_app.app_context():
        resp = client.post(
            "/auth/login",
            json={"email": user.email, "password": password},
            content_type="application/json",
        )
        assert resp.status_code in (200, 201), f"Login failed: {resp.data}"
    return client


@pytest.fixture
def app_client(user):
    client = _make_client(user)
    yield client
    client.__exit__(None, None, None) if hasattr(client, "__exit__") else None


@pytest.fixture
def other_app_client(other_user):
    yield _make_client(other_user)


def _plant_event(db, org_id, *, entity_type, entity_id, event_type, payload=None, diff=None, when=None):
    # entity_events.seq has no DB default (migration entity_events_seq_noident_001); a test
    # that builds the row directly allocates it like EventWriter does (per-org MAX+1).
    next_seq = db.execute(
        text("SELECT COALESCE(MAX(seq), 0) + 1 FROM entity_events WHERE org_id = :o"), {"o": str(org_id)}
    ).scalar()
    ev = EntityEvent(
        org_id=org_id,
        seq=next_seq,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_type="user",
        actor_label="activity_log_test@test.com",
        payload=payload or {},
        diff=diff,
        created_at=when or datetime.now(UTC),
    )
    db.add(ev)
    db.commit()
    return ev


def _plant_summary(db, org_id, *, entity_type, entity_id, summary):
    """Directly write an entity_event_summaries row, bypassing EventWriter -- this is test
    setup for the read-side routes, not a stand-in for EventWriter itself (platform layer,
    out of scope for this review)."""
    from datetime import UTC as _UTC
    from datetime import datetime as _dt

    db.execute(
        __import__("sqlalchemy").text(
            """
            INSERT INTO entity_event_summaries
                (entity_id, org_id, entity_type, summary, last_event_at, last_event_type, last_actor, updated_at)
            VALUES
                (:entity_id, :org_id, :entity_type, CAST(:summary AS jsonb), :now, :event_type, :actor, :now)
            ON CONFLICT (entity_id) DO UPDATE SET
                summary = CAST(:summary AS jsonb), org_id = :org_id
            """
        ),
        {
            "entity_id": str(entity_id),
            "org_id": str(org_id),
            "entity_type": entity_type,
            "summary": __import__("json").dumps(summary),
            "now": _dt.now(_UTC),
            "event_type": "test.seed",
            "actor": "activity_log_test@test.com",
        },
    )
    db.commit()


# --------------------------------------------------------------------------------------
# Fixture hygiene [REGRESSION] -- findings-index 4ff460ee (test DB leftovers).
# --------------------------------------------------------------------------------------


def test_purge_org_removes_an_org_whose_user_has_audit_rows(db, org, user):
    """`_purge_org` swallows its own failures, so a broken delete order is invisible: the test
    passes and the org row stays in the shared DB. This file leaked 31 orgs a run that way
    (users were deleted before the `audit_logs` rows that reference them). Assert the
    post-state instead of trusting the teardown."""
    from app.core.db.models.audit_log import AuditLog

    db.add(AuditLog(org_id=org.id, user_id=user.id, action="login", entity="user", entity_id=user.id))
    db.commit()
    org_id = org.id

    _purge_org(db, org_id)

    assert db.query(Organisation).filter(Organisation.id == org_id).count() == 0
    assert db.query(AuditLog).filter(AuditLog.org_id == org_id).count() == 0


# --------------------------------------------------------------------------------------
# AC7 [REGRESSION] -- the headline finding: entity_summary_detail leaked cross-tenant.
# --------------------------------------------------------------------------------------


class TestAC7CrossTenantSummaryLeak:
    """backend.py:5538 queried EntityEventSummary by entity_id alone, no org_id filter.
    entity_id is that table's primary key (globally unique), so any authenticated user of
    any org who has another org's entity UUID got that entity's full summary back --
    including, for entity_type=user/org, PII (email, login/failed-login counts) and org
    metadata that never touch inventory at all."""

    def test_inventory_item_summary_not_visible_cross_tenant(self, db, org, other_org, app_client):
        neighbour_item = InventoryItemFactory(
            org_id=other_org.id, name="Neighbour Secret Item", quantity="7", unit="kg"
        )
        db.commit()

        resp = app_client.get(f"/api/core/entities/inventory_item/{neighbour_item.id}/summary")
        assert resp.status_code == 200, resp.data
        body = resp.get_json()
        assert body["summary"] == {}, f"org A received org B's inventory summary: {body['summary']}"
        assert body["recent_events"] == []

    def test_user_summary_pii_not_visible_cross_tenant(self, db, org, other_org, other_user, app_client):
        """The severity-raising case: entity_type=user summaries carry email, role,
        login_count, failed_login_count, last_login_at (event_writer._update_user_summary).
        A missing org filter here leaks another org's user PII, not just inventory data."""
        _plant_summary(
            db,
            other_org.id,
            entity_type="user",
            entity_id=other_user.id,
            summary={
                "email": "victim@neighbour-org.example",
                "role": "admin",
                "login_count": 42,
                "failed_login_count": 3,
                "last_login_at": datetime.now(UTC).isoformat(),
            },
        )

        resp = app_client.get(f"/api/core/entities/user/{other_user.id}/summary")
        assert resp.status_code == 200, resp.data
        body = resp.get_json()
        assert body["summary"] == {}, f"org A received org B's user PII: {body['summary']}"
        assert "victim@neighbour-org.example" not in resp.get_data(as_text=True)

    def test_org_summary_not_visible_cross_tenant(self, db, org, other_org, app_client):
        _plant_summary(
            db,
            other_org.id,
            entity_type="org",
            entity_id=other_org.id,
            summary={
                "name": "Neighbour Org Real Name",
                "status": "active",
                "last_changed_by": "someone@neighbour.example",
            },
        )

        resp = app_client.get(f"/api/core/entities/org/{other_org.id}/summary")
        assert resp.status_code == 200, resp.data
        body = resp.get_json()
        assert body["summary"] == {}, f"org A received org B's org metadata: {body['summary']}"
        assert "Neighbour Org Real Name" not in resp.get_data(as_text=True)

    def test_own_org_summary_still_returned(self, db, org, app_client):
        """The fix must not overcorrect into never returning a summary -- same-org lookups
        still work."""
        item = InventoryItemFactory(org_id=org.id, name="My Own Item", quantity="3", unit="kg")
        db.commit()

        resp = app_client.get(f"/api/core/entities/inventory_item/{item.id}/summary")
        assert resp.status_code == 200, resp.data
        body = resp.get_json()
        assert body["summary"] != {}
        assert body["summary"]["add_method"] == "manual"


class TestAC8RecentEventsAlreadyOrgScoped:
    """AC8: recent_events was already correctly org-scoped before this review's fix --
    lock that in so a future edit can't regress both queries in the same handler at once."""

    def test_recent_events_excludes_other_orgs_events(self, db, org, other_org, app_client):
        neighbour_item = InventoryItemFactory(org_id=other_org.id, name="Neighbour Item 2", quantity="1", unit="kg")
        db.commit()

        resp = app_client.get(f"/api/core/entities/inventory_item/{neighbour_item.id}/summary")
        assert resp.status_code == 200, resp.data
        assert resp.get_json()["recent_events"] == []


class TestAC9EntityTypeAndIdValidation:
    def test_invalid_entity_type_returns_400(self, app_client, org):
        resp = app_client.get(f"/api/core/entities/not_a_type/{uuid4()}/summary")
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "Invalid entity_type"

    def test_invalid_entity_id_returns_400_not_500(self, app_client, org):
        resp = app_client.get("/api/core/entities/inventory_item/not-a-uuid/summary")
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "Invalid entity_id"


class TestAC10NoSummaryRowReturnsEmptyDict:
    def test_no_summary_row_returns_empty_dict_not_404(self, app_client, org):
        resp = app_client.get(f"/api/core/entities/execution/{uuid4()}/summary")
        assert resp.status_code == 200, resp.data
        assert resp.get_json()["summary"] == {}


# --------------------------------------------------------------------------------------
# Entity story
# --------------------------------------------------------------------------------------


class TestEntityStory:
    def test_ac1_invalid_entity_type_400(self, app_client, org):
        resp = app_client.get(f"/api/core/entities/bogus/{uuid4()}/story")
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "Invalid entity_type"

    def test_ac2_invalid_entity_id_400(self, app_client, org):
        resp = app_client.get("/api/core/entities/inventory_item/not-a-uuid/story")
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "Invalid entity_id"

    def test_ac3_cross_tenant_entity_id_returns_empty_events_not_404(self, db, org, other_org, app_client):
        """Cross-org existence must not be distinguishable from non-existence, same
        standard as traceability's AC2."""
        neighbour_item = InventoryItemFactory(org_id=other_org.id, name="Neighbour Item 3", quantity="1", unit="kg")
        db.commit()

        resp = app_client.get(f"/api/core/entities/inventory_item/{neighbour_item.id}/story")
        assert resp.status_code == 200, resp.data
        body = resp.get_json()
        assert body["events"] == []
        assert body["total"] == 0

    def test_ac3_events_ordered_oldest_first_and_paginated(self, db, org, app_client):
        item_id = uuid4()
        now = datetime.now(UTC)
        for i in range(3):
            _plant_event(
                db,
                org.id,
                entity_type="inventory_item",
                entity_id=item_id,
                event_type="inventory_item.quantity_adjusted",
                payload={"quantity_before": i, "quantity_after": i + 1, "unit": "kg"},
                when=now + timedelta(seconds=i),
            )

        resp = app_client.get(f"/api/core/entities/inventory_item/{item_id}/story?limit=2")
        assert resp.status_code == 200, resp.data
        body = resp.get_json()
        assert body["total"] == 3, "total must reflect the full org+entity-scoped count, not the page size"
        assert len(body["events"]) == 2
        ats = [e["at"] for e in body["events"]]
        assert ats == sorted(ats), "events must be ordered oldest-first"

    def test_ac5_events_carry_summary_and_diff_rows(self, db, org, app_client):
        item_id = uuid4()
        _plant_event(
            db,
            org.id,
            entity_type="inventory_item",
            entity_id=item_id,
            event_type="inventory_item.quantity_adjusted",
            payload={"quantity_before": "5", "quantity_after": "8", "unit": "kg"},
        )

        resp = app_client.get(f"/api/core/entities/inventory_item/{item_id}/story")
        body = resp.get_json()
        assert body["events"][0]["summary"] == "Quantity adjusted 5 → 8 kg"
        assert "diff_rows" in body["events"][0]

    def test_ac6_legacy_audit_merge_is_org_scoped(self, db, org, other_org, app_client):
        """A cross-tenant entity_id must not surface another org's legacy
        extra_data.inventory_audit_history entries either -- _merge_inventory_legacy_audit
        re-scopes its own InventoryItem lookup by (id, org_id)."""
        from app.core.db.repositories.inventory_repo import InventoryRepository

        neighbour_item = InventoryRepository(db).create_inventory_item(
            org_id=other_org.id,
            name="Neighbour Legacy Item",
            quantity="4",
            unit="kg",
            inventory_type="raw_material",
            extra_data={
                "inventory_audit_history": [
                    {
                        "timestamp_utc": datetime.now(UTC).isoformat(),
                        "operator_name": "Neighbour Operator",
                        "operator_email": "op@neighbour.example",
                        "quantity_added": "4",
                        "user_id": str(uuid4()),
                    }
                ]
            },
        )
        db.commit()

        resp = app_client.get(f"/api/core/entities/inventory_item/{neighbour_item.id}/story")
        assert resp.status_code == 200, resp.data
        body = resp.get_json()
        assert body["events"] == [], "legacy audit entries from another org's item must not leak"
        assert "Neighbour Operator" not in resp.get_data(as_text=True)

    def test_ac6_legacy_audit_merge_strips_user_id(self, db, org, app_client):
        from app.core.db.repositories.inventory_repo import InventoryRepository

        item = InventoryRepository(db).create_inventory_item(
            org_id=org.id,
            name="My Legacy Item",
            quantity="4",
            unit="kg",
            inventory_type="raw_material",
            extra_data={
                "inventory_audit_history": [
                    {
                        "timestamp_utc": (datetime.now(UTC) - timedelta(days=1)).isoformat(),
                        "operator_name": "Legacy Operator",
                        "operator_email": "op@myorg.example",
                        "quantity_added": "4",
                        "user_id": str(uuid4()),
                    }
                ]
            },
        )
        db.commit()

        resp = app_client.get(f"/api/core/entities/inventory_item/{item.id}/story")
        body = resp.get_json()
        legacy_rows = [e for e in body["events"] if e["event_type"] == "inventory_item.legacy_entry"]
        assert len(legacy_rows) == 1
        assert "user_id" not in __import__("json").dumps(legacy_rows[0])
        assert legacy_rows[0]["actor"] == "Legacy Operator (op@myorg.example)"

    def test_ac_gap_non_numeric_limit_returns_400_not_500(self, app_client, org):
        """[REGRESSION] F2: bare int() on limit/offset raised an unhandled ValueError ->
        500 before this review's fix."""
        resp = app_client.get(f"/api/core/entities/inventory_item/{uuid4()}/story?limit=abc")
        assert resp.status_code == 400, resp.data
        assert "error" in resp.get_json()

    def test_ac_gap_non_numeric_offset_returns_400_not_500(self, app_client, org):
        resp = app_client.get(f"/api/core/entities/inventory_item/{uuid4()}/story?offset=abc")
        assert resp.status_code == 400, resp.data


class TestEntityStoryUnauthenticated:
    def test_ac15_story_requires_auth(self, org):
        from app.api.app_factory import create_app

        flask_app = create_app()
        flask_app.config["TESTING"] = True
        with flask_app.test_client() as client:
            client.environ_base["wsgi.url_scheme"] = "https"
            client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
            resp = client.get(f"/api/core/entities/inventory_item/{uuid4()}/story")
            assert resp.status_code == 401


# --------------------------------------------------------------------------------------
# Org activity feed
# --------------------------------------------------------------------------------------


class TestEntityActivityFeed:
    def test_ac11_activity_feed_is_org_scoped(self, db, org, other_org, app_client):
        item_id = uuid4()
        neighbour_item_id = uuid4()
        _plant_event(db, org.id, entity_type="inventory_item", entity_id=item_id, event_type="inventory_item.created")
        _plant_event(
            db,
            other_org.id,
            entity_type="inventory_item",
            entity_id=neighbour_item_id,
            event_type="inventory_item.created",
        )

        resp = app_client.get("/api/core/entities/activity")
        assert resp.status_code == 200, resp.data
        body = resp.get_json()
        seen_ids = {e["entity_id"] for e in body["events"]}
        assert str(item_id) in seen_ids
        assert str(neighbour_item_id) not in seen_ids

    def test_ac12_entity_types_filter_restricts_results(self, db, org, app_client):
        item_id, exec_id = uuid4(), uuid4()
        _plant_event(db, org.id, entity_type="inventory_item", entity_id=item_id, event_type="inventory_item.created")
        _plant_event(db, org.id, entity_type="execution", entity_id=exec_id, event_type="execution.created")

        resp = app_client.get("/api/core/entities/activity?entity_types=execution")
        body = resp.get_json()
        types_seen = {e["entity_type"] for e in body["events"]}
        assert types_seen == {"execution"}

    def test_ac12_unknown_entity_type_in_filter_yields_zero_rows_not_error(self, org, app_client):
        resp = app_client.get("/api/core/entities/activity?entity_types=not_a_real_type")
        assert resp.status_code == 200, resp.data
        assert resp.get_json()["events"] == []

    def test_ac13_date_range_filters_inclusive_of_whole_to_date_day(self, db, org, app_client):
        early = datetime(2020, 1, 1, tzinfo=UTC)
        in_range = datetime(2024, 6, 15, 23, 0, tzinfo=UTC)
        late = datetime(2030, 1, 1, tzinfo=UTC)
        for when, tag in ((early, "early"), (in_range, "in_range"), (late, "late")):
            _plant_event(
                db,
                org.id,
                entity_type="process",
                entity_id=uuid4(),
                event_type="process.created",
                payload={"name": tag},
                when=when,
            )

        resp = app_client.get("/api/core/entities/activity?from_date=2024-06-01&to_date=2024-06-15")
        body = resp.get_json()
        names = {e["payload"]["name"] for e in body["events"]}
        assert names == {"in_range"}, f"expected only the in-range event, got {names}"

    def test_ac13_malformed_date_is_silently_ignored_not_400(self, org, app_client):
        resp = app_client.get("/api/core/entities/activity?from_date=not-a-date")
        assert resp.status_code == 200, resp.data

    def test_ac13_malformed_to_date_is_silently_ignored_not_400(self, org, app_client):
        resp = app_client.get("/api/core/entities/activity?to_date=not-a-date")
        assert resp.status_code == 200, resp.data

    def test_ac_gap_non_numeric_limit_returns_400_not_500(self, app_client, org):
        resp = app_client.get("/api/core/entities/activity?limit=abc")
        assert resp.status_code == 400, resp.data

    def test_ac_gap_non_numeric_offset_returns_400_not_500(self, app_client, org):
        resp = app_client.get("/api/core/entities/activity?offset=abc")
        assert resp.status_code == 400, resp.data

    def test_ac15_activity_feed_requires_auth(self):
        from app.api.app_factory import create_app

        flask_app = create_app()
        flask_app.config["TESTING"] = True
        with flask_app.test_client() as client:
            client.environ_base["wsgi.url_scheme"] = "https"
            client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
            resp = client.get("/api/core/entities/activity")
            assert resp.status_code == 401


class TestEntitySummaryUnauthenticated:
    def test_ac15_summary_requires_auth(self):
        from app.api.app_factory import create_app

        flask_app = create_app()
        flask_app.config["TESTING"] = True
        with flask_app.test_client() as client:
            client.environ_base["wsgi.url_scheme"] = "https"
            client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
            resp = client.get(f"/api/core/entities/inventory_item/{uuid4()}/summary")
            assert resp.status_code == 401


# --------------------------------------------------------------------------------------
# Diff-humanisation (unit-level, no DB needed for most cases)
# --------------------------------------------------------------------------------------


class FakeEvent:
    def __init__(self, event_type, payload=None, diff=None):
        self.event_type = event_type
        self.payload = payload or {}
        self.diff = diff


class TestHumanSummaryFallback:
    def test_ac16_unrecognized_event_type_falls_back_to_generic_rendering(self):
        from app.features.activity_log.routes.activity_routes import _human_summary

        ev = FakeEvent("widget.frobnicated")
        assert _human_summary(ev) == "Widget — frobnicated"

    def test_ac16_unrecognized_event_type_does_not_raise(self):
        from app.features.activity_log.routes.activity_routes import _event_diff_rows, _human_summary

        ev = FakeEvent("totally.unknown_thing", payload={}, diff={"some_field": {"before": "a", "after": "b"}})
        _human_summary(ev)  # must not raise
        _event_diff_rows(ev)  # must not raise

    def test_known_event_type_inventory_created_summary(self):
        from app.features.activity_log.routes.activity_routes import _human_summary

        ev = FakeEvent(
            "inventory_item.created",
            payload={"quantity": "10", "unit": "kg", "add_method": "manual", "inventory_type": "raw_material"},
        )
        assert "Added 10 kg" in _human_summary(ev)

    def test_build_diff_rows_skips_unchanged_fields(self):
        from app.features.activity_log.routes.activity_routes import _build_diff_rows

        rows = _build_diff_rows({"name": {"before": "Same", "after": "Same"}})
        assert rows == []

    def test_build_diff_rows_reports_changed_field(self):
        from app.features.activity_log.routes.activity_routes import _build_diff_rows

        rows = _build_diff_rows({"quantity": {"before": "5", "after": "8"}})
        assert rows == [{"label": "Quantity", "before": "5", "after": "8"}]


# --------------------------------------------------------------------------------------
# _human_summary -- every event-type branch (~450 of this slice's 721 lines are this kind
# of diff-humanisation presentation logic, per .agents/feature-index.md; before this
# review only "inventory_item.created" and the unrecognized-type fallback had any test
# touching them at all).
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("event_type", "payload", "diff", "expected_substring"),
    [
        (
            "inventory_item.quantity_adjusted",
            {"quantity_before": "5", "quantity_after": "8", "unit": "kg"},
            None,
            "5 → 8 kg",
        ),
        (
            "inventory_item.consumed",
            {"quantity_consumed": "3", "unit": "kg", "step_name": "Mixing"},
            None,
            "consumed in 'Mixing'",
        ),
        (
            "inventory_item.produced",
            {"quantity_produced": "2", "unit": "L", "step_name": "Bottling"},
            None,
            "produced by 'Bottling'",
        ),
        (
            "inventory_item.wasted",
            {"quantity_wasted": "1", "unit": "kg", "reason": "spillage"},
            None,
            "wasted — spillage",
        ),
        ("inventory_item.updated", {}, {"quantity": {"before": "5", "after": "8"}}, "Updated quantity"),
        ("inventory_item.updated", {}, {}, "Updated"),
        ("inventory_item.deleted", {"name": "Old Widget"}, None, "Deleted Old Widget"),
        (
            "execution.created",
            {"total_steps": 4, "process_version_number": 2},
            None,
            "Batch started — 4 steps (process v2)",
        ),
        (
            "execution.step_completed",
            {
                "step_name": "Mixing",
                "items_consumed": [{"item_id": "x"}],
                "items_produced": [{"item_id": "y"}, {"item_id": "z"}],
            },
            None,
            "'Mixing' completed — 1 input consumed, 2 outputs produced",
        ),
        ("execution.completed", {"total_steps": 3}, None, "Batch completed (3 steps)"),
        ("execution.cancelled", {"reason": "operator abort"}, None, "Batch cancelled — operator abort"),
        ("process.created", {"name": "Distillation"}, None, "created"),
        ("process.updated", {}, None, "Process updated"),
        (
            "process.step_added",
            {"step": {"name": "Fermentation", "step_number": 2}},
            None,
            "Step 'Fermentation' added at position 2",
        ),
        ("process.step_updated", {"step": {"name": "Fermentation"}}, None, "Step 'Fermentation' updated"),
        ("process.step_deleted", {"deleted_step": {"name": "Fermentation"}}, None, "Step 'Fermentation' removed"),
        ("process.deleted", {"name": "Distillation"}, None, "deleted"),
        (
            "process.step_doc_uploaded",
            {"step_name": "Mixing", "doc_title": "SOP-1"},
            None,
            "SOP file 'SOP-1' uploaded to step 'Mixing'",
        ),
        (
            "process.step_doc_created",
            {"step_name": "Mixing", "doc_title": "SOP-1"},
            None,
            "SOP instructions 'SOP-1' written for step 'Mixing'",
        ),
        (
            "process.step_doc_updated",
            {"step_name": "Mixing", "doc_title": "SOP-1"},
            None,
            "SOP instructions 'SOP-1' updated for step 'Mixing'",
        ),
        (
            "process.step_doc_deleted",
            {"step_name": "Mixing", "doc_title": "SOP-1"},
            None,
            "SOP document 'SOP-1' removed from step 'Mixing'",
        ),
        ("user.created", {"email": "new@test.com"}, None, "Account created — new@test.com"),
        ("user.login", {"2fa_used": True, "ip": "1.2.3.4"}, None, "Logged in with 2FA from 1.2.3.4"),
        ("user.login", {"2fa_used": False, "ip": "1.2.3.4"}, None, "Logged in with password from 1.2.3.4"),
        ("user.login_failed", {"ip": "1.2.3.4", "failed_attempts": 3}, None, "Login failed from 1.2.3.4 (attempt 3)"),
        ("user.2fa_enabled", {}, None, "Two-factor authentication enabled"),
        ("user.2fa_disabled", {}, None, "Two-factor authentication disabled"),
        ("user.role_changed", {"old_role": "member", "new_role": "admin"}, None, "Role changed from member to admin"),
        ("org.settings_updated", {}, {"name": {"after": "New Org Name"}}, "Name changed to 'New Org Name'"),
        ("org.settings_updated", {}, {"status": {"after": "suspended"}}, "Status changed to suspended"),
        ("org.settings_updated", {}, {}, "Organisation settings updated"),
    ],
)
def test_human_summary_every_known_event_type(event_type, payload, diff, expected_substring):
    from app.features.activity_log.routes.activity_routes import _human_summary

    ev = FakeEvent(event_type, payload=payload, diff=diff)
    assert expected_substring in _human_summary(ev)


class TestEventDiffRowsDispatch:
    """_event_diff_rows dispatches on event_type to one of three shapes: synthesized rows
    for a newly-added step, nested step diff for step_updated, or the generic diff -- only
    the generic path had coverage before this review."""

    def test_process_step_added_synthesizes_rows_from_payload(self):
        from app.features.activity_log.routes.activity_routes import _event_diff_rows

        ev = FakeEvent(
            "process.step_added",
            payload={
                "step": {
                    "description": "Mix thoroughly",
                    "inputs": [{"name": "Water", "quantity": "1", "unit": "L"}],
                    "outputs": [{"name": "Mixture", "quantity": "1", "unit": "L"}],
                    "execution_prompts": [{"label": "Confirm temperature"}],
                }
            },
        )
        rows = _event_diff_rows(ev)
        labels = [r["label"] for r in rows]
        assert labels == ["Description", "Input", "Output", "Prompt"]
        assert rows[1]["after"] == "'Water' — 1 L"

    def test_process_step_updated_uses_nested_step_diff(self):
        from app.features.activity_log.routes.activity_routes import _event_diff_rows

        ev = FakeEvent("process.step_updated", diff={"step": {"name": {"before": "Old", "after": "New"}}})
        rows = _event_diff_rows(ev)
        assert rows == [{"label": "Name", "before": "Old", "after": "New"}]

    def test_default_dispatch_uses_top_level_diff(self):
        from app.features.activity_log.routes.activity_routes import _event_diff_rows

        ev = FakeEvent("inventory_item.updated", diff={"quantity": {"before": "1", "after": "2"}})
        rows = _event_diff_rows(ev)
        assert rows == [{"label": "Quantity", "before": "1", "after": "2"}]


class TestSmartListDiffRows:
    """_smart_list_diff_rows: deep-diffs two lists of dicts (e.g. a step's inputs/outputs
    changing between versions) into added/removed/field-changed rows. Zero coverage before
    this review despite being a meaningfully complex chunk of the diff-humanisation logic."""

    def test_item_added_to_list(self):
        from app.features.activity_log.routes.activity_routes import _smart_list_diff_rows

        rows = _smart_list_diff_rows("Inputs", [], [{"name": "Water", "quantity": "1", "unit": "L"}])
        assert rows == [{"label": "Inputs", "before": None, "after": "'Water' added"}]

    def test_item_removed_from_list(self):
        from app.features.activity_log.routes.activity_routes import _smart_list_diff_rows

        rows = _smart_list_diff_rows("Inputs", [{"name": "Water", "quantity": "1"}], [])
        assert rows == [{"label": "Inputs", "before": "'Water' removed", "after": None}]

    def test_item_field_changed_within_list(self):
        from app.features.activity_log.routes.activity_routes import _smart_list_diff_rows

        before = [{"name": "Water", "quantity": "1", "unit": "L"}]
        after = [{"name": "Water", "quantity": "2", "unit": "L"}]
        rows = _smart_list_diff_rows("Inputs", before, after)
        assert len(rows) == 1
        assert rows[0]["label"] == "Inputs 'Water' – Quantity"
        assert rows[0]["before"] == "1"
        assert rows[0]["after"] == "2"

    def test_unkeyed_scalar_list_falls_back_to_whole_value_diff(self):
        from app.features.activity_log.routes.activity_routes import _smart_list_diff_rows

        rows = _smart_list_diff_rows("Tags", [{"foo": "a"}], [{"foo": "b"}])
        # neither dict has an id/name/label key, so this falls back to a single before/after row
        assert len(rows) == 1
        assert rows[0]["label"] == "Tags"

    def test_identical_lists_produce_no_rows(self):
        from app.features.activity_log.routes.activity_routes import _smart_list_diff_rows

        items = [{"name": "Water", "quantity": "1", "unit": "L"}]
        rows = _smart_list_diff_rows("Inputs", items, items)
        assert rows == []


class TestMergeInventoryLegacyAuditMatching:
    """_merge_inventory_legacy_audit's matched-event branch: a legacy entry within 10s of
    an existing entity_event augments that event's actor field rather than becoming a
    standalone timeline item. Only the unmatched (standalone) branch had coverage before
    this review."""

    def test_legacy_entry_within_10s_of_event_augments_actor_not_duplicates(self, db, org, app_client):
        from app.core.db.repositories.inventory_repo import InventoryRepository

        item = InventoryRepository(db).create_inventory_item(
            org_id=org.id,
            name="Matched Legacy Item",
            quantity="5",
            unit="kg",
            inventory_type="raw_material",
        )
        db.commit()
        created_event = (
            db.query(EntityEvent)
            .filter(EntityEvent.org_id == org.id, EntityEvent.entity_id == item.id)
            .order_by(EntityEvent.created_at.desc())
            .first()
        )
        assert created_event is not None
        item.extra_data = {
            **(item.extra_data or {}),
            "inventory_audit_history": [
                {
                    "timestamp_utc": created_event.created_at.isoformat(),
                    "operator_name": "Jane Operator",
                    "operator_email": "jane@myorg.example",
                    "user_id": str(uuid4()),
                }
            ],
        }
        db.add(item)
        db.commit()

        resp = app_client.get(f"/api/core/entities/inventory_item/{item.id}/story")
        body = resp.get_json()
        assert (
            len(body["events"]) == 1
        ), "a matched legacy entry augments the existing event, it does not add a second row"
        assert body["events"][0]["event_type"] != "inventory_item.legacy_entry"
        assert "Jane Operator" in body["events"][0]["actor"]

    def test_extra_data_present_but_no_legacy_history_key_is_a_noop(self, db, org, app_client):
        """Early-return branch: an item can have extra_data (e.g. notes, metadata) without
        ever having an inventory_audit_history key at all -- must not error."""
        from app.core.db.repositories.inventory_repo import InventoryRepository

        item = InventoryRepository(db).create_inventory_item(
            org_id=org.id,
            name="No Legacy History Item",
            quantity="5",
            unit="kg",
            inventory_type="raw_material",
            extra_data={"notes": "just some notes, no audit history key"},
        )
        db.commit()

        resp = app_client.get(f"/api/core/entities/inventory_item/{item.id}/story")
        assert resp.status_code == 200, resp.data
        # exactly the real inventory_item.created event, no synthetic legacy rows
        assert len(resp.get_json()["events"]) == 1

    def test_unmatched_legacy_entry_summary_includes_all_optional_fields(self, db, org, app_client):
        """_legacy_summary's supplier/batch/purchased/expiry branches -- exercised via a
        legacy entry far enough in the past that it never matches the item's own
        creation event (so it becomes a standalone inventory_item.legacy_entry row)."""
        from app.core.db.repositories.inventory_repo import InventoryRepository

        item = InventoryRepository(db).create_inventory_item(
            org_id=org.id,
            name="Rich Legacy Item",
            quantity="5",
            unit="kg",
            inventory_type="raw_material",
        )
        db.commit()
        item.extra_data = {
            "inventory_audit_history": [
                {
                    "timestamp_utc": (datetime.now(UTC) - timedelta(days=30)).isoformat(),
                    "operator_name": "Old Operator",
                    "operator_email": "old@myorg.example",
                    "quantity_added": "5",
                    "source_method": "barcode_scan",
                    "supplier": "Acme Supplies",
                    "supplier_batch_number": "B-42",
                    "purchase_date": "2026-01-01",
                    "expiry_date": "2027-01-01",
                }
            ]
        }
        db.add(item)
        db.commit()

        resp = app_client.get(f"/api/core/entities/inventory_item/{item.id}/story")
        body = resp.get_json()
        legacy_rows = [e for e in body["events"] if e["event_type"] == "inventory_item.legacy_entry"]
        assert len(legacy_rows) == 1
        summary = legacy_rows[0]["summary"]
        assert "Added 5" in summary
        assert "via barcode scan" in summary
        assert "supplier: Acme Supplies" in summary
        assert "batch: B-42" in summary
        assert "purchased: 2026-01-01" in summary
        assert "expiry: 2027-01-01" in summary


class TestFmtFieldValue:
    """_fmt_field_value/_fmt_sub_val: value-formatting helpers used throughout
    _build_diff_rows and _smart_list_diff_rows. Several branches (bool, label-keyed list
    items, inventory_type mapping) had zero direct coverage before this review."""

    def test_bool_true_renders_yes(self):
        from app.features.activity_log.routes.activity_routes import _fmt_field_value

        assert _fmt_field_value(True) == "Yes"

    def test_bool_false_renders_no(self):
        from app.features.activity_log.routes.activity_routes import _fmt_field_value

        assert _fmt_field_value(False) == "No"

    def test_list_of_dicts_with_label_key_joins_labels(self):
        from app.features.activity_log.routes.activity_routes import _fmt_field_value

        val = [{"label": "Confirm temp", "type": "checkbox"}, {"label": "Sign off"}]
        assert _fmt_field_value(val) == "Confirm temp (checkbox), Sign off"

    def test_list_of_dicts_with_name_and_quantity(self):
        from app.features.activity_log.routes.activity_routes import _fmt_field_value

        val = [{"name": "Water", "quantity": "1", "unit": "L"}]
        assert _fmt_field_value(val) == "Water (1 L)"

    def test_empty_list_renders_none_marker(self):
        from app.features.activity_log.routes.activity_routes import _fmt_field_value

        assert _fmt_field_value([]) == "(none)"

    def test_inventory_type_string_maps_to_label(self):
        from app.features.activity_log.routes.activity_routes import _fmt_field_value

        assert _fmt_field_value("work_in_progress") == "Work in progress"

    def test_fmt_sub_val_bool(self):
        from app.features.activity_log.routes.activity_routes import _fmt_sub_val

        assert _fmt_sub_val(True) == "Yes"

    def test_fmt_sub_val_complex_value(self):
        from app.features.activity_log.routes.activity_routes import _fmt_sub_val

        assert _fmt_sub_val(["a", "b"]) == "(complex)"
        assert _fmt_sub_val({"a": 1}) == "(complex)"

    def test_fmt_sub_val_inventory_type_field_maps_to_label(self):
        from app.features.activity_log.routes.activity_routes import _fmt_sub_val

        assert _fmt_sub_val("final_product", field="inventory_type") == "Final product"


class TestBuildDiffRowsListDispatch:
    def test_build_diff_rows_dispatches_list_of_dicts_to_smart_list_diff(self):
        from app.features.activity_log.routes.activity_routes import _build_diff_rows

        diff = {
            "inputs": {
                "before": [{"name": "Water", "quantity": "1", "unit": "L"}],
                "after": [{"name": "Water", "quantity": "2", "unit": "L"}],
            }
        }
        rows = _build_diff_rows(diff)
        assert len(rows) == 1
        assert rows[0]["label"] == "Inputs 'Water' – Quantity"


class TestStepAddedDiffRowsMalformedEntries:
    def test_non_dict_items_in_inputs_outputs_prompts_are_skipped_not_raised(self):
        from app.features.activity_log.routes.activity_routes import _step_added_diff_rows

        rows = _step_added_diff_rows(
            {
                "description": "Mix",
                "inputs": ["not-a-dict", {"name": "Water"}],
                "outputs": [42, {"name": "Mixture"}],
                "execution_prompts": [None, {"label": "Confirm"}],
            }
        )
        labels = [r["label"] for r in rows]
        assert labels == ["Description", "Input", "Output", "Prompt"]


class TestInventoryCreatedSummarySupplierBatch:
    def test_supplier_and_batch_appear_in_summary(self):
        from app.features.activity_log.routes.activity_routes import _human_summary

        ev = FakeEvent(
            "inventory_item.created",
            payload={
                "quantity": "10",
                "unit": "kg",
                "inventory_type": "raw_material",
                "supplier": "Acme Supplies",
                "supplier_batch_number": "B-42",
            },
        )
        summary = _human_summary(ev)
        assert "supplier: Acme Supplies" in summary
        assert "batch: B-42" in summary


class TestActivityLogAccessDeniedLogging:
    """[REGRESSION] observability: same rationale and pattern as
    tests/test_traceability.py::TestTraceAccessDeniedLogging -- a story/summary lookup that
    resolves to nothing for the caller's org must be observable server-side, even though the
    route response can't distinguish "not yours" from "doesn't exist" (AC3/AC10). Added this
    review as defense-in-depth telemetry alongside the F1 fix. Mutation this catches:
    dropping the `_log_activity_access_denied(...)` call at either site and keeping only the
    empty-result return."""

    def test_story_for_nonexistent_or_cross_org_entity_emits_access_denied(self, app_client, org, caplog):
        import logging

        with caplog.at_level(logging.WARNING):
            resp = app_client.get(f"/api/core/entities/inventory_item/{uuid4()}/story")
        assert resp.status_code == 200, resp.data
        assert resp.get_json()["events"] == []
        denials = [r for r in caplog.records if "access_denied" in r.getMessage()]
        assert denials, f"empty story lookup was not logged: {[r.getMessage() for r in caplog.records]}"
        assert "entity_not_found_or_cross_org" in denials[0].getMessage()

    def test_summary_for_nonexistent_or_cross_org_entity_emits_access_denied(self, app_client, org, caplog):
        import logging

        with caplog.at_level(logging.WARNING):
            resp = app_client.get(f"/api/core/entities/inventory_item/{uuid4()}/summary")
        assert resp.status_code == 200, resp.data
        assert resp.get_json()["summary"] == {}
        denials = [r for r in caplog.records if "access_denied" in r.getMessage()]
        assert denials, f"empty summary lookup was not logged: {[r.getMessage() for r in caplog.records]}"

    def test_story_for_real_own_org_entity_does_not_emit_access_denied(self, db, org, app_client, caplog):
        """The log must not fire on ordinary, legitimate traffic -- only on a lookup that
        resolves to nothing."""
        import logging

        item = InventoryItemFactory(org_id=org.id, name="Real Item For Logging Test", quantity="1", unit="kg")
        db.commit()

        with caplog.at_level(logging.WARNING):
            resp = app_client.get(f"/api/core/entities/inventory_item/{item.id}/story")
        assert resp.status_code == 200, resp.data
        assert resp.get_json()["events"] != []
        denials = [r for r in caplog.records if "access_denied" in r.getMessage()]
        assert not denials, f"a real, own-org lookup must not log access_denied: {[r.getMessage() for r in denials]}"
