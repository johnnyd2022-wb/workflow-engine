"""
Tests for core checks (expired_materials, etc.) – compliance semantics only.

Scope: expired_materials.py, corechecks.py, output_expiry_check.py, and API response shape.
Do NOT modify DAG traversal (dagtraversal.py). Tests validate behavior, not implementation details.
"""

from datetime import date, datetime, timedelta, timezone

import pytest

from app.core.backend.checks.expired_materials import run_expired_materials_check
from app.core.backend.checks.output_expiry_check import run_output_expiry_check
from app.core.backend.corechecks import CoreChecksRunner
from app.core.db import db_session
from app.core.db.models.execution import Execution
from app.core.db.models.execution_step import ExecutionStep
from app.core.db.models.inventory_item import InventoryItem, InventoryType
from app.core.db.models.organisation import Organisation
from app.core.db.models.process import Process
from app.core.db.models.step import Step
from app.core.db.repositories.execution_repo import ExecutionRepository
from app.core.db.repositories.inventory_repo import InventoryRepository
from app.core.db.repositories.organisation_repo import OrganisationRepository
from app.core.db.repositories.process_repo import ProcessRepository
from app.core.utils.resetdb import DEMO_USER_EMAIL, clear_demo_db, reset_demo_db


@pytest.fixture
def db():
    """Real database session for integration tests."""
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


# ---------------------------------------------------------------------------
# Compliance semantics (cursor_instructions/corechecks.md §6)
# ---------------------------------------------------------------------------


class TestExpiredMaterialsComplianceSemantics:
    """Lock in compliance semantics: zero quantity not flagged; shape; connections deduplicated."""

    def test_expired_raw_with_zero_quantity_not_in_results(self, db):
        """Expired raw with zero quantity: not flagged, not included in expired_raw_materials."""
        from app.core.db.repositories.inventory_repo import InventoryRepository
        from app.core.db.repositories.organisation_repo import OrganisationRepository

        org_repo = OrganisationRepository(db)
        inv_repo = InventoryRepository(db)
        org = org_repo.create_org("Corechecks Zero Qty Org")
        try:
            today = date.today()
            expiry_past = today - timedelta(days=7)
            raw = inv_repo.create_inventory_item(
                org_id=org.id,
                name="Expired Zero Qty Raw",
                quantity="0",
                unit="kg",
                inventory_type=InventoryType.RAW_MATERIAL.value,
                supplier="Test",
                purchase_date=today - timedelta(days=365),
                supplier_batch_number="Z-001",
                expiry_date=expiry_past,
                source_execution_id=None,
                source_execution_step_id=None,
                source_step_name=None,
                extra_data=None,
            )
            result = run_expired_materials_check(org.id, db)
            assert result.check_id == "expired_materials"
            assert result.data is not None
            expired_list = result.data.get("expired_raw_materials") or []
            ids = [e["id"] for e in expired_list]
            assert str(raw.id) not in ids, "Expired raw with quantity 0 must not be included"
            assert not result.flagged, "Should not be flagged when only expired raw has zero quantity"
        finally:
            db.query(InventoryItem).filter(InventoryItem.org_id == org.id).delete(synchronize_session=False)
            db.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
            db.commit()

    def test_expired_materials_response_shape(self, db, demo_data):
        """API / check response shape: expired_raw_materials, impacted_items, connections."""
        org_id = demo_data["org_id"]
        result = run_expired_materials_check(org_id, db)
        assert result.check_id == "expired_materials"
        assert result.data is not None
        assert "expired_raw_materials" in result.data
        assert "impacted_items" in result.data
        assert "connections" in result.data
        assert isinstance(result.data["expired_raw_materials"], list)
        assert isinstance(result.data["impacted_items"], list)
        assert isinstance(result.data["connections"], list)

    def test_demo_expired_raw_with_stock_flagged(self, db, demo_data):
        """After reset_demo_db: at least one expired raw with stock is flagged and present in results."""
        org_id = demo_data["org_id"]
        result = run_expired_materials_check(org_id, db)
        expired = result.data.get("expired_raw_materials") or []
        assert len(expired) >= 1, "Demo data includes at least one expired raw material with stock"
        assert result.flagged

    def test_connections_deduplicated(self, db, demo_data):
        """Connections list has no duplicate (from_id, to_id, execution_id)."""
        org_id = demo_data["org_id"]
        result = run_expired_materials_check(org_id, db)
        connections = result.data.get("connections") or []
        keys = [(c.get("from_id"), c.get("to_id"), c.get("execution_id")) for c in connections]
        assert len(keys) == len(set(keys)), "Connections must be deduplicated by (from_id, to_id, execution_id)"

    def test_runner_expired_materials_same_shape(self, db, demo_data):
        """CoreChecksRunner.run_check('expired_materials') returns same data shape as API."""
        org_id = demo_data["org_id"]
        runner = CoreChecksRunner(org_id=org_id, session=db)
        result = runner.run_check("expired_materials")
        assert result is not None
        assert result.data is not None
        assert "expired_raw_materials" in result.data
        assert "impacted_items" in result.data
        assert "connections" in result.data


def _make_output_expiry_fixture(db, org_id, mode="set_at_execution", completed_at_days_ago=10, expiry_past_days=5):
    """
    Create minimal process/step/execution/execution_step/inventory for output_expiry check.
    mode: "set_at_execution" or "fixed_duration".
    completed_at_days_ago: set execution step completed_at this many days in the past.
    expiry_past_days: for datetime mode, expiry_at is this many days in the past (so item is expired).
    Returns (process, step, execution, execution_step, inventory_item) for cleanup and assertions.
    """
    now = datetime.now(timezone.utc)
    process_repo = ProcessRepository(db)
    exec_repo = ExecutionRepository(db)
    inv_repo = InventoryRepository(db)

    step_output = {
        "name": "Expiry Test Output",
        "quantity": 1,
        "unit": "kg",
        "extra_data": {
            "custom_expiry": {
                "enabled": True,
                "mode": mode,
                "duration_value": 5 if mode == "fixed_duration" else None,
                "duration_unit": "days",
                "warning_value": 2,
                "warning_unit": "days",
            }
        },
    }

    process = process_repo.create_process(
        org_id=org_id,
        name="Output Expiry Test Process",
        description="For output_expiry check tests",
        is_draft=False,
    )
    step = process_repo.add_step(
        process_id=process.id,
        org_id=org_id,
        step_number=1,
        name="Single Step",
        description="One output with custom expiry",
        inputs=[],
        outputs=[step_output],
        execution_prompts=[],
    )
    assert step is not None

    execution = exec_repo.create_execution(org_id=org_id, process_id=process.id)
    execution_steps = (
        db.query(ExecutionStep)
        .filter(ExecutionStep.execution_id == execution.id)
        .order_by(ExecutionStep.step_number)
        .all()
    )
    assert len(execution_steps) == 1
    exec_step = execution_steps[0]

    exec_repo.complete_step(
        execution_step_id=exec_step.id,
        org_id=org_id,
        actual_inputs=[],
        actual_outputs=[{"name": "Expiry Test Output", "quantity": 10, "unit": "kg"}],
        execution_data={},
    )
    db.refresh(exec_step)
    exec_step.completed_at = now - timedelta(days=completed_at_days_ago)
    db.commit()

    extra_data = None
    if mode == "set_at_execution":
        expiry_at = (now - timedelta(days=expiry_past_days)).isoformat()
        extra_data = {
            "custom_expiry_actual": {
                "mode": "datetime",
                "expiry_at": expiry_at,
                "warning_value": 2,
                "warning_unit": "days",
            }
        }

    inventory_item = inv_repo.create_inventory_item(
        org_id=org_id,
        name="Expiry Test Output",
        quantity="10",
        unit="kg",
        inventory_type=InventoryType.WORK_IN_PROGRESS.value,
        supplier=None,
        purchase_date=None,
        supplier_batch_number=None,
        expiry_date=None,
        source_execution_id=execution.id,
        source_execution_step_id=exec_step.id,
        source_step_name=step.name,
        extra_data=extra_data,
    )
    return process, step, execution, exec_step, inventory_item


def _cleanup_output_expiry_fixture(db, org_id, process, execution, inventory_item):
    """Remove fixture data: inventory, execution_steps, execution, steps, process (FK order)."""
    db.query(InventoryItem).filter(InventoryItem.id == inventory_item.id).delete(synchronize_session=False)
    db.query(ExecutionStep).filter(ExecutionStep.execution_id == execution.id).delete(synchronize_session=False)
    db.query(Execution).filter(Execution.id == execution.id).delete(synchronize_session=False)
    db.query(Step).filter(Step.process_id == process.id).delete(synchronize_session=False)
    db.query(Process).filter(Process.id == process.id).delete(synchronize_session=False)
    db.commit()


class TestOutputExpiryCheck:
    """Custom output expiry check: registered, shape, duration/datetime, and integration."""

    def test_output_expiry_registered_and_shape(self, db, demo_data):
        """output_expiry check is registered and returns output_expiry_items list."""
        org_id = demo_data["org_id"]
        runner = CoreChecksRunner(org_id=org_id, session=db)
        result = runner.run_check("output_expiry")
        assert result is not None
        assert result.check_id == "output_expiry"
        assert result.data is not None
        assert "output_expiry_items" in result.data
        assert isinstance(result.data["output_expiry_items"], list)

    def test_output_expiry_result_item_shape(self, db, demo_data):
        """Every item in output_expiry_items has required keys and expiry_at is valid ISO."""
        org_id = demo_data["org_id"]
        process, step, execution, exec_step, inv_item = _make_output_expiry_fixture(
            db, org_id, mode="set_at_execution", completed_at_days_ago=10, expiry_past_days=5
        )
        try:
            result = run_output_expiry_check(org_id, db)
            items = result.data.get("output_expiry_items") or []
            assert len(items) >= 1
            for item in items:
                assert isinstance(item, dict)
                for key in (
                    "type",
                    "severity",
                    "message",
                    "execution_id",
                    "process_id",
                    "step_id",
                    "inventory_item_id",
                    "item_name",
                    "unit",
                    "expiry_at",
                    "warning_value",
                    "warning_unit",
                    "config_mode",
                ):
                    assert key in item, f"output_expiry item missing key: {key}"
                assert item["type"] == "expiry"
                assert item["severity"] in ("red", "amber")
                assert item["warning_value"] >= 0
                # expiry_at must be ISO-parseable
                raw = item["expiry_at"]
                assert isinstance(raw, str), "expiry_at must be string"
                datetime.fromisoformat(raw.replace("Z", "+00:00"))
        finally:
            _cleanup_output_expiry_fixture(db, org_id, process, execution, inv_item)

    def test_output_expiry_datetime_returns_iso_and_severity(self, db, demo_data):
        """Datetime-based expiry: result has expiry_at as ISO string and severity red or amber."""
        org_id = demo_data["org_id"]
        process, step, execution, exec_step, inv_item = _make_output_expiry_fixture(
            db, org_id, mode="set_at_execution", completed_at_days_ago=10, expiry_past_days=5
        )
        try:
            result = run_output_expiry_check(org_id, db)
            items = result.data.get("output_expiry_items") or []
            found = [i for i in items if i.get("inventory_item_id") == str(inv_item.id)]
            assert len(found) == 1, "expected one output_expiry item for our fixture inventory"
            item = found[0]
            assert "expiry_at" in item
            assert isinstance(item["expiry_at"], str)
            datetime.fromisoformat(item["expiry_at"].replace("Z", "+00:00"))
            assert item["severity"] in ("red", "amber")
            assert item["config_mode"] == "set_at_execution"
        finally:
            _cleanup_output_expiry_fixture(db, org_id, process, execution, inv_item)

    def test_output_expiry_duration_fixed_included(self, db, demo_data):
        """Fixed-duration step output: item is included with expiry_at = completed_at + duration."""
        org_id = demo_data["org_id"]
        process, step, execution, exec_step, inv_item = _make_output_expiry_fixture(
            db, org_id, mode="fixed_duration", completed_at_days_ago=10
        )
        try:
            result = run_output_expiry_check(org_id, db)
            items = result.data.get("output_expiry_items") or []
            found = [i for i in items if i.get("inventory_item_id") == str(inv_item.id)]
            assert len(found) == 1
            item = found[0]
            assert item["config_mode"] == "fixed_duration"
            assert "expiry_at" in item
            # completed_at was 10 days ago, duration 5 days -> expiry 5 days ago (expired)
            expiry_dt = datetime.fromisoformat(item["expiry_at"].replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            assert (now - expiry_dt).days >= 4  # at least ~5 days in the past
        finally:
            _cleanup_output_expiry_fixture(db, org_id, process, execution, inv_item)

    def test_output_expiry_custom_actual_reflected(self, db, demo_data):
        """custom_expiry_actual (set_at_execution payload) is reflected in check result."""
        org_id = demo_data["org_id"]
        process, step, execution, exec_step, inv_item = _make_output_expiry_fixture(
            db, org_id, mode="set_at_execution", completed_at_days_ago=10, expiry_past_days=3
        )
        try:
            result = run_output_expiry_check(org_id, db)
            items = result.data.get("output_expiry_items") or []
            found = [i for i in items if i.get("inventory_item_id") == str(inv_item.id)]
            assert len(found) == 1
            item = found[0]
            assert item["config_mode"] == "set_at_execution"
            assert item["expiry_at"]
            assert item["warning_value"] >= 0
            assert item["warning_unit"] in ("hours", "days", "weeks", "months")
            # Message should reference the output name
            assert "Expiry Test Output" in (item.get("message") or "")
        finally:
            _cleanup_output_expiry_fixture(db, org_id, process, execution, inv_item)

    def test_output_expiry_invalid_unit_fallback(self, db, demo_data):
        """Step config with invalid duration_unit: check does not crash and falls back (e.g. to days)."""
        org_id = demo_data["org_id"]
        process_repo = ProcessRepository(db)
        exec_repo = ExecutionRepository(db)
        inv_repo = InventoryRepository(db)
        now = datetime.now(timezone.utc)
        step_output = {
            "name": "Invalid Unit Output",
            "quantity": 1,
            "unit": "L",
            "extra_data": {
                "custom_expiry": {
                    "enabled": True,
                    "mode": "fixed_duration",
                    "duration_value": 5,
                    "duration_unit": "invalid_unit",  # not in _ALLOWED_UNITS; check falls back to "days"
                    "warning_value": 1,
                    "warning_unit": "days",
                }
            },
        }
        process = process_repo.create_process(
            org_id=org_id, name="Invalid Unit Process", description="", is_draft=False
        )
        step = process_repo.add_step(
            process_id=process.id,
            org_id=org_id,
            step_number=1,
            name="Step",
            inputs=[],
            outputs=[step_output],
            execution_prompts=[],
        )
        assert step is not None
        execution = exec_repo.create_execution(org_id=org_id, process_id=process.id)
        exec_steps = (
            db.query(ExecutionStep)
            .filter(ExecutionStep.execution_id == execution.id)
            .order_by(ExecutionStep.step_number)
            .all()
        )
        exec_step = exec_steps[0]
        exec_repo.complete_step(
            execution_step_id=exec_step.id,
            org_id=org_id,
            actual_inputs=[],
            actual_outputs=[{"name": "Invalid Unit Output", "quantity": 5, "unit": "L"}],
            execution_data={},
        )
        db.refresh(exec_step)
        exec_step.completed_at = now - timedelta(days=10)
        db.commit()
        inv_item = inv_repo.create_inventory_item(
            org_id=org_id,
            name="Invalid Unit Output",
            quantity="5",
            unit="L",
            inventory_type=InventoryType.WORK_IN_PROGRESS.value,
            supplier=None,
            purchase_date=None,
            supplier_batch_number=None,
            expiry_date=None,
            source_execution_id=execution.id,
            source_execution_step_id=exec_step.id,
            source_step_name=step.name,
            extra_data=None,
        )
        try:
            result = run_output_expiry_check(org_id, db)
            items = result.data.get("output_expiry_items") or []
            found = [i for i in items if i.get("inventory_item_id") == str(inv_item.id)]
            assert len(found) == 1, "check should return item despite invalid_unit (fallback to days)"
            assert "expiry_at" in found[0]
            datetime.fromisoformat(found[0]["expiry_at"].replace("Z", "+00:00"))
        finally:
            _cleanup_output_expiry_fixture(db, org_id, process, execution, inv_item)

    def test_output_expiry_duration_warning_consistency(self, db, demo_data):
        """Result items: warning_value >= 0 and expiry_at valid.
        Note: warning > duration is rejected at execution save time (backend); see
        test_executions.TestCustomExpiryWarningNotExceedDuration for that safeguard."""
        org_id = demo_data["org_id"]
        process, step, execution, exec_step, inv_item = _make_output_expiry_fixture(
            db, org_id, mode="fixed_duration", completed_at_days_ago=10
        )
        try:
            result = run_output_expiry_check(org_id, db)
            for item in result.data.get("output_expiry_items") or []:
                assert item.get("warning_value") is not None
                assert int(item["warning_value"]) >= 0
                assert "expiry_at" in item
                datetime.fromisoformat(item["expiry_at"].replace("Z", "+00:00"))
        finally:
            _cleanup_output_expiry_fixture(db, org_id, process, execution, inv_item)

    def test_output_expiry_integration_set_at_execution(self, db, demo_data):
        """Full integration: set_at_execution output + inventory with custom_expiry_actual -> in output_expiry_items."""
        org_id = demo_data["org_id"]
        runner = CoreChecksRunner(org_id=org_id, session=db)
        process, step, execution, exec_step, inv_item = _make_output_expiry_fixture(
            db, org_id, mode="set_at_execution", completed_at_days_ago=10, expiry_past_days=5
        )
        try:
            result = runner.run_check("output_expiry")
            assert result is not None
            assert result.check_id == "output_expiry"
            items = result.data.get("output_expiry_items") or []
            ids = [i.get("inventory_item_id") for i in items]
            assert str(inv_item.id) in ids
            found = next(i for i in items if i.get("inventory_item_id") == str(inv_item.id))
            assert found["process_id"] == str(process.id)
            assert found["step_id"] == str(step.id)
            assert found["execution_id"] == str(execution.id)
        finally:
            _cleanup_output_expiry_fixture(db, org_id, process, execution, inv_item)
