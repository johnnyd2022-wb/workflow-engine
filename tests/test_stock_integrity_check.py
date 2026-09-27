"""Plan 1.7: stock arithmetic, whole counts, and module finding boundary."""

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import text

from app.core.db.repositories.inventory_repo import InventoryRepository
from app.core.domain.inventory_quantity_guard import InventoryQuantityWriteReason, allow_inventory_quantity_write
from app.features.inventory.checks.stock_integrity import CHECK_ID, _lot_balance, run_stock_integrity_check
from tests.factories import OrganisationFactory


def _event(event_type, payload, diff=None):
    return SimpleNamespace(event_type=event_type, payload=payload, diff=diff)


def test_lot_balance_accepts_produced_sold_wasted_and_adjusted():
    item = SimpleNamespace(quantity=Decimal("8"), unit="bottles")
    events = [
        _event("inventory_item.created", {"quantity": "10"}),
        _event("inventory_item.quantity_adjusted", {"delta": "-3", "reason": "sales_fifo_consumption"}),
        _event("inventory_item.updated", {}, {"quantity": {"before": "7", "after": "9"}}),
    ]
    assert _lot_balance(item, events, Decimal("1"), Decimal("3")) == []


def test_lot_balance_flags_fractional_count_and_missing_sale_allocation():
    item = SimpleNamespace(quantity=Decimal("7.5"), unit="bottles")
    events = [
        _event("inventory_item.created", {"quantity": "10"}),
        _event("inventory_item.quantity_adjusted", {"delta": "-3", "reason": "sales_manual_allocation"}),
    ]
    codes = {code for code, _ in _lot_balance(item, events, Decimal("0"), Decimal("0"))}
    assert codes == {"fractional_count", "balance_mismatch", "sale_allocation_mismatch"}


def test_lot_balance_subtracts_production_use_in_canonical_unit():
    item = SimpleNamespace(quantity=Decimal("9"), unit="L")
    events = [
        _event("inventory_item.created", {"quantity": "10"}),
        _event("inventory_item.consumed", {"quantity_consumed": "1000", "unit": "ml"}),
    ]
    assert _lot_balance(item, events, Decimal("0"), Decimal("0")) == []


def test_stock_check_uses_generic_module_contract_without_core_frontend_branch():
    root = Path(__file__).resolve().parents[1]
    for name in ("system-findings-banner.js", "system-findings-notifications.js"):
        text = (root / "app/core/frontend/js" / name).read_text(encoding="utf-8")
        assert CHECK_ID not in text


def test_stock_check_emits_actionable_finding_for_drift(db):
    org = OrganisationFactory()
    db.flush()
    item = InventoryRepository(db).create_inventory_item(
        org.id, name="Audit bottle", quantity="2", unit="bottles", inventory_type="final_product", commit=False
    )
    db.flush()
    # Simulate an authorized quantity write whose audit event went missing.
    with allow_inventory_quantity_write(InventoryQuantityWriteReason.REPOSITORY_UPDATE):
        db.execute(text("UPDATE inventory_items SET quantity = 3 WHERE id = :id"), {"id": item.id})
    db.expire(item)

    result = run_stock_integrity_check(org.id, db)

    assert result.flagged
    assert result.data["system_finding"]["action"]["href"].startswith("/")
    alerts = result.data["system_alerts"]
    assert any(a["id"] == f"stock:{item.id}:balance_mismatch" for a in alerts)
    assert all(a["href"].startswith("/") and a["action_label"] for a in alerts)
