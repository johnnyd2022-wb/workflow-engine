"""
Tests for core checks (expired_materials, etc.) – compliance semantics only.

Scope: expired_materials.py, corechecks.py, and API response shape.
Do NOT modify DAG traversal (dagtraversal.py). Tests validate behavior, not implementation details.
"""

from datetime import date, timedelta

import pytest

from app.core.backend.checks.expired_materials import run_expired_materials_check
from app.core.backend.corechecks import CoreChecksRunner
from app.core.db import db_session
from app.core.db.models.inventory_item import InventoryItem, InventoryType
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
        from app.core.db.models.organisation import Organisation
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


class TestOutputExpiryCheck:
    """Custom output expiry check: registered and returns expected shape."""

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
