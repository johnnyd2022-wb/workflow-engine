"""Regression tests for the traceability (sourcemap) audit (review-feature, spec
.agents/specs/traceability.md).

Each test below is marked `[REGRESSION]` and reproduces one of the four findings from
`.agents/reports/traceability/security-audit.md`, verified RED against the code at the
review baseline (branch review/traceability, base 64e7ae6) before the fix in the same
commit. The mandatory cross-tenant probe for F1 (the headline finding — a cross-tenant
entity-state leak) lives at the API level in
`tests/e2e/traceability/test_tenant_isolation.py::test_ac9_temporal_trace_root_state_not_visible_cross_tenant`
via a real two-org browser session; F2-F4 are pure backend/API-shape bugs with no
UI-observable symptom, so they're covered here instead at the `app_client` level, matching
this file's sibling `tests/test_inventory.py`.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.core.db.models.entity_event import EntityEvent
from app.core.db.models.organisation import Organisation
from app.core.security.auth_service import AuthService
from tests.dag_traversal_helpers import build_linear_dag
from tests.factories import OrganisationFactory


@pytest.fixture
def org(db):
    organisation = OrganisationFactory(name=f"Traceability Audit Org {uuid4()}")
    db.commit()
    org_id = organisation.id
    yield organisation
    db.rollback()
    _purge_org(db, org_id)


@pytest.fixture
def other_org(db):
    organisation = OrganisationFactory(name=f"Traceability Audit Neighbour {uuid4()}")
    db.commit()
    org_id = organisation.id
    yield organisation
    db.rollback()
    _purge_org(db, org_id)


def _purge_org(db, org_id):
    """Teardown ordering matches tests/test_inventory.py::_purge_org -- children before
    parent, failures swallowed so a bad teardown doesn't masquerade as the next test's
    setup failure."""
    from app.core.db.models.entity_event import EntityEvent
    from app.core.db.models.entity_event_summary import EntityEventSummary
    from app.core.db.models.execution import Execution
    from app.core.db.models.execution_step import ExecutionStep
    from app.core.db.models.inventory_item import InventoryItem
    from app.core.db.models.process import Process
    from app.core.db.models.process_version import ProcessVersion
    from app.core.db.models.step import Step

    try:
        for model in (EntityEvent, EntityEventSummary, InventoryItem):
            db.query(model).filter(model.org_id == org_id).delete(synchronize_session=False)
        exec_ids = [e.id for e in db.query(Execution).filter(Execution.org_id == org_id).all()]
        if exec_ids:
            db.query(ExecutionStep).filter(ExecutionStep.execution_id.in_(exec_ids)).delete(synchronize_session=False)
        db.query(Execution).filter(Execution.org_id == org_id).delete(synchronize_session=False)
        proc_ids = [p.id for p in db.query(Process).filter(Process.org_id == org_id).all()]
        if proc_ids:
            db.query(Step).filter(Step.process_id.in_(proc_ids)).delete(synchronize_session=False)
        db.query(ProcessVersion).filter(ProcessVersion.org_id == org_id).delete(synchronize_session=False)
        db.query(Process).filter(Process.org_id == org_id).delete(synchronize_session=False)
        db.query(Organisation).filter(Organisation.id == org_id).delete(synchronize_session=False)
        db.commit()
    except Exception:
        db.rollback()


@pytest.fixture
def user(db, org):
    from app.core.db.repositories.user_repo import UserRepository

    u = UserRepository(db).create_user(
        org_id=org.id,
        email=f"trace_{uuid4()}@test.com",
        password_hash=AuthService.hash_password("TestPass123!"),
    )
    db.commit()
    yield u


@pytest.fixture
def app_client(db, org, user):
    """Authenticated Flask test client scoped to `org` -- same pattern as
    tests/test_inventory.py::app_client."""
    from app.api.app_factory import create_app

    flask_app = create_app()
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False

    with flask_app.test_client() as client:
        client.environ_base["wsgi.url_scheme"] = "https"
        client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
        with flask_app.app_context():
            resp = client.post(
                "/auth/login",
                json={"email": user.email, "password": "TestPass123!"},
                content_type="application/json",
            )
            assert resp.status_code in (200, 201), f"Login failed: {resp.data}"
            yield client


@pytest.fixture
def dag(db, org):
    return build_linear_dag(db, org.id)


class TestCurrentStateTraceBranch:
    """F2 [REGRESSION]: POST /api/core/sourcemap/trace with no `as_of` imported a module
    (app.features.workflow_engine.dagtraversal) that does not exist anywhere in the repo,
    and even if it had, called trace_forward/trace_backward with the wrong signature and
    treated their dict return as an object with .nodes/.edges. Every request into this
    branch raised inside the try and was swallowed by a bare `except Exception`, always
    returning 500. Fixed by routing to the real app.core.backend.dagtraversal functions,
    matching how trace_raw_material/trace_inventory_backward already call them."""

    def test_current_state_trace_returns_graph_not_500(self, app_client, dag):
        resp = app_client.post(
            "/api/core/sourcemap/trace",
            json={"root_type": "inventory_item", "root_id": str(dag["r1_id"]), "depth": 5},
        )
        assert resp.status_code == 200, resp.data
        body = resp.get_json()
        assert body["is_current"] is True
        assert body["as_of"] is None
        assert body["root"]["id"] == str(dag["r1_id"])
        node_ids = {n["id"] for n in body["nodes"]}
        # Forward trace from R1 must surface the whole downstream chain.
        assert str(dag["w1_id"]) in node_ids
        assert str(dag["f1_id"]) in node_ids

    def test_bidirectional_equals_separate_traces_with_fewer_queries(self, db, org):
        """trace_bidirectional shares one DAGTracer across both directions, so the org's
        step/produced-item graph is bulk-loaded once, not once per direction. Same nodes
        and edges as the two separate calls; strictly fewer DB round trips."""
        from sqlalchemy import event

        from app.core.backend.dagtraversal import trace_backward, trace_bidirectional, trace_forward
        from app.core.db import engine
        from app.core.security.tenant_scope import tenant_scope

        d = build_linear_dag(db, org.id)
        db.commit()
        root = d["w1_id"]

        counter = {"n": 0}
        listener = lambda *a, **k: counter.__setitem__("n", counter["n"] + 1)  # noqa: E731
        event.listen(engine, "after_cursor_execute", listener)
        try:
            with tenant_scope(org.id):
                counter["n"] = 0
                fwd = trace_forward(org.id, db, root, include_quantity_filter=False, root_item_id=root)
                bwd = trace_backward(org.id, db, root, include_quantity_filter=False, traced_item_id=root)
                separate_queries = counter["n"]

                counter["n"] = 0
                both = trace_bidirectional(org.id, db, root, include_quantity_filter=False, root_item_id=root)
                combined_queries = counter["n"]
        finally:
            event.remove(engine, "after_cursor_execute", listener)

        assert {n["id"] for n in both["forward"]["items"]} == {n["id"] for n in fwd["items"]}
        assert {n["id"] for n in both["backward"]["items"]} == {n["id"] for n in bwd["items"]}
        assert {(e["from_id"], e["to_id"]) for e in both["forward"]["connections"]} == {
            (e["from_id"], e["to_id"]) for e in fwd["connections"]
        }
        assert combined_queries < separate_queries, (separate_queries, combined_queries)

    def test_current_state_trace_unknown_item_returns_404_not_500(self, app_client, org):
        resp = app_client.post(
            "/api/core/sourcemap/trace",
            json={"root_type": "inventory_item", "root_id": str(uuid4())},
        )
        assert resp.status_code == 404, resp.data
        assert resp.get_json()["error"] == "Item not found"

    def test_current_state_trace_rejects_other_orgs_item(self, app_client, org, other_org, db):
        """Same [id, org_id] scoping the as_of branch already had -- confirms the fix
        didn't regress the pre-existing 404-on-cross-org guarantee at line ~5766."""
        from tests.dag_traversal_helpers import build_linear_dag as _build

        other_dag = _build(db, other_org.id)
        resp = app_client.post(
            "/api/core/sourcemap/trace",
            json={"root_type": "inventory_item", "root_id": str(other_dag["r1_id"])},
        )
        assert resp.status_code == 404, resp.data


class TestSourcemapObjectsPageLimitParsing:
    """F3 [REGRESSION]: GET /api/core/sourcemap/objects parsed page/limit with bare int(),
    no try/except -- a non-numeric value raised an unhandled ValueError -> 500."""

    def test_non_numeric_page_returns_400_not_500(self, app_client):
        resp = app_client.get("/api/core/sourcemap/objects?page=abc")
        assert resp.status_code == 400, resp.data
        assert "error" in resp.get_json()

    def test_non_numeric_limit_returns_400_not_500(self, app_client):
        resp = app_client.get("/api/core/sourcemap/objects?limit=xyz")
        assert resp.status_code == 400, resp.data

    def test_valid_page_and_limit_still_work(self, app_client, dag):
        resp = app_client.get("/api/core/sourcemap/objects?page=1&limit=10")
        assert resp.status_code == 200, resp.data
        body = resp.get_json()
        assert "objects" in body and "total" in body and body["page"] == 1


class TestSourcemapTraceDepthParsing:
    """F4 [REGRESSION]: POST /api/core/sourcemap/trace parsed `depth` with bare int()
    before root_id was even validated -- a bad depth alongside a well-formed root_id
    raised an unhandled ValueError -> 500, pre-empting the documented 400-on-bad-root_id
    path (AC11) entirely."""

    def test_non_numeric_depth_returns_400_not_500(self, app_client, dag):
        resp = app_client.post(
            "/api/core/sourcemap/trace",
            json={"root_type": "inventory_item", "root_id": str(dag["r1_id"]), "depth": "abc"},
        )
        assert resp.status_code == 400, resp.data

    def test_non_numeric_depth_with_invalid_root_id_still_400s(self, app_client):
        """Bad depth must not prevent the root_id validation path from ever running --
        this is the specific ordering bug F4 describes."""
        resp = app_client.post(
            "/api/core/sourcemap/trace",
            json={"root_type": "inventory_item", "root_id": "not-a-uuid", "depth": "abc"},
        )
        assert resp.status_code == 400, resp.data


def _next_event_seq(db, org_id) -> int:
    """entity_events.seq has no DB default (migration entity_events_seq_noident_001); tests
    that build the row directly allocate it like EventWriter does (per-org MAX+1)."""
    return int(
        db.execute(
            text("SELECT COALESCE(MAX(seq), 0) + 1 FROM entity_events WHERE org_id = :o"), {"o": str(org_id)}
        ).scalar()
    )


def _plant_step_completed_event(
    db, org_id, *, execution_id, item_id, role, quantity="2", unit="kg", when=None, execution_data=None
):
    """Directly write an execution.step_completed EntityEvent -- this is test setup for
    TemporalDAGTracer, which reads entity_events, not a stand-in for EventWriter (platform
    layer, out of scope here). `role` is "consumed" or "produced", matching the payload
    shapes TemporalDAGTracer.trace() reads (items_consumed / items_produced). `execution_data`
    mirrors what ExecutionRepository.complete_step puts in the real event payload -- used to
    exercise batch_id / custom_prompts node metadata."""
    key = "items_consumed" if role == "consumed" else "items_produced"
    payload = {"execution_id": str(execution_id), key: [{"item_id": str(item_id), "quantity": quantity, "unit": unit}]}
    if execution_data is not None:
        payload["execution_data"] = execution_data
    ev = EntityEvent(
        org_id=org_id,
        seq=_next_event_seq(db, org_id),
        event_type="execution.step_completed",
        entity_type="execution",
        entity_id=execution_id,
        actor_type="user",
        actor_label="tracer_test@test.com",
        payload=payload,
        created_at=when or datetime.now(UTC),
    )
    db.add(ev)
    db.commit()
    return ev


class TestTemporalDAGTracerUnit:
    """Direct unit coverage for TemporalDAGTracer (app/core/backend/temporal_dag_tracer.py)
    -- zero test references existed anywhere in the suite before this review
    (baseline.md). Exercises the BFS edge-building/traversal that
    tests/e2e/traceability/test_tenant_isolation.py's API-level probe doesn't reach."""

    def test_trace_builds_consumed_and_produced_edges_across_two_hops(self, db, org):
        from app.core.backend.temporal_dag_tracer import TemporalDAGTracer

        raw_id, exec_id, wip_id = uuid4(), uuid4(), uuid4()
        now = datetime.now(UTC)
        _plant_step_completed_event(db, org.id, execution_id=exec_id, item_id=raw_id, role="consumed", when=now)
        _plant_step_completed_event(db, org.id, execution_id=exec_id, item_id=wip_id, role="produced", when=now)

        tracer = TemporalDAGTracer(db, org.id, now + timedelta(minutes=1), max_depth=5)
        result = tracer.trace(raw_id, "inventory_item")

        assert result["root_id"] == str(raw_id)
        node_ids = {n["id"] for n in result["nodes"]}
        assert str(exec_id) in node_ids, "execution node must be reachable via the consumed_by edge"
        assert str(wip_id) in node_ids, "produced item must be reachable through the execution"
        relationships = {(e["from"], e["to"], e["relationship"]) for e in result["edges"]}
        assert (str(raw_id), str(exec_id), "consumed_by") in relationships
        assert (str(exec_id), str(wip_id), "produced") in relationships

    def test_trace_excludes_events_after_as_of(self, db, org):
        from app.core.backend.temporal_dag_tracer import TemporalDAGTracer

        raw_id, exec_id, wip_id = uuid4(), uuid4(), uuid4()
        now = datetime.now(UTC)
        _plant_step_completed_event(db, org.id, execution_id=exec_id, item_id=raw_id, role="consumed", when=now)
        _plant_step_completed_event(
            db, org.id, execution_id=exec_id, item_id=wip_id, role="produced", when=now + timedelta(days=1)
        )

        tracer = TemporalDAGTracer(db, org.id, now + timedelta(hours=1), max_depth=5)
        result = tracer.trace(raw_id, "inventory_item")

        node_ids = {n["id"] for n in result["nodes"]}
        assert str(exec_id) in node_ids
        assert str(wip_id) not in node_ids, "event dated after as_of must not appear in the graph"

    def test_trace_never_pulls_in_another_orgs_edges(self, db, org, other_org):
        """AC14: a step_completed event belonging to another org must never contribute an
        edge to this org's graph, even when both orgs reference the same execution_id by
        coincidence (edges are entirely org-scoped at the query level, not merely filtered
        post-hoc)."""
        from app.core.backend.temporal_dag_tracer import TemporalDAGTracer

        shared_exec_id = uuid4()
        raw_id = uuid4()
        foreign_wip_id = uuid4()
        now = datetime.now(UTC)
        _plant_step_completed_event(db, org.id, execution_id=shared_exec_id, item_id=raw_id, role="consumed", when=now)
        _plant_step_completed_event(
            db, other_org.id, execution_id=shared_exec_id, item_id=foreign_wip_id, role="produced", when=now
        )

        tracer = TemporalDAGTracer(db, org.id, now + timedelta(minutes=1), max_depth=5)
        result = tracer.trace(raw_id, "inventory_item")

        node_ids = {n["id"] for n in result["nodes"]}
        assert str(foreign_wip_id) not in node_ids, "other org's produced-item edge leaked into this org's graph"

    def test_timeline_includes_all_connected_events_ordered_oldest_first(self, db, org):
        from app.core.backend.temporal_dag_tracer import TemporalDAGTracer

        raw_id, exec_id = uuid4(), uuid4()
        now = datetime.now(UTC)
        _plant_step_completed_event(db, org.id, execution_id=exec_id, item_id=raw_id, role="consumed", when=now)
        base_seq = _next_event_seq(db, org.id)
        for i in range(5):
            db.add(
                EntityEvent(
                    org_id=org.id,
                    seq=base_seq + i,
                    event_type="inventory_item.quantity_adjusted",
                    entity_type="inventory_item",
                    entity_id=raw_id,
                    actor_type="user",
                    payload={"delta": i},
                    created_at=now + timedelta(seconds=i + 1),
                )
            )
        db.commit()

        tracer = TemporalDAGTracer(db, org.id, now + timedelta(minutes=1), max_depth=5)
        result = tracer.trace(raw_id, "inventory_item")

        timeline = result["timeline"]
        assert len(timeline) == 6  # 1 step_completed + 5 quantity_adjusted, all on raw_id/exec_id nodes
        ats = [ev["at"] for ev in timeline]
        assert ats == sorted(ats), "timeline must be ordered oldest-first"

    def test_produced_item_node_carries_batch_id_and_custom_prompts(self, db, org):
        """The "Batch number" compliance/traceability prompt (and any other org-defined
        prompt) already rides along in the step_completed event's execution_data -- non-root
        nodes should surface it instead of always being state: None (AC17 covers `state`
        specifically; batch_id/custom_prompts are new, separate fields)."""
        from app.core.backend.temporal_dag_tracer import TemporalDAGTracer

        raw_id, exec_id, wip_id = uuid4(), uuid4(), uuid4()
        now = datetime.now(UTC)
        _plant_step_completed_event(db, org.id, execution_id=exec_id, item_id=raw_id, role="consumed", when=now)
        _plant_step_completed_event(
            db,
            org.id,
            execution_id=exec_id,
            item_id=wip_id,
            role="produced",
            when=now,
            execution_data={
                "Batch number": "VAT55",
                "Botanical origin": "Wairarapa rhubarb",
                # completed_by/completed_by_email/completed_by_user_id/completed_at are all
                # internal audit keys _split_temporal_prompts excludes -- they're already
                # shown elsewhere (the "Completed by" row), not "custom prompt metadata".
                "completed_by": "op@test.com",
                "completed_by_email": "op@test.com",
                "completed_by_user_id": str(uuid4()),
                "completed_at": now.isoformat(),
            },
        )

        tracer = TemporalDAGTracer(db, org.id, now + timedelta(minutes=1), max_depth=5)
        result = tracer.trace(raw_id, "inventory_item")

        by_id = {n["id"]: n for n in result["nodes"]}
        wip_node = by_id[str(wip_id)]
        assert wip_node["batch_id"] == "VAT55"
        assert wip_node["custom_prompts"] == {"Botanical origin": "Wairarapa rhubarb"}
        assert wip_node["state"] is None, "AC17: non-root state stays None; only new fields are added"

        exec_node = by_id[str(exec_id)]
        assert exec_node["batch_id"] == "VAT55"

    def test_node_metadata_never_pulls_in_another_orgs_batch_id(self, db, org, other_org):
        from app.core.backend.temporal_dag_tracer import TemporalDAGTracer

        shared_exec_id = uuid4()
        raw_id = uuid4()
        foreign_wip_id = uuid4()
        now = datetime.now(UTC)
        _plant_step_completed_event(db, org.id, execution_id=shared_exec_id, item_id=raw_id, role="consumed", when=now)
        _plant_step_completed_event(
            db,
            other_org.id,
            execution_id=shared_exec_id,
            item_id=foreign_wip_id,
            role="produced",
            when=now,
            execution_data={"Batch number": "OTHER-ORG-BATCH"},
        )

        tracer = TemporalDAGTracer(db, org.id, now + timedelta(minutes=1), max_depth=5)
        result = tracer.trace(raw_id, "inventory_item")

        node_ids = {n["id"] for n in result["nodes"]}
        assert str(foreign_wip_id) not in node_ids
        assert all(n.get("batch_id") != "OTHER-ORG-BATCH" for n in result["nodes"])


class TestSourcemapObjectsTenantScoping:
    """AC18: every sub-query in GET /api/core/sourcemap/objects filters by the caller's
    org_id. No dedicated coverage existed before this review (baseline.md)."""

    def test_objects_index_excludes_other_orgs_items(self, app_client, org, other_org, db):
        from tests.dag_traversal_helpers import build_linear_dag as _build

        own_dag = build_linear_dag(db, org.id)
        other_dag = _build(db, other_org.id)

        resp = app_client.get("/api/core/sourcemap/objects?type=inventory_item&limit=200")
        assert resp.status_code == 200, resp.data
        ids = {o["id"] for o in resp.get_json()["objects"]}
        assert str(own_dag["r1_id"]) in ids
        assert str(other_dag["r1_id"]) not in ids

    @pytest.mark.parametrize(
        "entity_type,own_key,other_key",
        [("execution", "execution_id", "execution_id"), ("process", "process_id", "process_id")],
    )
    def test_objects_index_excludes_other_orgs_non_inventory_types(
        self, app_client, org, other_org, db, entity_type, own_key, other_key
    ):
        """AC18 for the two sub-queries test_objects_index_excludes_other_orgs_items doesn't
        reach -- sourcemap_objects makes three independent org-scoped queries (InventoryItem,
        Execution, Process), and only the first was covered before test-evaluator flagged
        the gap."""
        from tests.dag_traversal_helpers import build_linear_dag as _build

        own_dag = build_linear_dag(db, org.id)
        other_dag = _build(db, other_org.id)

        resp = app_client.get(f"/api/core/sourcemap/objects?type={entity_type}&limit=200")
        assert resp.status_code == 200, resp.data
        ids = {o["id"] for o in resp.get_json()["objects"]}
        assert str(own_dag[own_key]) in ids
        assert str(other_dag[other_key]) not in ids


class TestTraceAccessDeniedLogging:
    """[REGRESSION] observability: a rejected cross-org/nonexistent trace lookup must be
    observable server-side even though the route response can't distinguish "not yours"
    from "doesn't exist" (AC2/AC6). Added this review -- none of these three routes logged
    anything on their 404 path before. Mutation this catches: dropping the
    `_log_trace_access_denied(...)` call at each site and keeping only the `return`."""

    def test_forward_trace_not_found_emits_access_denied(self, app_client, caplog):
        import logging

        with caplog.at_level(logging.WARNING):
            resp = app_client.get(f"/api/core/inventory/trace/{uuid4()}")
        assert resp.status_code == 404, resp.data
        denials = [r for r in caplog.records if "access_denied" in r.getMessage()]
        assert denials, f"not found lookup was not logged: {[r.getMessage() for r in caplog.records]}"
        assert "inventory_item_not_found_or_cross_org" in denials[0].getMessage()

    def test_backward_trace_not_found_emits_access_denied(self, app_client, caplog):
        import logging

        with caplog.at_level(logging.WARNING):
            resp = app_client.get(f"/api/core/inventory/trace-backward/{uuid4()}")
        assert resp.status_code == 404, resp.data
        denials = [r for r in caplog.records if "access_denied" in r.getMessage()]
        assert denials, f"not found lookup was not logged: {[r.getMessage() for r in caplog.records]}"

    def test_current_state_sourcemap_trace_not_found_emits_access_denied(self, app_client, caplog):
        import logging

        with caplog.at_level(logging.WARNING):
            resp = app_client.post(
                "/api/core/sourcemap/trace",
                json={"root_type": "inventory_item", "root_id": str(uuid4())},
            )
        assert resp.status_code == 404, resp.data
        denials = [r for r in caplog.records if "access_denied" in r.getMessage()]
        assert denials, f"not found lookup was not logged: {[r.getMessage() for r in caplog.records]}"
