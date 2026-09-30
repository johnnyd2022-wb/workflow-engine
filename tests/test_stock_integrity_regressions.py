"""Plan 5.2: stock arithmetic stays exact and tenant findings cannot leak."""

from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.core.db.repositories.inventory_repo import InventoryRepository
from app.core.domain.inventory_quantity_guard import InventoryQuantityWriteReason, allow_inventory_quantity_write
from app.features.inventory.checks.stock_integrity import _lot_balance, run_stock_integrity_check
from tests.factories import OrganisationFactory


def _event(kind, payload, diff=None):
    return SimpleNamespace(event_type=kind, payload=payload, diff=diff)


@pytest.mark.parametrize("unit", ["bottles", "cans", "kegs", "cases", "L", "kg"])
def test_produced_sold_used_wasted_adjusted_and_reversed_balance(unit):
    events = [
        _event("inventory_item.created", {"quantity": "50"}),
        _event("inventory_item.quantity_adjusted", {"delta": "-10", "reason": "sales_fifo_consumption"}),
        _event("inventory_item.quantity_adjusted", {"delta": "3", "reason": "sales_fifo_reversal"}),
        _event("inventory_item.consumed", {"quantity_consumed": "2", "unit": unit}),
        _event("inventory_item.updated", {}, {"quantity": {"before": "41", "after": "42"}}),
    ]
    item = SimpleNamespace(quantity=Decimal("39"), unit=unit)
    assert _lot_balance(item, events, Decimal("3"), Decimal("7")) == []


@pytest.mark.parametrize("qty", ["NaN", "Infinity", "-Infinity", "not a quantity"])
def test_invalid_on_hand_is_a_finding(qty):
    assert _lot_balance(SimpleNamespace(quantity=qty, unit="L"), [], Decimal(0), Decimal(0))[0][0] == "invalid_quantity"


@pytest.mark.parametrize("unit", ["bottles", "cans", "kegs", "cases"])
def test_small_fractional_count_is_never_rounded_away(unit):
    qty = Decimal("1.0001")
    issues = _lot_balance(
        SimpleNamespace(quantity=qty, unit=unit),
        [_event("inventory_item.created", {"quantity": str(qty)})],
        Decimal(0),
        Decimal(0),
    )
    assert {code for code, _ in issues} == {"fractional_count"}


@pytest.mark.parametrize(
    "payload", [{"quantity_consumed": "bad"}, {"quantity_consumed": "-1"}, {"quantity_consumed": "1", "unit": "kg"}]
)
def test_invalid_consumption_history_is_reported(payload):
    events = [_event("inventory_item.created", {"quantity": "10"}), _event("inventory_item.consumed", payload)]
    issues = _lot_balance(SimpleNamespace(quantity=Decimal(10), unit="L"), events, Decimal(0), Decimal(0))
    assert "invalid_history" in {code for code, _ in issues}


def test_healthy_tenant_does_not_inherit_another_tenants_drift(db):
    healthy_org, drift_org = OrganisationFactory(), OrganisationFactory()
    db.flush()
    repo = InventoryRepository(db)
    healthy = repo.create_inventory_item(healthy_org.id, "Same product", "10", "bottles", "final_product", commit=False)
    drift = repo.create_inventory_item(drift_org.id, "Same product", "10", "bottles", "final_product", commit=False)
    db.flush()
    with allow_inventory_quantity_write(InventoryQuantityWriteReason.REPOSITORY_UPDATE):
        db.execute(text("UPDATE inventory_items SET quantity = 9 WHERE id = :id"), {"id": drift.id})
    db.expire_all()
    bad = run_stock_integrity_check(drift_org.id, db)
    good = run_stock_integrity_check(healthy_org.id, db)
    assert bad.flagged
    assert not good.flagged
    assert any(alert["id"] == f"stock:{drift.id}:balance_mismatch" for alert in bad.data["system_alerts"])
    assert all(str(healthy.id) not in alert["id"] for alert in bad.data["system_alerts"])
