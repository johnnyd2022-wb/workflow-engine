"""Nightly stock arithmetic and sales matching checks (source-to-sale 1.7)."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.db.models.entity_event import EntityEvent
from app.core.db.models.inventory_item import InventoryItem
from app.core.db.models.inventory_movement import InventoryMovement, InventoryMovementType
from app.core.db.models.organisation import Organisation
from app.core.utils.unit_conversion import is_count_unit
from app.features.compliance_checks.routes.corechecks import CheckResult
from app.features.crm.models.sales_fifo_allocation import SalesFifoAllocation
from app.features.crm.services.sales_traceability_service import SalesTraceabilityService

CHECK_ID = "inventory.stock_integrity"
_SALES_REASONS = frozenset({"sales_fifo_consumption", "sales_manual_allocation", "sales_fifo_reversal"})


def _decimal(value) -> Decimal | None:
    try:
        number = Decimal(str(value))
        return number if number.is_finite() else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def _lot_balance(item, events, wasted: Decimal, allocated: Decimal) -> list[tuple[str, str]]:
    """Return stable issue codes and explanations for one lot's stock arithmetic."""
    issues = []
    on_hand = _decimal(item.quantity)
    if on_hand is None:
        return [("invalid_quantity", "The on-hand quantity is invalid; correct this lot in Live Inventory.")]
    if is_count_unit(item.unit) and on_hand != on_hand.to_integral_value():
        issues.append(("fractional_count", f"{on_hand} {item.unit} on hand; counted goods must be whole."))

    produced = sold = adjusted = Decimal(0)
    baseline_found = False
    for event in events:
        payload = event.payload or {}
        if event.event_type == "inventory_item.created":
            baseline = _decimal(payload.get("quantity"))
            if baseline is None:
                issues.append(("invalid_history", "The lot's opening quantity is invalid."))
            else:
                produced = baseline
                baseline_found = True
        elif event.event_type == "inventory_item.quantity_adjusted":
            delta = _decimal(payload.get("delta"))
            if delta is None:
                issues.append(("invalid_history", "A stock change has no valid quantity."))
            elif payload.get("reason") in _SALES_REASONS:
                sold -= delta
            else:
                adjusted += delta
        elif event.event_type == "inventory_item.updated":
            change = (event.diff or {}).get("quantity") or {}
            if change:
                before = _decimal(change.get("before"))
                after = _decimal(change.get("after"))
                if before is None or after is None:
                    issues.append(("invalid_history", "A stock edit has no valid before and after quantities."))
                else:
                    adjusted += after - before

    if not baseline_found:
        issues.append(("missing_history", "This lot has no opening or production stock event."))
    elif not any(code == "invalid_history" for code, _ in issues):
        expected = produced - sold - wasted + adjusted
        if expected != on_hand:
            issues.append(
                (
                    "balance_mismatch",
                    f"Produced/opening {produced} − sold {sold} − wasted {wasted} "
                    f"+ adjusted {adjusted} = {expected} {item.unit}; on hand is {on_hand} {item.unit}.",
                )
            )
    if sold != allocated:
        issues.append(
            (
                "sale_allocation_mismatch",
                f"Stock history records {sold} {item.unit} sold, but active sale allocations total "
                f"{allocated} {item.unit}.",
            )
        )
    return issues


def _events_by_lot(org_id: UUID, session: Session):
    events_by_item = defaultdict(list)
    events = (
        session.query(EntityEvent)
        .filter(
            EntityEvent.org_id == org_id,
            EntityEvent.entity_type == "inventory_item",
            EntityEvent.event_type.in_(
                ("inventory_item.created", "inventory_item.quantity_adjusted", "inventory_item.updated")
            ),
        )
        .order_by(EntityEvent.seq)
        .all()
    )
    for event in events:
        events_by_item[event.entity_id].append(event)
    return events_by_item


def _wastage_by_lot(org_id: UUID, session: Session):
    wasted_by_item = defaultdict(Decimal)
    movements = (
        session.query(InventoryMovement.inventory_item_id, InventoryMovement.quantity)
        .filter(
            InventoryMovement.org_id == org_id,
            InventoryMovement.movement_type == InventoryMovementType.WASTAGE.value,
        )
        .all()
    )
    for item_id, quantity in movements:
        amount = _decimal(quantity)
        if amount is not None:
            wasted_by_item[item_id] -= amount  # signed movement
    return wasted_by_item


def _allocations_by_lot(org_id: UUID, session: Session):
    allocated_by_item = defaultdict(Decimal)
    allocations = (
        session.query(SalesFifoAllocation.inventory_item_id, SalesFifoAllocation.quantity)
        .filter(SalesFifoAllocation.org_id == org_id)
        .all()
    )
    for item_id, quantity in allocations:
        amount = _decimal(quantity)
        if amount is not None:
            allocated_by_item[item_id] += amount
    return allocated_by_item


def run_stock_integrity_check(org_id: UUID, session: Session) -> CheckResult:
    """Audit every current lot and give each failure a stable operator action."""
    items = session.query(InventoryItem).filter(InventoryItem.org_id == org_id).all()
    events_by_item = _events_by_lot(org_id, session)
    wasted_by_item = _wastage_by_lot(org_id, session)
    allocated_by_item = _allocations_by_lot(org_id, session)

    alerts = []
    for item in items:
        lot = item.supplier_batch_number or (item.extra_data or {}).get("batch_number") or str(item.id)[:8]
        for code, description in _lot_balance(
            item, events_by_item[item.id], wasted_by_item[item.id], allocated_by_item[item.id]
        ):
            alerts.append(
                {
                    "id": f"stock:{item.id}:{code}",
                    "title": f"{item.name} · lot {lot}: stock needs checking",
                    "description": description,
                    "href": "/core?tab=inventory",
                    "action_label": "Review stock",
                }
            )

    org = session.get(Organisation, org_id)
    if org is not None and org.go_live_date is not None:
        service = SalesTraceabilityService(session)
        for line in service._unmatched_sales_lines(org_id, limit=1_000_000):
            reason = line.get("reason")
            alerts.append(
                {
                    "id": f"sale:{line['invoice_id']}:{line['line_key']}",
                    "title": f"Sale {line.get('invoice_number') or line['invoice_id']} needs a batch match",
                    "description": f"Reason: {reason or 'missing reason'}. Match or correct this sale line.",
                    "href": "/crm/matching",
                    "action_label": "Review sale",
                }
            )

    flagged = bool(alerts)
    return CheckResult(
        check_id=CHECK_ID,
        flagged=flagged,
        message=f"{len(alerts)} stock or sales integrity issue{'s' if len(alerts) != 1 else ''}" if flagged else None,
        data={
            "system_finding": {
                "category": "Stock integrity",
                "action": {"href": "/core/notifications", "label": "Review findings"},
                "details": alerts[:10],
            },
            "system_alerts": alerts,
        },
    )
