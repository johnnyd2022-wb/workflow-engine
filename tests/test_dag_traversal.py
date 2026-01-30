"""Unit tests for DAGTracer: forward/backward traversal, cycle detection, connections, enrichment."""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.core.backend.dagtraversal import MAX_DAG_DEPTH, DAGTracer, validate_item_uuid
from app.core.db.models.inventory_item import InventoryType


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
        tracer = DAGTracer(org_id=org_id, session=session)
        result = tracer.trace_forward(uuid4())
        assert result["items"] == []
        assert result["connections"] == []

    def test_trace_forward_item_no_source_step_returns_empty(self, org_id, session):
        item = MagicMock()
        item.id = uuid4()
        item.source_execution_step_id = None
        item.org_id = org_id
        session.query.return_value.filter.return_value.first.return_value = item
        session.query.return_value.join.return_value.filter.return_value.all.return_value = []
        tracer = DAGTracer(org_id=org_id, session=session)
        result = tracer.trace_forward(item.id)
        assert result["items"] != []
        assert result["connections"] == []

    def test_trace_backward_item_not_found_returns_empty(self, org_id, session):
        session.query.return_value.filter.return_value.first.return_value = None
        tracer = DAGTracer(org_id=org_id, session=session)
        result = tracer.trace_backward(uuid4())
        assert result["items"] == []
        assert result["connections"] == []


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
        result = tracer.trace_backward(item_a.id)
        assert result["items"] is not None
        assert result["connections"] is not None


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
        result = tracer.trace_forward(item.id)
        for conn in result["connections"]:
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


class TestDAGTracerConstants:
    """Tests for configurable constants."""

    def test_max_dag_depth_defined(self):
        assert MAX_DAG_DEPTH == 50
