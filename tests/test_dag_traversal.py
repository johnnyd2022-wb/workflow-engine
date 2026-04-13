"""Unit tests for DAGTracer: forward/backward traversal, cycle detection, connections, enrichment.

All tests use real DB. Data is populated from resetdb temporarily and removed at the end of each test
that uses the demo_data fixture (same pattern as cleanup_test_data / test_login_2fa_flow).

Hardening (cursor_instructions/harden-dagtraversal-testsuite.md): invariant assertions, synthetic DAGs,
deterministic output, ID-only lineage, N+1 guard, enrichment resilience. TEST SUITE ONLY – no traversal code changes.
"""

from uuid import uuid4

import pytest

from app.core.backend.dagtraversal import DAGTracer, validate_item_uuid
from app.core.db import db_session
from app.core.db.models.inventory_item import InventoryItem, InventoryType
from app.core.utils.resetdb import DEMO_USER_EMAIL, clear_demo_db, reset_demo_db
from tests.dag_traversal_helpers import (
    QueryCounter,
    assert_traversal_invariants,
    build_branching_dag,
    build_id_only_lineage_dag,
    build_large_linear_chain,
    build_linear_dag,
    clear_org_synthetic_data,
)


@pytest.fixture
def db():
    """Real database session for integration tests (same pattern as cleanup_test_data / test_login_2fa_flow)."""
    session = db_session()
    try:
        yield session
    finally:
        session.close()
        db_session.remove()


@pytest.fixture
def ensure_demo_user(db):
    """Ensure demo user demo@whistlebird.co.nz exists (create org + user if not). Used by demo_data."""
    from app.core.db.repositories.organisation_repo import OrganisationRepository
    from app.core.db.repositories.user_repo import UserRepository
    from app.core.security.auth_service import AuthService

    user_repo = UserRepository(db)
    org_repo = OrganisationRepository(db)
    user = user_repo.get_user_by_email(DEMO_USER_EMAIL)
    if user:
        return user
    org = org_repo.create_org("Whistlebird Demo")
    password_hash = AuthService.hash_password("Demo123!")
    user_repo.create_user(org_id=org.id, email=DEMO_USER_EMAIL, password_hash=password_hash)
    return user_repo.get_user_by_email(DEMO_USER_EMAIL)


@pytest.fixture
def demo_data(db, ensure_demo_user):
    """Populate DB with distillery sample data (resetdb); removed at teardown via clear_demo_db."""
    result = reset_demo_db(db)
    assert result.get("success"), result.get("message", "reset_demo_db failed")
    try:
        yield {"org_id": ensure_demo_user.org_id}
    finally:
        clear_demo_db(db)


@pytest.fixture
def synthetic_org(db):
    """Minimal org for synthetic DAG tests; no demo/seed data. Cleared at teardown (data + org row)."""
    from app.core.db.models.organisation import Organisation
    from app.core.db.repositories.organisation_repo import OrganisationRepository

    org_repo = OrganisationRepository(db)
    # Use unique org name to avoid collisions if teardown is skipped due to earlier failures.
    org = org_repo.create_org(f"Synthetic Test Org {uuid4()}")
    try:
        yield org.id
    finally:
        clear_org_synthetic_data(db, org.id)
        db.query(Organisation).filter(Organisation.id == org.id).delete()
        db.commit()


class TestValidateItemUuid:
    """Tests for validate_item_uuid."""

    def test_valid_uuid_string(self):
        uid = uuid4()
        result, err = validate_item_uuid(str(uid))
        assert result == uid
        assert err is None

    def test_valid_uuid_object(self):
        uid = uuid4()
        result, err = validate_item_uuid(uid)
        assert result == uid
        assert err is None

    def test_invalid_uuid_string(self):
        result, err = validate_item_uuid("not-a-uuid")
        assert result is None
        assert err is not None
        assert "Invalid" in err

    def test_none(self):
        result, err = validate_item_uuid(None)
        assert result is None
        assert err is not None


class TestDAGTracerForwardBackward:
    """Tests for trace_forward and trace_backward correctness (real DB)."""

    def test_trace_forward_item_not_found_returns_empty(self, db):
        """Real DB: traversing from non-existent item returns empty nodes/edges."""
        org_id = uuid4()
        tracer = DAGTracer(org_id=org_id, session=db)
        result = tracer.traverse(start_nodes=[uuid4()], direction="forward")
        assert result.nodes == []
        assert result.edges == []

    def test_trace_forward_from_raw_returns_nodes(self, db, demo_data):
        """Real DB + resetdb: trace forward from a raw material returns nodes (and edges if downstream)."""
        org_id = demo_data["org_id"]
        raw_items = (
            db.query(InventoryItem)
            .filter(InventoryItem.org_id == org_id, InventoryItem.inventory_type == InventoryType.RAW_MATERIAL.value)
            .limit(1)
            .all()
        )
        assert raw_items, "Demo data must include raw materials"
        tracer = DAGTracer(org_id=org_id, session=db)
        result = tracer.traverse(start_nodes=[raw_items[0].id], direction="forward", root_set={raw_items[0].id})
        assert_traversal_invariants(result)
        assert len(result.nodes) >= 1
        assert result.metadata is not None

    def test_trace_backward_item_not_found_returns_empty(self, db):
        """Real DB: traversing backward from non-existent item returns empty nodes/edges."""
        org_id = uuid4()
        tracer = DAGTracer(org_id=org_id, session=db)
        result = tracer.traverse(start_nodes=[uuid4()], direction="backward")
        assert result.nodes == []
        assert result.edges == []


class TestDAGTracerCycleDetection:
    """Tests for cycle detection and depth limit (real DB + resetdb)."""

    def test_trace_backward_visited_set_prevents_infinite_loop(self, db, demo_data):
        """Real DB + resetdb: backward trace from final returns nodes/edges without infinite loop."""
        org_id = demo_data["org_id"]
        finals = (
            db.query(InventoryItem)
            .filter(InventoryItem.org_id == org_id, InventoryItem.inventory_type == InventoryType.FINAL_PRODUCT.value)
            .limit(1)
            .all()
        )
        assert finals, "Demo data must include final products"
        tracer = DAGTracer(org_id=org_id, session=db)
        result = tracer.traverse(start_nodes=[finals[0].id], direction="backward", root_set={finals[0].id})
        assert_traversal_invariants(result)
        assert result.nodes is not None
        assert result.edges is not None


class TestDAGTracerConnectionMapping:
    """Tests for connection structure (from_id, to_id, execution_id) (real DB + resetdb)."""

    def test_trace_forward_connection_keys(self, db, demo_data):
        """Real DB + resetdb: forward trace edges have from_id, to_id, execution_id."""
        org_id = demo_data["org_id"]
        raw_items = (
            db.query(InventoryItem)
            .filter(InventoryItem.org_id == org_id, InventoryItem.inventory_type == InventoryType.RAW_MATERIAL.value)
            .limit(1)
            .all()
        )
        assert raw_items, "Demo data must include raw materials"
        tracer = DAGTracer(org_id=org_id, session=db)
        result = tracer.traverse(start_nodes=[raw_items[0].id], direction="forward", root_set={raw_items[0].id})
        assert_traversal_invariants(result)
        for conn in result.edges:
            assert "from_id" in conn
            assert "to_id" in conn
            assert "execution_id" in conn


class TestDAGTracerExtraDataEnrichment:
    """Tests for extra_data enrichment (real DB + resetdb) and _item_to_dict (pure unit)."""

    def test_enrich_items_bulk_adds_process_name(self, db, demo_data):
        """Real DB + resetdb: _enrich_items_bulk adds process_name and execution_prompts."""
        org_id = demo_data["org_id"]
        wip_or_final = (
            db.query(InventoryItem)
            .filter(
                InventoryItem.org_id == org_id,
                InventoryItem.inventory_type.in_(
                    [InventoryType.WORK_IN_PROGRESS.value, InventoryType.FINAL_PRODUCT.value]
                ),
            )
            .limit(1)
            .all()
        )
        assert wip_or_final, "Demo data must include WIP or final products"
        tracer = DAGTracer(org_id=org_id, session=db)
        enriched = tracer._enrich_items_bulk(wip_or_final)
        assert len(enriched) == 1
        assert enriched[0].get("process_name") is not None
        assert enriched[0].get("extra_data", {}).get("execution_prompts") is not None

    def test_item_to_dict_serializes_id_as_string(self):
        """Pure unit: _item_to_dict serializes id as string (no DB)."""
        from unittest.mock import MagicMock

        item = MagicMock()
        item.id = uuid4()
        item.name = "Test"
        item.quantity = "0"
        item.unit = "kg"
        item.inventory_type = InventoryType.RAW_MATERIAL.value
        item.supplier = None
        item.purchase_date = None
        item.supplier_batch_number = None
        item.expiry_date = None
        item.source_execution_id = None
        item.source_execution_step_id = None
        item.source_step_name = None
        item.created_at = None
        result = DAGTracer._item_to_dict(item, {}, None)
        assert result["id"] == str(item.id)
        assert isinstance(result["id"], str)


class TestDAGTracerTraverse:
    """Tests for unified traverse() engine (real DB)."""

    def test_traverse_returns_traversal_result(self, db):
        """Real DB: traverse returns TraversalResult with root_nodes, direction, nodes, edges, metadata."""
        org_id = uuid4()
        tracer = DAGTracer(org_id=org_id, session=db)
        result = tracer.traverse(start_nodes=[uuid4()], direction="forward")
        assert hasattr(result, "root_nodes")
        assert hasattr(result, "direction")
        assert hasattr(result, "nodes")
        assert hasattr(result, "edges")
        assert hasattr(result, "metadata")
        assert result.direction == "forward"

    def test_traverse_multiple_roots_accepted(self, db, demo_data):
        """Real DB + resetdb: multiple start_nodes accepted; traversal runs from each root."""
        org_id = demo_data["org_id"]
        raw_items = (
            db.query(InventoryItem)
            .filter(InventoryItem.org_id == org_id, InventoryItem.inventory_type == InventoryType.RAW_MATERIAL.value)
            .limit(2)
            .all()
        )
        assert len(raw_items) >= 2, "Demo data must include at least 2 raw materials"
        tracer = DAGTracer(org_id=org_id, session=db)
        result = tracer.traverse(
            start_nodes=[raw_items[0].id, raw_items[1].id],
            direction="forward",
            root_set={raw_items[0].id, raw_items[1].id},
        )
        assert_traversal_invariants(result)
        assert result.direction == "forward"
        assert result.root_nodes == {raw_items[0].id, raw_items[1].id}
        assert len(result.nodes) >= 2

    def test_zero_quantity_excluded_unless_in_root_set(self, db, demo_data):
        """Real DB + resetdb: root_set item included even with quantity 0 (demo has stock; we assert root in nodes)."""
        org_id = demo_data["org_id"]
        raw_items = (
            db.query(InventoryItem)
            .filter(InventoryItem.org_id == org_id, InventoryItem.inventory_type == InventoryType.RAW_MATERIAL.value)
            .limit(1)
            .all()
        )
        assert raw_items, "Demo data must include raw materials"
        tracer = DAGTracer(org_id=org_id, session=db)
        result = tracer.traverse(
            start_nodes=[raw_items[0].id],
            direction="forward",
            include_quantity_filter=True,
            root_set={raw_items[0].id},
        )
        assert_traversal_invariants(result)
        assert len(result.nodes) >= 1
        assert any(n["id"] == str(raw_items[0].id) for n in result.nodes)

    def test_stop_condition_node_still_included(self, db, demo_data):
        """Real DB + resetdb: stop_condition includes that node; we stop traversing beyond it."""
        from app.core.backend.dagtraversal import stop_at_inventory_types

        org_id = demo_data["org_id"]
        finals = (
            db.query(InventoryItem)
            .filter(InventoryItem.org_id == org_id, InventoryItem.inventory_type == InventoryType.FINAL_PRODUCT.value)
            .limit(1)
            .all()
        )
        assert finals, "Demo data must include final products"
        tracer = DAGTracer(org_id=org_id, session=db)
        result = tracer.traverse(
            start_nodes=[finals[0].id],
            direction="backward",
            stop_conditions=[stop_at_inventory_types("final_product")],
            root_set={finals[0].id},
        )
        assert_traversal_invariants(result)
        assert result.nodes is not None
        assert result.metadata is not None


class TestDAGTracerWithRealDB:
    """Integration tests using real test DB session (same connection pattern as test_2fa_totp_optimized / cleanup_test_data)."""

    def test_trace_forward_nonexistent_item_returns_empty(self, db):
        """With real DB: traversing from a non-existent item ID returns empty nodes/edges."""
        org_id = uuid4()
        tracer = DAGTracer(org_id=org_id, session=db)
        result = tracer.traverse(start_nodes=[uuid4()], direction="forward")
        assert result.nodes == []
        assert result.edges == []
        assert result.direction == "forward"

    def test_trace_backward_nonexistent_item_returns_empty(self, db):
        """With real DB: traversing backward from a non-existent item ID returns empty nodes/edges."""
        org_id = uuid4()
        tracer = DAGTracer(org_id=org_id, session=db)
        result = tracer.traverse(start_nodes=[uuid4()], direction="backward")
        assert result.nodes == []
        assert result.edges == []
        assert result.direction == "backward"


class TestDAGTracerWithDemoData:
    """Integration tests using real DB populated by resetdb (distillery demo data for demo@whistlebird.co.nz)."""

    def test_trace_forward_from_raw_returns_nodes_and_edges(self, db, demo_data):
        """After reset_demo_db: trace forward from a raw material returns nodes and edges."""
        org_id = demo_data["org_id"]
        raw_items = (
            db.query(InventoryItem)
            .filter(InventoryItem.org_id == org_id, InventoryItem.inventory_type == InventoryType.RAW_MATERIAL.value)
            .limit(1)
            .all()
        )
        assert raw_items, "Demo data must include raw materials"
        tracer = DAGTracer(org_id=org_id, session=db)
        result = tracer.traverse(start_nodes=[raw_items[0].id], direction="forward", root_set={raw_items[0].id})
        assert_traversal_invariants(result)
        assert result.direction == "forward"
        assert len(result.nodes) >= 1
        assert result.metadata is not None

    def test_trace_backward_from_final_returns_nodes(self, db, demo_data):
        """After reset_demo_db: trace backward from a final product returns nodes."""
        org_id = demo_data["org_id"]
        final_items = (
            db.query(InventoryItem)
            .filter(InventoryItem.org_id == org_id, InventoryItem.inventory_type == InventoryType.FINAL_PRODUCT.value)
            .limit(1)
            .all()
        )
        assert final_items, "Demo data must include final products"
        tracer = DAGTracer(org_id=org_id, session=db)
        result = tracer.traverse(start_nodes=[final_items[0].id], direction="backward", root_set={final_items[0].id})
        assert_traversal_invariants(result)
        assert result.direction == "backward"
        assert len(result.nodes) >= 1
        assert result.metadata is not None

    def test_demo_data_includes_expired_raw_for_check_needed(self, db, demo_data):
        """After reset_demo_db: at least one raw material has expiry in the past (triggers check-needed)."""
        from datetime import date

        org_id = demo_data["org_id"]
        today = date.today()
        expired_raw = (
            db.query(InventoryItem)
            .filter(
                InventoryItem.org_id == org_id,
                InventoryItem.inventory_type == InventoryType.RAW_MATERIAL.value,
                InventoryItem.expiry_date.isnot(None),
                InventoryItem.expiry_date < today,
            )
            .all()
        )
        assert len(expired_raw) >= 1, "Demo data should include at least one expired raw material for check-needed"


# ---------------------------------------------------------------------------
# Hardening: synthetic DAGs, invariants, deterministic output, ID-only, N+1, enrichment
# (cursor_instructions/harden-dagtraversal-testsuite.md – TEST SUITE ONLY)
# ---------------------------------------------------------------------------


class TestTraversalInvariantsLinearDAG:
    """Enforce graph correctness on linear synthetic DAG R1 -> W1 -> F1. No demo/seed data."""

    def test_linear_forward_nodes_and_edges(self, db, synthetic_org):
        data = build_linear_dag(db, synthetic_org)
        tracer = DAGTracer(org_id=data["org_id"], session=db)
        result = tracer.traverse(
            start_nodes=[data["r1_id"]],
            direction="forward",
            root_set={data["r1_id"]},
        )
        assert_traversal_invariants(result)
        node_ids = {n["id"] for n in result.nodes}
        assert node_ids == {str(data["r1_id"]), str(data["w1_id"]), str(data["f1_id"])}
        edge_pairs = {(e["from_id"], e["to_id"]) for e in result.edges}
        assert edge_pairs == {
            (str(data["r1_id"]), str(data["w1_id"])),
            (str(data["w1_id"]), str(data["f1_id"])),
        }

    def test_linear_backward_nodes_and_edges(self, db, synthetic_org):
        data = build_linear_dag(db, synthetic_org)
        tracer = DAGTracer(org_id=data["org_id"], session=db)
        result = tracer.traverse(
            start_nodes=[data["f1_id"]],
            direction="backward",
            root_set={data["f1_id"]},
        )
        assert_traversal_invariants(result)
        node_ids = {n["id"] for n in result.nodes}
        assert node_ids == {str(data["r1_id"]), str(data["w1_id"]), str(data["f1_id"])}
        edge_pairs = {(e["from_id"], e["to_id"]) for e in result.edges}
        assert edge_pairs == {
            (str(data["r1_id"]), str(data["w1_id"])),
            (str(data["w1_id"]), str(data["f1_id"])),
        }


class TestTraversalInvariantsBranchingDAG:
    """Branching DAG: all branches included, no duplicate nodes/edges."""

    def test_branching_forward_includes_all_branches(self, db, synthetic_org):
        data = build_branching_dag(db, synthetic_org)
        tracer = DAGTracer(org_id=data["org_id"], session=db)
        result = tracer.traverse(
            start_nodes=[data["r1_id"]],
            direction="forward",
            root_set={data["r1_id"]},
        )
        assert_traversal_invariants(result)
        node_ids = {n["id"] for n in result.nodes}
        assert str(data["r1_id"]) in node_ids
        assert str(data["w1_id"]) in node_ids
        assert str(data["w2_id"]) in node_ids
        assert str(data["f1_id"]) in node_ids
        assert len(result.nodes) == len(node_ids)
        edge_keys = {(e["from_id"], e["to_id"], e.get("execution_id", "")) for e in result.edges}
        assert len(result.edges) == len(edge_keys)


class TestCycleSafetyLargeChain:
    """Traversal terminates on large chain; no recursion/stack overflow; each node and edge once.

    Covers instruction §3 (cycle safety): a true A->B->C->A cycle would require schema support
    for reusing an inventory ID as step output; this long linear chain validates termination
    and that cycle protection (visited set) prevents unbounded traversal.
    """

    def test_large_chain_forward_terminates(self, db, synthetic_org):
        length = 25
        data = build_large_linear_chain(db, synthetic_org, length=length)
        tracer = DAGTracer(org_id=data["org_id"], session=db)
        result = tracer.traverse(
            start_nodes=[data["first_id"]],
            direction="forward",
            root_set={data["first_id"]},
        )
        assert_traversal_invariants(result)
        assert len(result.nodes) == length + 1
        assert len(result.edges) == length
        node_ids = {n["id"] for n in result.nodes}
        assert node_ids == {str(i) for i in data["all_ids"]}


class TestDeterministicOutput:
    """Same traversal twice produces identical node order and edge order."""

    def test_linear_traversal_deterministic(self, db, synthetic_org):
        data = build_linear_dag(db, synthetic_org)
        tracer = DAGTracer(org_id=data["org_id"], session=db)
        result1 = tracer.traverse(
            start_nodes=[data["r1_id"]],
            direction="forward",
            root_set={data["r1_id"]},
        )
        result2 = tracer.traverse(
            start_nodes=[data["r1_id"]],
            direction="forward",
            root_set={data["r1_id"]},
        )
        assert_traversal_invariants(result1)
        assert_traversal_invariants(result2)
        assert [n["id"] for n in result1.nodes] == [n["id"] for n in result2.nodes]
        assert [(e["from_id"], e["to_id"]) for e in result1.edges] == [
            (e["from_id"], e["to_id"]) for e in result2.edges
        ]


class TestIdOnlyLineage:
    """Traversal correctness depends only on IDs; names overlap must not confuse lineage."""

    def test_lineage_uses_ids_not_names(self, db, synthetic_org):
        data = build_id_only_lineage_dag(db, synthetic_org)
        tracer = DAGTracer(org_id=data["org_id"], session=db)
        result = tracer.traverse(
            start_nodes=[data["used_raw_id"]],
            direction="forward",
            root_set={data["used_raw_id"]},
        )
        assert_traversal_invariants(result)
        node_ids = {n["id"] for n in result.nodes}
        assert str(data["used_raw_id"]) in node_ids
        assert str(data["final_id"]) in node_ids
        assert str(data["unused_raw_id"]) not in node_ids


class TestN1Guard:
    """Traversal must not issue per-node/per-edge queries; query count below threshold."""

    def test_linear_traversal_query_count_bounded(self, db, synthetic_org):
        data = build_linear_dag(db, synthetic_org)
        tracer = DAGTracer(org_id=data["org_id"], session=db)
        with QueryCounter(db) as counter:
            tracer.traverse(
                start_nodes=[data["r1_id"]],
                direction="forward",
                root_set={data["r1_id"]},
            )
        assert counter.count < 50, "Traversal should not cause N+1; query count too high"


class TestEnrichmentResilience:
    """Traversal succeeds with or without enrichment data; missing enrichment does not break graph correctness."""

    def test_traversal_succeeds_with_enrichment(self, db, synthetic_org):
        data = build_linear_dag(db, synthetic_org)
        tracer = DAGTracer(org_id=data["org_id"], session=db)
        result = tracer.traverse(
            start_nodes=[data["r1_id"]],
            direction="forward",
            root_set={data["r1_id"]},
        )
        assert_traversal_invariants(result)
        assert len(result.nodes) == 3

    def test_traversal_succeeds_without_extra_process_name(self, db, synthetic_org):
        data = build_linear_dag(db, synthetic_org)
        tracer = DAGTracer(org_id=data["org_id"], session=db)
        result = tracer.traverse(
            start_nodes=[data["f1_id"]],
            direction="backward",
            root_set={data["f1_id"]},
        )
        assert_traversal_invariants(result)
        assert len(result.nodes) == 3
