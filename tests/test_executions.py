"""
Tests for execution lifecycle: create execution, get execution with steps,
complete step with actual_inputs/actual_outputs (execution modal contract), step order, and regressions.

Scope: ExecutionRepository, execution/execution_step models, and the API contract
(actual_inputs/actual_outputs shape) used by flows2 execution modal. Serves as a deployment gate.
"""

import math
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.core.db import db_session
from app.core.db.models.execution import ExecutionStatus
from app.core.db.models.execution_step import ExecutionStepStatus
from app.core.db.models.organisation import Organisation
from app.core.db.models.process import Process
from app.core.db.models.step import Step
from app.core.db.repositories.execution_repo import ExecutionRepository
from app.core.db.repositories.organisation_repo import OrganisationRepository
from app.core.db.repositories.process_repo import ProcessRepository
from app.core.utils.resetdb import DEMO_USER_EMAIL, clear_demo_db, reset_demo_db


@pytest.fixture
def db():
    """Real database session for integration tests (same pattern as test_corechecks / test_dag_traversal)."""
    session = db_session()
    try:
        yield session
    finally:
        session.close()
        db_session.remove()


@pytest.fixture
def ensure_demo_user(db):
    """Ensure demo user exists. Used by demo_data."""
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
    """Populate DB with distillery sample data; cleared at teardown."""
    result = reset_demo_db(db)
    assert result.get("success"), result.get("message", "reset_demo_db failed")
    try:
        yield {"org_id": ensure_demo_user.org_id}
    finally:
        clear_demo_db(db)


def _clear_synthetic_executions(db, org_id, process_id):
    """Remove executions and execution_steps for a process (keeps process/steps)."""
    exec_repo = ExecutionRepository(db)
    executions = exec_repo.list_executions(org_id=org_id, process_id=process_id)
    for e in executions:
        for es in e.execution_steps:
            db.delete(es)
        db.delete(e)
    db.commit()


def _teardown_synthetic_org_process(db, org_id, process_id):
    """Shared teardown: clear executions, delete steps, process, org.

    org_id and process_id are plain UUIDs so this still works even if the original
    ORM instances have been detached from the session (e.g. in tests that call
    db_session.remove() or close the session explicitly).
    """
    _clear_synthetic_executions(db, org_id, process_id)
    db.query(Step).filter(Step.process_id == process_id).delete(synchronize_session=False)
    db.query(Process).filter(Process.id == process_id).delete(synchronize_session=False)
    db.query(Organisation).filter(Organisation.id == org_id).delete(synchronize_session=False)
    db.commit()


def _create_linear_process_n_steps(db, org_name, process_name, n_steps):
    """
    Create org + process with n_steps in a linear chain: Input A -> Out1 -> ... -> Out(n-1) -> Final.
    Returns (org, process). Caller must teardown via _clear_synthetic_executions and delete Steps, Process, Org.
    """
    org_repo = OrganisationRepository(db)
    process_repo = ProcessRepository(db)
    # Use a unique org name to avoid collisions with existing data in the test database
    org = org_repo.create_org(f"{org_name} {uuid4()}")
    process = process_repo.create_process(
        org_id=org.id,
        name=process_name,
        description=f"Linear {n_steps}-step process",
        is_draft=False,
    )
    for i in range(1, n_steps + 1):
        prev_name = "Input A" if i == 1 else f"Out{i - 1}"
        out_name = f"Out{i}" if i < n_steps else "Final"
        process_repo.add_step(
            process_id=process.id,
            org_id=org.id,
            step_number=i,
            name=f"Step {i}",
            inputs=[{"name": prev_name, "quantity": 10 - i, "unit": "kg"}],
            outputs=[{"name": out_name, "quantity": 9 - i, "unit": "kg"}],
        )
    return org, process


def _synthetic_org_process_yield(db, org, process, num_steps=None):
    """Shared yield + teardown for all synthetic org/process fixtures."""
    data = {"org_id": org.id, "process_id": process.id}
    if num_steps is not None:
        data["num_steps"] = num_steps
    try:
        yield data
    finally:
        _teardown_synthetic_org_process(db, data["org_id"], data["process_id"])


@pytest.fixture
def synthetic_org_and_process_clean(db):
    """Minimal org + process with 2 steps (linear chain). Cleared at teardown."""
    org, process = _create_linear_process_n_steps(db, "Execution Test Org Clean", "Two Step Process", 2)
    yield from _synthetic_org_process_yield(db, org, process)


@pytest.fixture
def synthetic_org_process_three_steps(db):
    """Org + process with 3 steps (linear chain). Cleared at teardown."""
    org, process = _create_linear_process_n_steps(db, "Execution Test Org Three Steps", "Three Step Process", 3)
    yield from _synthetic_org_process_yield(db, org, process)


@pytest.fixture
def synthetic_org_process_five_steps(db):
    """Org + process with 5 steps (linear chain). Cleared at teardown."""
    org, process = _create_linear_process_n_steps(db, "Execution Test Org Five Steps", "Five Step Process", 5)
    yield from _synthetic_org_process_yield(db, org, process)


@pytest.fixture
def synthetic_org_process_ten_steps(db):
    """Org + process with 10 steps (linear chain). Cleared at teardown."""
    org, process = _create_linear_process_n_steps(db, "Execution Test Org Ten Steps", "Ten Step Process", 10)
    yield from _synthetic_org_process_yield(db, org, process)


@pytest.fixture
def synthetic_org_process_n_steps(db, request):
    """Parametrized: org + process with request.param steps (use with @pytest.mark.parametrize(..., indirect=True))."""
    n = request.param
    org, process = _create_linear_process_n_steps(db, f"Execution Test Org {n} Steps", f"{n} Step Process", n)
    yield from _synthetic_org_process_yield(db, org, process, num_steps=n)


# Allowed keys and types for actual_inputs/actual_outputs (execution modal contract)
ALLOWED_INPUT_KEYS = {"name", "quantity", "unit", "inventory_item_id"}
ALLOWED_OUTPUT_KEYS = {"name", "quantity", "unit", "inventory_item_id"}

# Error message patterns (match repo raises) – standardize so tests survive wording tweaks
RE_PRIOR_STEPS_NOT_COMPLETED = r"prior steps.*are not completed"
RE_NOT_IN_STATE_TO_COMPLETE = r"not in a state that can be completed"
RE_PROCESS_NOT_FOUND = r"not found or does not belong"

# Standard: use None when no inventory selection; str(uuid4()) when testing linkage
INVENTORY_ITEM_ID_NONE = None


def _assert_quantity_numeric(value, msg="quantity"):
    """Assert quantity is int or float (consistent numeric type)."""
    assert isinstance(value, (int, float)), f"{msg} must be int or float, got {type(value)}"


def _assert_quantity_positive(value, msg="quantity"):
    """Assert quantity > 0 where business logic forbids zero/negative."""
    _assert_quantity_numeric(value, msg)
    assert value > 0, f"{msg} must be positive, got {value}"


def _assert_quantity_close(actual, expected, rel_tol=1e-6, abs_tol=1e-9):
    """Assert two quantities are close (avoids floating-point precision failures). Zero handled via abs_tol."""
    _assert_quantity_numeric(actual)
    _assert_quantity_numeric(expected)
    assert math.isclose(actual, expected, rel_tol=rel_tol, abs_tol=abs_tol), f"expected {expected} ≈ {actual}"


# ---------------------------------------------------------------------------
# Create execution
# ---------------------------------------------------------------------------


class TestCreateExecution:
    """Create execution: steps created, first step READY, execution IN_PROGRESS."""

    def test_create_execution_creates_steps_and_sets_first_ready(self, db, synthetic_org_and_process_clean):
        org_id = synthetic_org_and_process_clean["org_id"]
        process_id = synthetic_org_and_process_clean["process_id"]
        repo = ExecutionRepository(db)
        execution = repo.create_execution(org_id=org_id, process_id=process_id)
        assert execution is not None
        assert execution.org_id == org_id
        assert execution.process_id == process_id
        assert execution.status == ExecutionStatus.IN_PROGRESS
        assert execution.total_steps == 2
        steps = sorted(execution.execution_steps, key=lambda s: s.step_number)
        assert len(steps) == 2
        assert steps[0].status == ExecutionStepStatus.READY
        assert steps[1].status == ExecutionStepStatus.PENDING

    def test_create_execution_invalid_process_raises(self, db, synthetic_org_and_process_clean):
        org_id = synthetic_org_and_process_clean["org_id"]
        repo = ExecutionRepository(db)
        with pytest.raises(ValueError, match=RE_PROCESS_NOT_FOUND):
            repo.create_execution(org_id=org_id, process_id=uuid4())


# ---------------------------------------------------------------------------
# Get execution
# ---------------------------------------------------------------------------


class TestGetExecution:
    """Get execution with steps: shape, actual_inputs/actual_outputs present (empty until completed)."""

    def test_get_execution_with_steps_returns_steps_with_actual_io(self, db, demo_data):
        org_id = demo_data["org_id"]
        repo = ExecutionRepository(db)
        executions = repo.list_executions(org_id=org_id)
        assert len(executions) >= 1
        execution = repo.get_execution_with_steps(executions[0].id, org_id)
        assert execution is not None
        assert hasattr(execution, "execution_steps")
        for es in execution.execution_steps:
            assert hasattr(es, "actual_inputs")
            assert hasattr(es, "actual_outputs")
            assert es.actual_inputs is None or isinstance(es.actual_inputs, list)
            assert es.actual_outputs is None or isinstance(es.actual_outputs, list)
            assert es.step is not None
            assert es.step.inputs is not None or es.step.outputs is not None

    def test_get_execution_wrong_org_returns_none(self, db, demo_data, synthetic_org_and_process_clean):
        org_id = demo_data["org_id"]
        other_org_id = synthetic_org_and_process_clean["org_id"]
        repo = ExecutionRepository(db)
        executions = repo.list_executions(org_id=org_id)
        assert len(executions) >= 1
        execution_id = executions[0].id
        result = repo.get_execution_with_steps(execution_id, other_org_id)
        assert result is None

    def test_get_execution_nonexistent_id_returns_none(self, db, synthetic_org_and_process_clean):
        org_id = synthetic_org_and_process_clean["org_id"]
        repo = ExecutionRepository(db)
        result = repo.get_execution_with_steps(uuid4(), org_id)
        assert result is None


# ---------------------------------------------------------------------------
# Complete step: contract and persistence
# ---------------------------------------------------------------------------


class TestCompleteStepContract:
    """Complete step stores actual_inputs/actual_outputs (execution modal contract)."""

    def test_complete_step_stores_actual_inputs_and_outputs(self, db, synthetic_org_and_process_clean):
        org_id = synthetic_org_and_process_clean["org_id"]
        process_id = synthetic_org_and_process_clean["process_id"]
        repo = ExecutionRepository(db)
        execution = repo.create_execution(org_id=org_id, process_id=process_id)
        steps = sorted(execution.execution_steps, key=lambda s: s.step_number)
        step1 = steps[0]
        actual_inputs = [
            {"name": "Input A", "quantity": 5, "unit": "kg", "inventory_item_id": str(uuid4())},
        ]
        actual_outputs = [{"name": "Out1", "quantity": 4, "unit": "kg"}]
        execution_data = {"completed_by": "test@example.com"}
        completed = repo.complete_step(
            execution_step_id=step1.id,
            org_id=org_id,
            actual_inputs=actual_inputs,
            actual_outputs=actual_outputs,
            execution_data=execution_data,
        )
        assert completed is not None
        assert completed.actual_inputs == actual_inputs
        assert completed.actual_outputs == actual_outputs
        assert completed.execution_data.get("completed_by") == "test@example.com"
        loaded = repo.get_execution_with_steps(execution.id, org_id)
        step1_loaded = next(es for es in loaded.execution_steps if es.step_number == 1)
        assert step1_loaded.actual_inputs == actual_inputs
        assert step1_loaded.actual_outputs == actual_outputs
        _assert_quantity_numeric(step1_loaded.actual_inputs[0]["quantity"])
        _assert_quantity_numeric(step1_loaded.actual_outputs[0]["quantity"])

    def test_complete_step_accepts_empty_actual_inputs_outputs(self, db, synthetic_org_and_process_clean):
        org_id = synthetic_org_and_process_clean["org_id"]
        process_id = synthetic_org_and_process_clean["process_id"]
        repo = ExecutionRepository(db)
        execution = repo.create_execution(org_id=org_id, process_id=process_id)
        steps = sorted(execution.execution_steps, key=lambda s: s.step_number)
        completed = repo.complete_step(
            execution_step_id=steps[0].id,
            org_id=org_id,
            actual_inputs=[],
            actual_outputs=[],
            execution_data={},
        )
        assert completed is not None
        assert completed.actual_inputs == []
        assert completed.actual_outputs == []


# ---------------------------------------------------------------------------
# Step order and advancement
# ---------------------------------------------------------------------------


class TestCompleteStepOrder:
    """Step order: cannot complete step N before step N-1; completing step 1 advances step 2 to READY."""

    def test_cannot_complete_step_2_before_step_1(self, db, synthetic_org_and_process_clean):
        org_id = synthetic_org_and_process_clean["org_id"]
        process_id = synthetic_org_and_process_clean["process_id"]
        repo = ExecutionRepository(db)
        execution = repo.create_execution(org_id=org_id, process_id=process_id)
        steps = sorted(execution.execution_steps, key=lambda s: s.step_number)
        step2 = steps[1]
        # Completing step 2 before step 1 should raise a prior-steps-not-completed error.
        with pytest.raises(ValueError, match=RE_PRIOR_STEPS_NOT_COMPLETED):
            repo.complete_step(
                execution_step_id=step2.id,
                org_id=org_id,
                actual_inputs=[],
                actual_outputs=[],
            )

    def test_completing_step_1_marks_step_2_ready(self, db, synthetic_org_and_process_clean):
        org_id = synthetic_org_and_process_clean["org_id"]
        process_id = synthetic_org_and_process_clean["process_id"]
        repo = ExecutionRepository(db)
        execution = repo.create_execution(org_id=org_id, process_id=process_id)
        steps = sorted(execution.execution_steps, key=lambda s: s.step_number)
        repo.complete_step(
            execution_step_id=steps[0].id,
            org_id=org_id,
            actual_inputs=[{"name": "Input A", "quantity": 9, "unit": "kg"}],
            actual_outputs=[{"name": "Out1", "quantity": 8, "unit": "kg"}],
        )
        loaded = repo.get_execution_with_steps(execution.id, org_id)
        step2 = next(es for es in loaded.execution_steps if es.step_number == 2)
        assert step2.status == ExecutionStepStatus.READY

    def test_completing_all_steps_marks_execution_completed(self, db, synthetic_org_and_process_clean):
        org_id = synthetic_org_and_process_clean["org_id"]
        process_id = synthetic_org_and_process_clean["process_id"]
        repo = ExecutionRepository(db)
        execution = repo.create_execution(org_id=org_id, process_id=process_id)
        steps = sorted(execution.execution_steps, key=lambda s: s.step_number)
        repo.complete_step(
            execution_step_id=steps[0].id,
            org_id=org_id,
            actual_inputs=[{"name": "Input A", "quantity": 9, "unit": "kg"}],
            actual_outputs=[{"name": "Out1", "quantity": 8, "unit": "kg"}],
        )
        repo.complete_step(
            execution_step_id=steps[1].id,
            org_id=org_id,
            actual_inputs=[{"name": "Out1", "quantity": 8, "unit": "kg"}],
            actual_outputs=[{"name": "Final", "quantity": 7, "unit": "kg"}],
        )
        loaded = repo.get_execution_by_id(execution.id, org_id)
        assert loaded.status == ExecutionStatus.COMPLETED
        assert loaded.completed_at is not None


# ---------------------------------------------------------------------------
# Multi-step (3+ steps)
# ---------------------------------------------------------------------------


class TestMultiStepProcess:
    """Multi-step process: complete 1 → 2 READY, complete 2 → 3 READY, complete 3 → execution COMPLETED."""

    def test_three_step_advancement_and_persistence(self, db, synthetic_org_process_three_steps):
        org_id = synthetic_org_process_three_steps["org_id"]
        process_id = synthetic_org_process_three_steps["process_id"]
        repo = ExecutionRepository(db)
        execution = repo.create_execution(org_id=org_id, process_id=process_id)
        steps = sorted(execution.execution_steps, key=lambda s: s.step_number)
        assert len(steps) == 3
        # Complete Step 1 → Step 2 should move to READY
        repo.complete_step(
            execution_step_id=steps[0].id,
            org_id=org_id,
            actual_inputs=[{"name": "Input A", "quantity": 9, "unit": "kg"}],
            actual_outputs=[{"name": "Out1", "quantity": 8, "unit": "kg"}],
        )
        loaded = repo.get_execution_with_steps(execution.id, org_id)
        step2 = next(es for es in loaded.execution_steps if es.step_number == 2)
        assert step2.status == ExecutionStepStatus.READY
        # Complete Step 2 → Step 3 should move to READY
        repo.complete_step(
            execution_step_id=steps[1].id,
            org_id=org_id,
            actual_inputs=[{"name": "Out1", "quantity": 8, "unit": "kg"}],
            actual_outputs=[{"name": "Out2", "quantity": 7, "unit": "kg"}],
        )
        loaded = repo.get_execution_with_steps(execution.id, org_id)
        step3 = next(es for es in loaded.execution_steps if es.step_number == 3)
        assert step3.status == ExecutionStepStatus.READY
        # Complete Step 3 → Execution should be COMPLETED
        repo.complete_step(
            execution_step_id=steps[2].id,
            org_id=org_id,
            actual_inputs=[{"name": "Out2", "quantity": 7, "unit": "kg"}],
            actual_outputs=[{"name": "Final", "quantity": 6, "unit": "kg"}],
        )
        loaded = repo.get_execution_by_id(execution.id, org_id)
        assert loaded.status == ExecutionStatus.COMPLETED
        # Verify actual_inputs and actual_outputs persist for all steps
        full = repo.get_execution_with_steps(execution.id, org_id)
        for es in full.execution_steps:
            assert es.actual_inputs is not None and len(es.actual_inputs) >= 0
            assert es.actual_outputs is not None and len(es.actual_outputs) >= 1
            for out in es.actual_outputs:
                _assert_quantity_numeric(out["quantity"])

    def test_five_step_advancement_and_persistence(self, db, synthetic_org_process_five_steps):
        """5-step process: complete 1..5 in order; all steps persist actual_inputs/actual_outputs; execution COMPLETED."""
        org_id = synthetic_org_process_five_steps["org_id"]
        process_id = synthetic_org_process_five_steps["process_id"]
        repo = ExecutionRepository(db)
        execution = repo.create_execution(org_id=org_id, process_id=process_id)
        steps = sorted(execution.execution_steps, key=lambda s: s.step_number)
        assert len(steps) == 5
        prev_output_name = "Input A"
        for i, step in enumerate(steps):
            out_name = "Out" + str(i + 1) if i < 4 else "Final"
            qty_in = 10 - (i + 1)
            qty_out = 9 - (i + 1)
            repo.complete_step(
                execution_step_id=step.id,
                org_id=org_id,
                actual_inputs=[{"name": prev_output_name, "quantity": qty_in, "unit": "kg", "inventory_item_id": None}],
                actual_outputs=[{"name": out_name, "quantity": qty_out, "unit": "kg", "inventory_item_id": None}],
            )
            prev_output_name = out_name
        loaded = repo.get_execution_by_id(execution.id, org_id)
        assert loaded.status == ExecutionStatus.COMPLETED
        full = repo.get_execution_with_steps(execution.id, org_id)
        for es in full.execution_steps:
            assert es.actual_inputs is not None
            assert es.actual_outputs is not None and len(es.actual_outputs) >= 1
            for out in es.actual_outputs:
                _assert_quantity_numeric(out["quantity"])

    def test_five_step_after_completing_one_only_next_ready_rest_pending(self, db, synthetic_org_process_five_steps):
        """After completing step 1 only, step 2 is READY and steps 3, 4, 5 remain PENDING."""
        org_id = synthetic_org_process_five_steps["org_id"]
        process_id = synthetic_org_process_five_steps["process_id"]
        repo = ExecutionRepository(db)
        execution = repo.create_execution(org_id=org_id, process_id=process_id)
        steps = sorted(execution.execution_steps, key=lambda s: s.step_number)
        repo.complete_step(
            execution_step_id=steps[0].id,
            org_id=org_id,
            actual_inputs=[{"name": "Input A", "quantity": 9, "unit": "kg", "inventory_item_id": None}],
            actual_outputs=[{"name": "Out1", "quantity": 8, "unit": "kg", "inventory_item_id": None}],
        )
        loaded = repo.get_execution_with_steps(execution.id, org_id)
        step2 = next(es for es in loaded.execution_steps if es.step_number == 2)
        step3 = next(es for es in loaded.execution_steps if es.step_number == 3)
        step4 = next(es for es in loaded.execution_steps if es.step_number == 4)
        step5 = next(es for es in loaded.execution_steps if es.step_number == 5)
        assert step2.status == ExecutionStepStatus.READY
        assert step3.status == ExecutionStepStatus.PENDING
        assert step4.status == ExecutionStepStatus.PENDING
        assert step5.status == ExecutionStepStatus.PENDING

    def test_ten_step_advancement_and_completed(self, db, synthetic_org_process_ten_steps):
        """10-step stress: complete all steps in order; execution COMPLETED; all steps persist actual_inputs/outputs."""
        org_id = synthetic_org_process_ten_steps["org_id"]
        process_id = synthetic_org_process_ten_steps["process_id"]
        repo = ExecutionRepository(db)
        execution = repo.create_execution(org_id=org_id, process_id=process_id)
        steps = sorted(execution.execution_steps, key=lambda s: s.step_number)
        assert len(steps) == 10
        prev_output_name = "Input A"
        for i, step in enumerate(steps):
            out_name = f"Out{i + 1}" if i < 9 else "Final"
            qty_in = 10 - (i + 1)
            qty_out = 9 - (i + 1)
            repo.complete_step(
                execution_step_id=step.id,
                org_id=org_id,
                actual_inputs=[
                    {
                        "name": prev_output_name,
                        "quantity": qty_in,
                        "unit": "kg",
                        "inventory_item_id": INVENTORY_ITEM_ID_NONE,
                    }
                ],
                actual_outputs=[
                    {"name": out_name, "quantity": qty_out, "unit": "kg", "inventory_item_id": INVENTORY_ITEM_ID_NONE}
                ],
            )
            prev_output_name = out_name
        loaded = repo.get_execution_by_id(execution.id, org_id)
        assert loaded.status == ExecutionStatus.COMPLETED
        full = repo.get_execution_with_steps(execution.id, org_id)
        for es in full.execution_steps:
            assert es.actual_inputs is not None and len(es.actual_inputs) >= 1
            assert es.actual_outputs is not None and len(es.actual_outputs) >= 1

    @pytest.mark.parametrize("synthetic_org_process_n_steps", [2, 3, 5, 10], indirect=True)
    def test_complete_all_steps_execution_completed(self, db, synthetic_org_process_n_steps):
        """Parametrized: complete all N steps in order -> execution COMPLETED; all steps persist actual_inputs/outputs."""
        org_id = synthetic_org_process_n_steps["org_id"]
        process_id = synthetic_org_process_n_steps["process_id"]
        n = synthetic_org_process_n_steps["num_steps"]
        repo = ExecutionRepository(db)
        execution = repo.create_execution(org_id=org_id, process_id=process_id)
        steps = sorted(execution.execution_steps, key=lambda s: s.step_number)
        assert len(steps) == n
        prev_output_name = "Input A"
        for i, step in enumerate(steps):
            out_name = f"Out{i + 1}" if i < n - 1 else "Final"
            qty_in = 10 - (i + 1)
            qty_out = 9 - (i + 1)
            repo.complete_step(
                execution_step_id=step.id,
                org_id=org_id,
                actual_inputs=[
                    {
                        "name": prev_output_name,
                        "quantity": qty_in,
                        "unit": "kg",
                        "inventory_item_id": INVENTORY_ITEM_ID_NONE,
                    }
                ],
                actual_outputs=[
                    {"name": out_name, "quantity": qty_out, "unit": "kg", "inventory_item_id": INVENTORY_ITEM_ID_NONE}
                ],
            )
            prev_output_name = out_name
        loaded = repo.get_execution_by_id(execution.id, org_id)
        assert loaded.status == ExecutionStatus.COMPLETED
        full = repo.get_execution_with_steps(execution.id, org_id)
        for es in full.execution_steps:
            assert es.actual_inputs is not None
            assert es.actual_outputs is not None and len(es.actual_outputs) >= 1
            for out in es.actual_outputs:
                _assert_quantity_numeric(out["quantity"])


# ---------------------------------------------------------------------------
# Step failure / invalid step handling
# ---------------------------------------------------------------------------


class TestStepFailureHandling:
    """Step failure: failed complete does not advance execution; state remains consistent."""

    def test_complete_step_failure_does_not_advance_execution(self, db, synthetic_org_process_three_steps):
        org_id = synthetic_org_process_three_steps["org_id"]
        process_id = synthetic_org_process_three_steps["process_id"]
        repo = ExecutionRepository(db)
        execution = repo.create_execution(org_id=org_id, process_id=process_id)
        steps = sorted(execution.execution_steps, key=lambda s: s.step_number)
        # Attempt to complete step 3 before step 1 and 2 (controlled exception)
        # This should raise a prior-steps-not-completed error.
        with pytest.raises(ValueError, match=RE_PRIOR_STEPS_NOT_COMPLETED):
            repo.complete_step(
                execution_step_id=steps[2].id,
                org_id=org_id,
                actual_inputs=[],
                actual_outputs=[],
            )
        # Assert execution remains IN_PROGRESS, step 2 and 3 still PENDING, step 1 still READY
        loaded = repo.get_execution_with_steps(execution.id, org_id)
        assert loaded.status == ExecutionStatus.IN_PROGRESS
        step1 = next(es for es in loaded.execution_steps if es.step_number == 1)
        step2 = next(es for es in loaded.execution_steps if es.step_number == 2)
        step3 = next(es for es in loaded.execution_steps if es.step_number == 3)
        assert step1.status == ExecutionStepStatus.READY
        assert step2.status == ExecutionStepStatus.PENDING
        assert step3.status == ExecutionStepStatus.PENDING

    def test_complete_step_raises_no_partial_commit(self, db, synthetic_org_process_three_steps):
        """When complete_step raises (e.g. wrong order), execution state is unchanged (rollback)."""
        org_id = synthetic_org_process_three_steps["org_id"]
        process_id = synthetic_org_process_three_steps["process_id"]
        repo = ExecutionRepository(db)
        execution = repo.create_execution(org_id=org_id, process_id=process_id)
        steps = sorted(execution.execution_steps, key=lambda s: s.step_number)
        # Out-of-order completion should raise a prior-steps-not-completed error.
        with pytest.raises(ValueError, match=RE_PRIOR_STEPS_NOT_COMPLETED):
            repo.complete_step(
                execution_step_id=steps[2].id,
                org_id=org_id,
                actual_inputs=[{"name": "Out2", "quantity": 7, "unit": "kg"}],
                actual_outputs=[{"name": "Final", "quantity": 6, "unit": "kg"}],
            )
        loaded = repo.get_execution_with_steps(execution.id, org_id)
        step1 = next(es for es in loaded.execution_steps if es.step_number == 1)
        step2 = next(es for es in loaded.execution_steps if es.step_number == 2)
        step3 = next(es for es in loaded.execution_steps if es.step_number == 3)
        assert step1.status == ExecutionStepStatus.READY
        assert step2.status == ExecutionStepStatus.PENDING
        assert step3.status == ExecutionStepStatus.PENDING
        assert loaded.status == ExecutionStatus.IN_PROGRESS


# ---------------------------------------------------------------------------
# Step order and output/input consistency
# ---------------------------------------------------------------------------


class TestStepOrderAndInputOutputConsistency:
    """Step N+1 completion with inputs matching step N outputs; unit consistency with step definition."""

    def test_step_n_plus_1_accepts_inputs_matching_step_n_outputs(self, db, synthetic_org_process_three_steps):
        """Completing step N+1 with actual_inputs matching step N actual_outputs (names and units) succeeds."""
        org_id = synthetic_org_process_three_steps["org_id"]
        process_id = synthetic_org_process_three_steps["process_id"]
        repo = ExecutionRepository(db)
        execution = repo.create_execution(org_id=org_id, process_id=process_id)
        steps = sorted(execution.execution_steps, key=lambda s: s.step_number)
        step1_outputs = [{"name": "Out1", "quantity": 8, "unit": "kg", "inventory_item_id": None}]
        repo.complete_step(
            execution_step_id=steps[0].id,
            org_id=org_id,
            actual_inputs=[{"name": "Input A", "quantity": 9, "unit": "kg", "inventory_item_id": str(uuid4())}],
            actual_outputs=step1_outputs,
        )
        loaded = repo.get_execution_with_steps(execution.id, org_id)
        step2 = next(es for es in loaded.execution_steps if es.step_number == 2)
        # Step 2 input matches step 1 output (name and unit from step definition)
        step_def = step2.step
        def_unit = step_def.inputs[0]["unit"] if step_def.inputs else "kg"
        repo.complete_step(
            execution_step_id=steps[1].id,
            org_id=org_id,
            actual_inputs=[{"name": "Out1", "quantity": 8, "unit": def_unit, "inventory_item_id": None}],
            actual_outputs=[{"name": "Out2", "quantity": 7, "unit": "kg", "inventory_item_id": None}],
        )
        loaded2 = repo.get_execution_with_steps(execution.id, org_id)
        step1_loaded = next(es for es in loaded2.execution_steps if es.step_number == 1)
        step2_loaded = next(es for es in loaded2.execution_steps if es.step_number == 2)
        assert step2_loaded.actual_inputs[0]["name"] == step1_loaded.actual_outputs[0]["name"]
        _assert_quantity_close(step2_loaded.actual_inputs[0]["quantity"], step1_loaded.actual_outputs[0]["quantity"])
        assert step2_loaded.actual_inputs[0]["unit"] == step1_loaded.actual_outputs[0]["unit"]

    def test_partial_execution_reload_and_resume(self, db, synthetic_org_process_three_steps):
        """Partial execution: complete step 1 only, reload execution, then complete step 2 (resume)."""
        org_id = synthetic_org_process_three_steps["org_id"]
        process_id = synthetic_org_process_three_steps["process_id"]
        repo = ExecutionRepository(db)
        execution = repo.create_execution(org_id=org_id, process_id=process_id)
        execution_id = execution.id
        steps = sorted(execution.execution_steps, key=lambda s: s.step_number)
        repo.complete_step(
            execution_step_id=steps[0].id,
            org_id=org_id,
            actual_inputs=[{"name": "Input A", "quantity": 9, "unit": "kg", "inventory_item_id": None}],
            actual_outputs=[{"name": "Out1", "quantity": 8, "unit": "kg", "inventory_item_id": None}],
        )
        loaded = repo.get_execution_with_steps(execution_id, org_id)
        assert loaded.status == ExecutionStatus.IN_PROGRESS
        step2 = next(es for es in loaded.execution_steps if es.step_number == 2)
        assert step2.status == ExecutionStepStatus.READY
        repo.complete_step(
            execution_step_id=step2.id,
            org_id=org_id,
            actual_inputs=[{"name": "Out1", "quantity": 8, "unit": "kg", "inventory_item_id": None}],
            actual_outputs=[{"name": "Out2", "quantity": 7, "unit": "kg", "inventory_item_id": None}],
        )
        loaded2 = repo.get_execution_with_steps(execution_id, org_id)
        assert loaded2.status == ExecutionStatus.IN_PROGRESS
        step2_done = next(es for es in loaded2.execution_steps if es.step_number == 2)
        assert step2_done.status == ExecutionStepStatus.COMPLETED


# ---------------------------------------------------------------------------
# Database transaction isolation
# ---------------------------------------------------------------------------


class TestDatabaseTransactionIsolation:
    """Separate sessions: create in one, complete in another, verify no stale data."""

    def test_complete_step_in_separate_session_visible_on_reload(self, db, synthetic_org_and_process_clean):
        """Create execution in session 1; complete step in session 2; reload in session 3 sees updated data."""
        org_id = synthetic_org_and_process_clean["org_id"]
        process_id = synthetic_org_and_process_clean["process_id"]
        repo1 = ExecutionRepository(db)
        execution = repo1.create_execution(org_id=org_id, process_id=process_id)
        execution_id = execution.id
        step1_id = next(es.id for es in execution.execution_steps if es.step_number == 1)
        db.commit()
        db_session.remove()
        session2 = db_session()
        try:
            repo2 = ExecutionRepository(session2)
            completed = repo2.complete_step(
                execution_step_id=step1_id,
                org_id=org_id,
                actual_inputs=[{"name": "Input A", "quantity": 9, "unit": "kg", "inventory_item_id": None}],
                actual_outputs=[{"name": "Out1", "quantity": 8, "unit": "kg", "inventory_item_id": None}],
            )
            assert completed is not None
        finally:
            session2.close()
            db_session.remove()
        session3 = db_session()
        try:
            repo3 = ExecutionRepository(session3)
            loaded = repo3.get_execution_with_steps(execution_id, org_id)
            assert loaded is not None
            step1 = next(es for es in loaded.execution_steps if es.step_number == 1)
            assert step1.status == ExecutionStepStatus.COMPLETED
            assert step1.actual_outputs and step1.actual_outputs[0]["name"] == "Out1"
        finally:
            session3.close()
            db_session.remove()


# ---------------------------------------------------------------------------
# Strict actual_inputs/actual_outputs shape
# ---------------------------------------------------------------------------


class TestActualInputsOutputsStrictShape:
    """Strict shape: only allowed keys; name str, quantity int/float, unit str, inventory_item_id str|None."""

    def test_actual_inputs_outputs_strict_shape(self, db, synthetic_org_and_process_clean):
        org_id = synthetic_org_and_process_clean["org_id"]
        process_id = synthetic_org_and_process_clean["process_id"]
        repo = ExecutionRepository(db)
        execution = repo.create_execution(org_id=org_id, process_id=process_id)
        steps = sorted(execution.execution_steps, key=lambda s: s.step_number)
        actual_inputs = [
            {"name": "Input A", "quantity": 5.0, "unit": "kg", "inventory_item_id": str(uuid4())},
        ]
        actual_outputs = [{"name": "Out1", "quantity": 4, "unit": "kg", "inventory_item_id": None}]
        repo.complete_step(
            execution_step_id=steps[0].id,
            org_id=org_id,
            actual_inputs=actual_inputs,
            actual_outputs=actual_outputs,
        )
        loaded = repo.get_execution_with_steps(execution.id, org_id)
        step = next(es for es in loaded.execution_steps if es.step_number == 1)
        for d in step.actual_inputs:
            assert (
                set(d.keys()) <= ALLOWED_INPUT_KEYS
            ), f"actual_inputs has extra keys: {set(d.keys()) - ALLOWED_INPUT_KEYS}"
            assert isinstance(d["name"], str)
            _assert_quantity_numeric(d["quantity"])
            assert isinstance(d["unit"], str)
            assert (
                "inventory_item_id" in d
            ), "actual_inputs should include inventory_item_id (str or None) for downstream consistency"
            assert d["inventory_item_id"] is None or isinstance(d["inventory_item_id"], str)
        for d in step.actual_outputs:
            assert (
                set(d.keys()) <= ALLOWED_OUTPUT_KEYS
            ), f"actual_outputs has extra keys: {set(d.keys()) - ALLOWED_OUTPUT_KEYS}"
            assert isinstance(d["name"], str)
            _assert_quantity_numeric(d["quantity"])
            assert isinstance(d["unit"], str)
            assert (
                "inventory_item_id" in d
            ), "actual_outputs should include inventory_item_id (str or None) for downstream consistency"
            assert d["inventory_item_id"] is None or isinstance(d["inventory_item_id"], str)


# ---------------------------------------------------------------------------
# completed_at timestamp
# ---------------------------------------------------------------------------


class TestCompletedAtTimestamp:
    """completed_at is set and within a few seconds of test run."""

    def test_completed_at_timestamp_is_recent(self, db, synthetic_org_and_process_clean):
        org_id = synthetic_org_and_process_clean["org_id"]
        process_id = synthetic_org_and_process_clean["process_id"]
        repo = ExecutionRepository(db)
        execution = repo.create_execution(org_id=org_id, process_id=process_id)
        steps = sorted(execution.execution_steps, key=lambda s: s.step_number)
        before = datetime.now(timezone.utc)
        repo.complete_step(
            execution_step_id=steps[0].id,
            org_id=org_id,
            actual_inputs=[{"name": "Input A", "quantity": 9, "unit": "kg"}],
            actual_outputs=[{"name": "Out1", "quantity": 8, "unit": "kg"}],
        )
        repo.complete_step(
            execution_step_id=steps[1].id,
            org_id=org_id,
            actual_inputs=[{"name": "Out1", "quantity": 8, "unit": "kg"}],
            actual_outputs=[{"name": "Final", "quantity": 7, "unit": "kg"}],
        )
        after = datetime.now(timezone.utc)
        loaded = repo.get_execution_by_id(execution.id, org_id)
        assert loaded.completed_at is not None
        assert isinstance(loaded.completed_at, datetime)
        # completed_at may be timezone-naive UTC; compare in UTC
        completed_utc = (
            loaded.completed_at if loaded.completed_at.tzinfo else loaded.completed_at.replace(tzinfo=timezone.utc)
        )
        assert (
            before <= completed_utc <= after + timedelta(seconds=5)
        ), "completed_at should be within a few seconds of test run"

    def test_completed_at_timezone_consistent_utc(self, db, synthetic_org_and_process_clean):
        """completed_at is stored and comparable in UTC (timezone-aware or naive UTC)."""
        org_id = synthetic_org_and_process_clean["org_id"]
        process_id = synthetic_org_and_process_clean["process_id"]
        repo = ExecutionRepository(db)
        execution = repo.create_execution(org_id=org_id, process_id=process_id)
        steps = sorted(execution.execution_steps, key=lambda s: s.step_number)
        repo.complete_step(
            execution_step_id=steps[0].id,
            org_id=org_id,
            actual_inputs=[{"name": "Input A", "quantity": 9, "unit": "kg"}],
            actual_outputs=[{"name": "Out1", "quantity": 8, "unit": "kg"}],
        )
        repo.complete_step(
            execution_step_id=steps[1].id,
            org_id=org_id,
            actual_inputs=[{"name": "Out1", "quantity": 8, "unit": "kg"}],
            actual_outputs=[{"name": "Final", "quantity": 7, "unit": "kg"}],
        )
        loaded = repo.get_execution_by_id(execution.id, org_id)
        assert loaded.completed_at is not None
        # If backend stores timezone-aware, it should be consistent (e.g. UTC)
        if getattr(loaded.completed_at, "tzinfo", None) is not None:
            assert loaded.completed_at.tzinfo is not None

    def test_completed_at_monotonic_across_steps(self, db, synthetic_org_process_three_steps):
        """completed_at is monotonic: step 1 completed_at <= step 2 completed_at <= step 3 completed_at."""
        org_id = synthetic_org_process_three_steps["org_id"]
        process_id = synthetic_org_process_three_steps["process_id"]
        repo = ExecutionRepository(db)
        execution = repo.create_execution(org_id=org_id, process_id=process_id)
        steps = sorted(execution.execution_steps, key=lambda s: s.step_number)
        for i, step in enumerate(steps):
            prev = "Input A" if i == 0 else ("Out1" if i == 1 else "Out2")
            out = "Out1" if i == 0 else ("Out2" if i == 1 else "Final")
            q_in = 10 - i - 1
            q_out = 8 - i - 1
            repo.complete_step(
                execution_step_id=step.id,
                org_id=org_id,
                actual_inputs=[{"name": prev, "quantity": q_in, "unit": "kg", "inventory_item_id": None}],
                actual_outputs=[{"name": out, "quantity": q_out, "unit": "kg", "inventory_item_id": None}],
            )
        full = repo.get_execution_with_steps(execution.id, org_id)
        completed_steps = [es for es in full.execution_steps if es.completed_at is not None]
        completed_steps.sort(key=lambda s: s.step_number)
        for i in range(1, len(completed_steps)):
            assert (
                completed_steps[i - 1].completed_at <= completed_steps[i].completed_at
            ), "completed_at should be monotonic by step order"


# ---------------------------------------------------------------------------
# Negative / regression
# ---------------------------------------------------------------------------


class TestCompleteStepNegative:
    """Invalid complete_step calls: wrong org, wrong step id, already completed step."""

    def test_complete_step_wrong_org_returns_none(self, db, synthetic_org_and_process_clean, demo_data):
        org_id = synthetic_org_and_process_clean["org_id"]
        other_org_id = demo_data["org_id"]
        repo = ExecutionRepository(db)
        execution = repo.create_execution(org_id=org_id, process_id=synthetic_org_and_process_clean["process_id"])
        steps = sorted(execution.execution_steps, key=lambda s: s.step_number)
        result = repo.complete_step(
            execution_step_id=steps[0].id,
            org_id=other_org_id,
            actual_inputs=[],
            actual_outputs=[],
        )
        assert result is None

    def test_complete_step_nonexistent_step_id_returns_none(self, db, synthetic_org_and_process_clean):
        org_id = synthetic_org_and_process_clean["org_id"]
        repo = ExecutionRepository(db)
        result = repo.complete_step(
            execution_step_id=uuid4(),
            org_id=org_id,
            actual_inputs=[],
            actual_outputs=[],
        )
        assert result is None

    def test_complete_step_already_completed_raises(self, db, synthetic_org_and_process_clean):
        org_id = synthetic_org_and_process_clean["org_id"]
        process_id = synthetic_org_and_process_clean["process_id"]
        repo = ExecutionRepository(db)
        execution = repo.create_execution(org_id=org_id, process_id=process_id)
        steps = sorted(execution.execution_steps, key=lambda s: s.step_number)
        repo.complete_step(
            execution_step_id=steps[0].id,
            org_id=org_id,
            actual_inputs=[{"name": "Input A", "quantity": 9, "unit": "kg"}],
            actual_outputs=[{"name": "Out1", "quantity": 8, "unit": "kg"}],
        )
        with pytest.raises(ValueError, match=RE_NOT_IN_STATE_TO_COMPLETE):
            repo.complete_step(
                execution_step_id=steps[0].id,
                org_id=org_id,
                actual_inputs=[],
                actual_outputs=[],
            )

    def test_complete_step_3_before_1_and_2_raises(self, db, synthetic_org_process_three_steps):
        """Out-of-order in 3-step process: completing step 3 before 1 and 2 raises."""
        org_id = synthetic_org_process_three_steps["org_id"]
        repo = ExecutionRepository(db)
        execution = repo.create_execution(org_id=org_id, process_id=synthetic_org_process_three_steps["process_id"])
        steps = sorted(execution.execution_steps, key=lambda s: s.step_number)
        # Completing step 3 before 1 and 2 should raise a prior-steps-not-completed error.
        with pytest.raises(ValueError, match=RE_PRIOR_STEPS_NOT_COMPLETED):
            repo.complete_step(
                execution_step_id=steps[2].id,
                org_id=org_id,
                actual_inputs=[{"name": "Out2", "quantity": 7, "unit": "kg"}],
                actual_outputs=[{"name": "Final", "quantity": 6, "unit": "kg"}],
            )

    def test_complete_step_after_execution_fully_completed_raises(self, db, synthetic_org_process_three_steps):
        """Completing any step after execution is COMPLETED raises."""
        org_id = synthetic_org_process_three_steps["org_id"]
        process_id = synthetic_org_process_three_steps["process_id"]
        repo = ExecutionRepository(db)
        execution = repo.create_execution(org_id=org_id, process_id=process_id)
        steps = sorted(execution.execution_steps, key=lambda s: s.step_number)
        repo.complete_step(
            execution_step_id=steps[0].id,
            org_id=org_id,
            actual_inputs=[{"name": "Input A", "quantity": 9, "unit": "kg"}],
            actual_outputs=[{"name": "Out1", "quantity": 8, "unit": "kg"}],
        )
        repo.complete_step(
            execution_step_id=steps[1].id,
            org_id=org_id,
            actual_inputs=[{"name": "Out1", "quantity": 8, "unit": "kg"}],
            actual_outputs=[{"name": "Out2", "quantity": 7, "unit": "kg"}],
        )
        repo.complete_step(
            execution_step_id=steps[2].id,
            org_id=org_id,
            actual_inputs=[{"name": "Out2", "quantity": 7, "unit": "kg"}],
            actual_outputs=[{"name": "Final", "quantity": 6, "unit": "kg"}],
        )
        loaded = repo.get_execution_by_id(execution.id, org_id)
        assert loaded.status == ExecutionStatus.COMPLETED
        with pytest.raises(ValueError, match=RE_NOT_IN_STATE_TO_COMPLETE):
            repo.complete_step(
                execution_step_id=steps[0].id,
                org_id=org_id,
                actual_inputs=[],
                actual_outputs=[],
            )


# ---------------------------------------------------------------------------
# Full flow (E2E-style)
# ---------------------------------------------------------------------------


class TestExecutionFlowE2E:
    """Full flow: create → complete step 1 with modal-shaped payload → get → complete step 2 → get; assert shapes."""

    def test_full_flow_actual_inputs_outputs_persisted_and_retrievable(self, db, synthetic_org_and_process_clean):
        org_id = synthetic_org_and_process_clean["org_id"]
        process_id = synthetic_org_and_process_clean["process_id"]
        repo = ExecutionRepository(db)
        execution = repo.create_execution(org_id=org_id, process_id=process_id)
        steps = sorted(execution.execution_steps, key=lambda s: s.step_number)
        # Simulate execution modal payload (e.g. user selected inventory → quantity = item total)
        step1_inputs = [
            {"name": "Input A", "quantity": 12.5, "unit": "kg", "inventory_item_id": str(uuid4())},
        ]
        step1_outputs = [{"name": "Out1", "quantity": 10, "unit": "kg"}]
        repo.complete_step(
            execution_step_id=steps[0].id,
            org_id=org_id,
            actual_inputs=step1_inputs,
            actual_outputs=step1_outputs,
            execution_data={"completed_by": "user@test.com"},
        )
        loaded = repo.get_execution_with_steps(execution.id, org_id)
        step1 = next(es for es in loaded.execution_steps if es.step_number == 1)
        assert step1.actual_inputs[0]["name"] == "Input A"
        _assert_quantity_close(step1.actual_inputs[0]["quantity"], 12.5)
        assert step1.actual_inputs[0]["unit"] == "kg"
        assert "inventory_item_id" in step1.actual_inputs[0]
        assert step1.actual_outputs[0]["name"] == "Out1"
        _assert_quantity_close(step1.actual_outputs[0]["quantity"], 10)
        assert step1.actual_outputs[0]["unit"] == "kg"
        _assert_quantity_positive(step1.actual_inputs[0]["quantity"])
        _assert_quantity_positive(step1.actual_outputs[0]["quantity"])
        # Complete step 2
        step2 = next(es for es in loaded.execution_steps if es.step_number == 2)
        repo.complete_step(
            execution_step_id=step2.id,
            org_id=org_id,
            actual_inputs=[{"name": "Out1", "quantity": 10, "unit": "kg"}],
            actual_outputs=[{"name": "Final", "quantity": 9, "unit": "kg"}],
        )
        loaded2 = repo.get_execution_with_steps(execution.id, org_id)
        assert loaded2.status == ExecutionStatus.COMPLETED
        step1_again = next(es for es in loaded2.execution_steps if es.step_number == 1)
        step2_again = next(es for es in loaded2.execution_steps if es.step_number == 2)
        _assert_quantity_close(step1_again.actual_outputs[0]["quantity"], 10)
        _assert_quantity_close(step2_again.actual_inputs[0]["quantity"], 10)
        _assert_quantity_close(step2_again.actual_outputs[0]["quantity"], 9)
        _assert_quantity_numeric(step1_again.actual_outputs[0]["quantity"])
        _assert_quantity_numeric(step2_again.actual_inputs[0]["quantity"])
        _assert_quantity_numeric(step2_again.actual_outputs[0]["quantity"])

    def test_three_step_e2e_status_and_strict_shapes(self, db, synthetic_org_process_three_steps):
        """3-step E2E: complete 1, 2, 3 with modal payloads; verify IN_PROGRESS → IN_PROGRESS → COMPLETED and shapes."""
        org_id = synthetic_org_process_three_steps["org_id"]
        process_id = synthetic_org_process_three_steps["process_id"]
        repo = ExecutionRepository(db)
        execution = repo.create_execution(org_id=org_id, process_id=process_id)
        steps = sorted(execution.execution_steps, key=lambda s: s.step_number)
        # Step 1
        repo.complete_step(
            execution_step_id=steps[0].id,
            org_id=org_id,
            actual_inputs=[{"name": "Input A", "quantity": 12.5, "unit": "kg", "inventory_item_id": str(uuid4())}],
            actual_outputs=[{"name": "Out1", "quantity": 10.0, "unit": "kg"}],
            execution_data={"completed_by": "user@test.com"},
        )
        loaded = repo.get_execution_with_steps(execution.id, org_id)
        assert loaded.status == ExecutionStatus.IN_PROGRESS
        step1 = next(es for es in loaded.execution_steps if es.step_number == 1)
        _assert_quantity_close(step1.actual_inputs[0]["quantity"], 12.5)
        _assert_quantity_close(step1.actual_outputs[0]["quantity"], 10.0)
        _assert_quantity_numeric(step1.actual_inputs[0]["quantity"])
        _assert_quantity_numeric(step1.actual_outputs[0]["quantity"])
        assert set(step1.actual_inputs[0].keys()) <= ALLOWED_INPUT_KEYS
        assert set(step1.actual_outputs[0].keys()) <= ALLOWED_OUTPUT_KEYS
        # Step 2
        repo.complete_step(
            execution_step_id=steps[1].id,
            org_id=org_id,
            actual_inputs=[{"name": "Out1", "quantity": 10.0, "unit": "kg"}],
            actual_outputs=[{"name": "Out2", "quantity": 7.5, "unit": "kg"}],
        )
        loaded = repo.get_execution_with_steps(execution.id, org_id)
        assert loaded.status == ExecutionStatus.IN_PROGRESS
        step2 = next(es for es in loaded.execution_steps if es.step_number == 2)
        _assert_quantity_numeric(step2.actual_inputs[0]["quantity"])
        _assert_quantity_numeric(step2.actual_outputs[0]["quantity"])
        # Step 3
        repo.complete_step(
            execution_step_id=steps[2].id,
            org_id=org_id,
            actual_inputs=[{"name": "Out2", "quantity": 7.5, "unit": "kg"}],
            actual_outputs=[{"name": "Final", "quantity": 6.0, "unit": "kg"}],
        )
        loaded = repo.get_execution_by_id(execution.id, org_id)
        assert loaded.status == ExecutionStatus.COMPLETED
        full = repo.get_execution_with_steps(execution.id, org_id)
        for es in full.execution_steps:
            for inp in es.actual_inputs:
                _assert_quantity_numeric(inp["quantity"])
                assert set(inp.keys()) <= ALLOWED_INPUT_KEYS
            for out in es.actual_outputs:
                _assert_quantity_numeric(out["quantity"])
                assert set(out.keys()) <= ALLOWED_OUTPUT_KEYS


# ---------------------------------------------------------------------------
# Regression safeguards
# ---------------------------------------------------------------------------


class TestRegressionSafeguards:
    """Edge cases: zero/fractional quantities, invalid unit, extra/missing keys; contract violations."""

    def test_fractional_quantity_persisted_and_retrievable(self, db, synthetic_org_and_process_clean):
        """Fractional quantities are stored and compared with isclose."""
        org_id = synthetic_org_and_process_clean["org_id"]
        process_id = synthetic_org_and_process_clean["process_id"]
        repo = ExecutionRepository(db)
        execution = repo.create_execution(org_id=org_id, process_id=process_id)
        steps = sorted(execution.execution_steps, key=lambda s: s.step_number)
        repo.complete_step(
            execution_step_id=steps[0].id,
            org_id=org_id,
            actual_inputs=[{"name": "Input A", "quantity": 2.5, "unit": "kg", "inventory_item_id": None}],
            actual_outputs=[{"name": "Out1", "quantity": 1.875, "unit": "kg", "inventory_item_id": None}],
        )
        loaded = repo.get_execution_with_steps(execution.id, org_id)
        step = next(es for es in loaded.execution_steps if es.step_number == 1)
        _assert_quantity_close(step.actual_inputs[0]["quantity"], 2.5)
        _assert_quantity_close(step.actual_outputs[0]["quantity"], 1.875)

    def test_zero_quantity_accepted_by_repo(self, db, synthetic_org_and_process_clean):
        """Repo accepts zero quantity (business rules may forbid elsewhere)."""
        org_id = synthetic_org_and_process_clean["org_id"]
        process_id = synthetic_org_and_process_clean["process_id"]
        repo = ExecutionRepository(db)
        execution = repo.create_execution(org_id=org_id, process_id=process_id)
        steps = sorted(execution.execution_steps, key=lambda s: s.step_number)
        repo.complete_step(
            execution_step_id=steps[0].id,
            org_id=org_id,
            actual_inputs=[{"name": "Input A", "quantity": 0, "unit": "kg", "inventory_item_id": None}],
            actual_outputs=[{"name": "Out1", "quantity": 0, "unit": "kg", "inventory_item_id": None}],
        )
        loaded = repo.get_execution_with_steps(execution.id, org_id)
        step = next(es for es in loaded.execution_steps if es.step_number == 1)
        _assert_quantity_close(step.actual_inputs[0]["quantity"], 0)
        _assert_quantity_close(step.actual_outputs[0]["quantity"], 0)

    def test_invalid_unit_stored_as_is(self, db, synthetic_org_and_process_clean):
        """Invalid or non-standard unit string is stored as-is (no validation in repo)."""
        org_id = synthetic_org_and_process_clean["org_id"]
        process_id = synthetic_org_and_process_clean["process_id"]
        repo = ExecutionRepository(db)
        execution = repo.create_execution(org_id=org_id, process_id=process_id)
        steps = sorted(execution.execution_steps, key=lambda s: s.step_number)
        repo.complete_step(
            execution_step_id=steps[0].id,
            org_id=org_id,
            actual_inputs=[{"name": "Input A", "quantity": 1, "unit": "invalid_unit", "inventory_item_id": None}],
            actual_outputs=[{"name": "Out1", "quantity": 1, "unit": "invalid_unit", "inventory_item_id": None}],
        )
        loaded = repo.get_execution_with_steps(execution.id, org_id)
        step = next(es for es in loaded.execution_steps if es.step_number == 1)
        assert step.actual_inputs[0]["unit"] == "invalid_unit"
        assert step.actual_outputs[0]["unit"] == "invalid_unit"

    def test_extra_keys_stored_and_retrieved(self, db, synthetic_org_and_process_clean):
        """Payload with extra keys is stored (JSONB keeps all keys); strict shape tests elsewhere enforce contract."""
        org_id = synthetic_org_and_process_clean["org_id"]
        process_id = synthetic_org_and_process_clean["process_id"]
        repo = ExecutionRepository(db)
        execution = repo.create_execution(org_id=org_id, process_id=process_id)
        steps = sorted(execution.execution_steps, key=lambda s: s.step_number)
        repo.complete_step(
            execution_step_id=steps[0].id,
            org_id=org_id,
            actual_inputs=[
                {"name": "Input A", "quantity": 1, "unit": "kg", "inventory_item_id": None, "extra": "ignored"},
            ],
            actual_outputs=[
                {"name": "Out1", "quantity": 1, "unit": "kg", "inventory_item_id": None, "extra": "ignored"}
            ],
        )
        loaded = repo.get_execution_with_steps(execution.id, org_id)
        step = next(es for es in loaded.execution_steps if es.step_number == 1)
        assert "extra" in step.actual_inputs[0]
        assert step.actual_inputs[0]["extra"] == "ignored"
        assert "extra" in step.actual_outputs[0]

    def test_minimal_keys_name_quantity_unit_accepted(self, db, synthetic_org_and_process_clean):
        """Minimal payload (name, quantity, unit only) is accepted and persisted."""
        org_id = synthetic_org_and_process_clean["org_id"]
        process_id = synthetic_org_and_process_clean["process_id"]
        repo = ExecutionRepository(db)
        execution = repo.create_execution(org_id=org_id, process_id=process_id)
        steps = sorted(execution.execution_steps, key=lambda s: s.step_number)
        repo.complete_step(
            execution_step_id=steps[0].id,
            org_id=org_id,
            actual_inputs=[{"name": "Input A", "quantity": 1, "unit": "kg"}],
            actual_outputs=[{"name": "Out1", "quantity": 1, "unit": "kg"}],
        )
        loaded = repo.get_execution_with_steps(execution.id, org_id)
        step = next(es for es in loaded.execution_steps if es.step_number == 1)
        assert step.actual_inputs[0]["name"] == "Input A"
        assert step.actual_outputs[0]["name"] == "Out1"
        _assert_quantity_close(step.actual_inputs[0]["quantity"], 1)
        _assert_quantity_close(step.actual_outputs[0]["quantity"], 1)

    def test_missing_required_keys_stored_as_sent(self, db, synthetic_org_and_process_clean):
        """Repo does not validate required keys; payload with missing 'name' is stored as-is (contract elsewhere)."""
        org_id = synthetic_org_and_process_clean["org_id"]
        process_id = synthetic_org_and_process_clean["process_id"]
        repo = ExecutionRepository(db)
        execution = repo.create_execution(org_id=org_id, process_id=process_id)
        steps = sorted(execution.execution_steps, key=lambda s: s.step_number)
        repo.complete_step(
            execution_step_id=steps[0].id,
            org_id=org_id,
            actual_inputs=[{"quantity": 1, "unit": "kg"}],
            actual_outputs=[{"quantity": 1, "unit": "kg"}],
        )
        loaded = repo.get_execution_with_steps(execution.id, org_id)
        step = next(es for es in loaded.execution_steps if es.step_number == 1)
        assert "name" not in step.actual_inputs[0]
        _assert_quantity_close(step.actual_inputs[0]["quantity"], 1)
        assert "name" not in step.actual_outputs[0]
        _assert_quantity_close(step.actual_outputs[0]["quantity"], 1)

    def test_negative_quantity_accepted_by_repo(self, db, synthetic_org_and_process_clean):
        """Repo accepts negative quantity (business rules may reject elsewhere)."""
        org_id = synthetic_org_and_process_clean["org_id"]
        process_id = synthetic_org_and_process_clean["process_id"]
        repo = ExecutionRepository(db)
        execution = repo.create_execution(org_id=org_id, process_id=process_id)
        steps = sorted(execution.execution_steps, key=lambda s: s.step_number)
        repo.complete_step(
            execution_step_id=steps[0].id,
            org_id=org_id,
            actual_inputs=[{"name": "Input A", "quantity": -1, "unit": "kg", "inventory_item_id": None}],
            actual_outputs=[{"name": "Out1", "quantity": -1, "unit": "kg", "inventory_item_id": None}],
        )
        loaded = repo.get_execution_with_steps(execution.id, org_id)
        step = next(es for es in loaded.execution_steps if es.step_number == 1)
        _assert_quantity_close(step.actual_inputs[0]["quantity"], -1)
        _assert_quantity_close(step.actual_outputs[0]["quantity"], -1)

    def test_inventory_item_id_linkage_preserved_across_steps(self, db, synthetic_org_process_three_steps):
        """inventory_item_id in actual_inputs/actual_outputs is stored and preserved (linkage for tracing)."""
        org_id = synthetic_org_process_three_steps["org_id"]
        process_id = synthetic_org_process_three_steps["process_id"]
        repo = ExecutionRepository(db)
        execution = repo.create_execution(org_id=org_id, process_id=process_id)
        steps = sorted(execution.execution_steps, key=lambda s: s.step_number)
        inv_id = str(uuid4())
        repo.complete_step(
            execution_step_id=steps[0].id,
            org_id=org_id,
            actual_inputs=[{"name": "Input A", "quantity": 9, "unit": "kg", "inventory_item_id": inv_id}],
            actual_outputs=[{"name": "Out1", "quantity": 8, "unit": "kg", "inventory_item_id": None}],
        )
        repo.complete_step(
            execution_step_id=steps[1].id,
            org_id=org_id,
            actual_inputs=[{"name": "Out1", "quantity": 8, "unit": "kg", "inventory_item_id": inv_id}],
            actual_outputs=[{"name": "Out2", "quantity": 7, "unit": "kg", "inventory_item_id": None}],
        )
        full = repo.get_execution_with_steps(execution.id, org_id)
        step1 = next(es for es in full.execution_steps if es.step_number == 1)
        step2 = next(es for es in full.execution_steps if es.step_number == 2)
        assert step1.actual_inputs[0].get("inventory_item_id") == inv_id
        assert step2.actual_inputs[0].get("inventory_item_id") == inv_id
