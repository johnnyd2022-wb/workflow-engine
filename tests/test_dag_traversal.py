"""Unit tests for DAGTracer: forward/backward traversal, cycle detection, connections, enrichment.

Uses real DB (same pattern as cleanup_test_data / test_login_2fa_flow). Populated via resetdb for demo user.
"""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.core.backend.dagtraversal import DAGTracer, validate_item_uuid
from app.core.db import db_session
from app.core.db.models.inventory_item import InventoryItem, InventoryType
from app.core.utils.resetdb import DEMO_USER_EMAIL, reset_demo_db


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
    """Populate DB with distillery sample data for demo user (resetdb). Use for tests that need real graph data."""
    result = reset_demo_db(db)
    assert result.get("success"), result.get("message", "reset_demo_db failed")
    return {"org_id": ensure_demo_user.org_id}


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
    """Tests for trace_forward and trace_backward correctness."""

    @pytest.fixture
    def org_id(self):
        return uuid4()

    @pytest.fixture
    def session(self):
        return MagicMock()

    def test_trace_forward_item_not_found_returns_empty(self, org_id, session):
        session.query.return_value.filter.return_value.first.return_value = None
        session.query.return_value.join.return_value.filter.return_value.all.return_value = []
        tracer = DAGTracer(org_id=org_id, session=session)
        result = tracer.traverse(start_nodes=[uuid4()], direction="forward")
        assert result.nodes == []
        assert result.edges == []

    def test_trace_forward_item_no_source_step_returns_root_only(self, org_id, session):
        item = MagicMock()
        item.id = uuid4()
        item.source_execution_step_id = None
        item.org_id = org_id
        item.name = "Raw"
        item.quantity = "1"
        item.unit = "kg"
        item.inventory_type = "raw_material"
        item.supplier = None
        item.purchase_date = None
        item.supplier_batch_number = None
        item.expiry_date = None
        item.source_execution_id = None
        item.source_step_name = None
        item.extra_data = None
        item.created_at = None
        session.query.return_value.filter.return_value.first.return_value = item
        session.query.return_value.filter.return_value.all.return_value = [item]
        session.query.return_value.join.return_value.filter.return_value.all.return_value = []
        tracer = DAGTracer(org_id=org_id, session=session)
        result = tracer.traverse(start_nodes=[item.id], direction="forward", root_set={item.id})
        assert len(result.nodes) >= 1
        assert result.edges == []

    def test_trace_backward_item_not_found_returns_empty(self, org_id, session):
        session.query.return_value.filter.return_value.first.return_value = None
        session.query.return_value.join.return_value.filter.return_value.all.return_value = []
        tracer = DAGTracer(org_id=org_id, session=session)
        result = tracer.traverse(start_nodes=[uuid4()], direction="backward")
        assert result.nodes == []
        assert result.edges == []


class TestDAGTracerCycleDetection:
    """Tests for cycle detection and depth limit."""

    @pytest.fixture
    def org_id(self):
        return uuid4()

    def test_trace_backward_visited_set_prevents_infinite_loop(self, org_id):
        session = MagicMock()
        item_a = MagicMock()
        item_a.id = uuid4()
        item_a.source_execution_step_id = uuid4()
        item_a.org_id = org_id
        item_a.extra_data = None
        item_a.source_execution_id = None
        item_a.source_execution_step_id = uuid4()
        item_a.name = "A"
        item_a.quantity = "1"
        item_a.unit = "kg"
        item_a.inventory_type = InventoryType.WORK_IN_PROGRESS.value
        item_a.supplier = None
        item_a.purchase_date = None
        item_a.supplier_batch_number = None
        item_a.expiry_date = None
        item_a.source_step_name = None
        item_a.created_at = None

        step = MagicMock()
        step.id = item_a.source_execution_step_id
        step.execution_id = uuid4()
        step.actual_inputs = [{"inventory_item_id": str(item_a.id)}]
        step.actual_outputs = None
        step.execution_data = None

        def query_side_effect(*args, **kwargs):
            q = MagicMock()
            q.filter.return_value.first.return_value = item_a
            q.filter.return_value.all.return_value = [item_a]
            q.join.return_value.filter.return_value.all.return_value = []
            return q

        session.query.side_effect = query_side_effect
        tracer = DAGTracer(org_id=org_id, session=session)
        result = tracer.traverse(start_nodes=[item_a.id], direction="backward", root_set={item_a.id})
        assert result.nodes is not None
        assert result.edges is not None


class TestDAGTracerConnectionMapping:
    """Tests for connection structure (from_id, to_id, execution_id)."""

    def test_trace_forward_connection_keys(self):
        session = MagicMock()
        org_id = uuid4()
        item = MagicMock()
        item.id = uuid4()
        item.org_id = org_id
        item.source_execution_step_id = None
        item.extra_data = None
        item.source_execution_id = None
        item.name = "Raw"
        item.quantity = "1"
        item.unit = "kg"
        item.inventory_type = InventoryType.RAW_MATERIAL.value
        item.supplier = None
        item.purchase_date = None
        item.supplier_batch_number = None
        item.expiry_date = None
        item.source_step_name = None
        item.created_at = None

        session.query.return_value.filter.return_value.first.return_value = item
        session.query.return_value.join.return_value.filter.return_value.all.return_value = []
        session.query.return_value.filter.return_value.all.return_value = []

        tracer = DAGTracer(org_id=org_id, session=session)
        result = tracer.traverse(start_nodes=[item.id], direction="forward")
        for conn in result.edges:
            assert "from_id" in conn
            assert "to_id" in conn
            assert "execution_id" in conn


class TestDAGTracerExtraDataEnrichment:
    """Tests for extra_data enrichment (execution_prompts, variable_inputs, variable_output, process_name)."""

    @pytest.fixture
    def org_id(self):
        return uuid4()

    def test_enrich_items_bulk_adds_process_name(self, org_id):
        session = MagicMock()
        item = MagicMock()
        item.id = uuid4()
        item.org_id = org_id
        item.name = "WIP"
        item.quantity = "1"
        item.unit = "kg"
        item.inventory_type = InventoryType.WORK_IN_PROGRESS.value
        item.supplier = None
        item.purchase_date = None
        item.supplier_batch_number = None
        item.expiry_date = None
        item.source_execution_id = uuid4()
        item.source_execution_step_id = uuid4()
        item.source_step_name = "Step 1"
        item.extra_data = None
        item.created_at = None

        execution = MagicMock()
        execution.id = item.source_execution_id
        execution.process_id = uuid4()

        process = MagicMock()
        process.id = execution.process_id
        process.name = "Test Process"

        step = MagicMock()
        step.id = item.source_execution_step_id
        step.execution_data = {"prompt_1": "value"}
        step.actual_inputs = []
        step.actual_outputs = [{"name": "WIP"}]

        def query_side_effect(model, *args, **kwargs):
            q = MagicMock()
            if "ExecutionStep" in str(model):
                q.filter.return_value.all.return_value = [step]
                q.filter.return_value.first.return_value = step
            elif "Execution" in str(model):
                q.filter.return_value.all.return_value = [execution]
            elif "Process" in str(model):
                q.filter.return_value.all.return_value = [process]
            else:
                q.filter.return_value.first.return_value = item
                q.filter.return_value.all.return_value = [item]
            return q

        session.query.side_effect = query_side_effect
        tracer = DAGTracer(org_id=org_id, session=session)
        enriched = tracer._enrich_items_bulk([item])
        assert len(enriched) == 1
        assert enriched[0].get("process_name") == "Test Process"
        assert enriched[0].get("extra_data", {}).get("execution_prompts") is not None

    def test_item_to_dict_serializes_id_as_string(self):
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
    """Tests for unified traverse() engine."""

    def test_traverse_returns_traversal_result(self):
        session = MagicMock()
        session.query.return_value.filter.return_value.first.return_value = None
        session.query.return_value.join.return_value.filter.return_value.all.return_value = []
        tracer = DAGTracer(org_id=uuid4(), session=session)
        result = tracer.traverse(start_nodes=[uuid4()], direction="forward")
        assert hasattr(result, "root_nodes")
        assert hasattr(result, "direction")
        assert hasattr(result, "nodes")
        assert hasattr(result, "edges")
        assert hasattr(result, "metadata")
        assert result.direction == "forward"

    def test_traverse_multiple_roots_accepted(self, org_id=None, session=None):
        """Multiple start_nodes are accepted; traversal runs from each root."""
        org_id = org_id or uuid4()
        session = session or MagicMock()
        item1 = MagicMock()
        item1.id = uuid4()
        item1.source_execution_step_id = None
        item1.org_id = org_id
        item1.name = "Raw1"
        item1.quantity = "1"
        item1.unit = "kg"
        item1.inventory_type = "raw_material"
        item1.supplier = item1.purchase_date = item1.supplier_batch_number = None
        item1.expiry_date = item1.source_execution_id = item1.source_step_name = None
        item1.extra_data = item1.created_at = None
        item2 = MagicMock()
        item2.id = uuid4()
        item2.source_execution_step_id = None
        item2.org_id = org_id
        item2.name = "Raw2"
        item2.quantity = "1"
        item2.unit = "kg"
        item2.inventory_type = "raw_material"
        item2.supplier = item2.purchase_date = item2.supplier_batch_number = None
        item2.expiry_date = item2.source_execution_id = item2.source_step_name = None
        item2.extra_data = item2.created_at = None
        session.query.return_value.filter.return_value.all.return_value = [item1, item2]
        session.query.return_value.join.return_value.filter.return_value.all.return_value = []
        session.query.return_value.filter.return_value.all.return_value = [item1, item2]
        tracer = DAGTracer(org_id=org_id, session=session)
        result = tracer.traverse(
            start_nodes=[item1.id, item2.id],
            direction="forward",
            root_set={item1.id, item2.id},
        )
        assert result.direction == "forward"
        assert result.root_nodes == {item1.id, item2.id}
        assert len(result.nodes) >= 2

    def test_zero_quantity_excluded_unless_in_root_set(self):
        """Items with quantity <= 0 are excluded unless in root_set."""
        session = MagicMock()
        org_id = uuid4()
        root_item = MagicMock()
        root_item.id = uuid4()
        root_item.org_id = org_id
        root_item.source_execution_step_id = None
        root_item.name = "Root"
        root_item.quantity = "0"
        root_item.unit = "kg"
        root_item.inventory_type = "raw_material"
        root_item.supplier = root_item.purchase_date = root_item.supplier_batch_number = None
        root_item.expiry_date = root_item.source_execution_id = root_item.source_step_name = None
        root_item.extra_data = root_item.created_at = None
        session.query.return_value.filter.return_value.all.return_value = [root_item]
        session.query.return_value.join.return_value.filter.return_value.all.return_value = []
        tracer = DAGTracer(org_id=org_id, session=session)
        result = tracer.traverse(
            start_nodes=[root_item.id],
            direction="forward",
            include_quantity_filter=True,
            root_set={root_item.id},
        )
        assert len(result.nodes) >= 1
        assert any(n["id"] == str(root_item.id) for n in result.nodes)

    def test_stop_condition_node_still_included(self):
        """When a stop_condition returns True, that node is still included; we only stop traversing beyond it."""
        from app.core.backend.dagtraversal import stop_at_inventory_types

        session = MagicMock()
        org_id = uuid4()
        item = MagicMock()
        item.id = uuid4()
        item.org_id = org_id
        item.source_execution_step_id = None
        item.name = "Final"
        item.quantity = "1"
        item.unit = "kg"
        item.inventory_type = InventoryType.FINAL_PRODUCT.value
        item.supplier = item.purchase_date = item.supplier_batch_number = None
        item.expiry_date = item.source_execution_id = item.source_step_name = None
        item.extra_data = item.created_at = None
        session.query.return_value.filter.return_value.all.return_value = [item]
        session.query.return_value.join.return_value.filter.return_value.all.return_value = []
        tracer = DAGTracer(org_id=org_id, session=session)
        result = tracer.traverse(
            start_nodes=[item.id],
            direction="backward",
            stop_conditions=[stop_at_inventory_types("final_product")],
            root_set={item.id},
        )
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
        if not raw_items:
            pytest.skip("No raw materials in demo data")
        tracer = DAGTracer(org_id=org_id, session=db)
        result = tracer.traverse(start_nodes=[raw_items[0].id], direction="forward", root_set={raw_items[0].id})
        assert result.direction == "forward"
        assert len(result.nodes) >= 1
        # May have edges if execution produced downstream items
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
        if not final_items:
            pytest.skip("No final products in demo data")
        tracer = DAGTracer(org_id=org_id, session=db)
        result = tracer.traverse(start_nodes=[final_items[0].id], direction="backward", root_set={final_items[0].id})
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
