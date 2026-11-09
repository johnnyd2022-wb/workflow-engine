"""Stock on hand and output already planned for one product, as engine supplies (GL-P07 B3).

Netting and the stock-cover forecast both read stock through here, so they agree on what
counts: stock of exactly that workflow output, at the planning site, owned by the same party,
not expired, not under an open quality hold (lot_holds) or flagged on hold / quarantined / in
transit, less what an unfinished batch has
already recorded using. Planned output is every live batch of that output at that site.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy import String as SAString
from sqlalchemy import cast, or_

from app.core.db.models.execution import Execution, ExecutionStatus
from app.core.db.models.inventory_item import InventoryItem
from app.core.utils.unit_conversion import convert_quantity_decimal
from app.features.planning.batch_models import PlanningBatch
from app.features.planning.engine import StockKey, Supply
from app.features.planning.models import PlanningDemand

HOLD_FLAGS = ("on_hold", "quarantined", "in_transit")
LIVE_EXECUTION = (ExecutionStatus.PENDING, ExecutionStatus.IN_PROGRESS)


def stock_key(output_id, unit, site, owner_id=None) -> StockKey:
    return StockKey(str(output_id), unit, str(site.id) if site else None, str(owner_id) if owner_id else None)


def _at_site(column, site):
    """A single-site business keeps NULL sites; with sites on, default-site rows were backfilled,
    but a NULL row is still treated as the default site's rather than dropped."""
    if site is None:
        return column.is_(None)
    if site.is_default:
        return or_(column == site.id, column.is_(None))
    return column == site.id


def _held(item) -> bool:
    extra = item.extra_data
    if extra is None:
        return False
    if not isinstance(extra, dict):
        return True
    return any(extra.get(flag) for flag in HOLD_FLAGS) or "contract_customer_id" in extra


def demand_owners(db, org_id: UUID, demands) -> dict[UUID, UUID | None]:
    """Who the stock for each demand belongs to: a contract order's customer, otherwise the
    producer (None). Contract demand is never met from the producer's own stock."""
    from app.features.contract_manufacturing.models.orders import ContractOrder, ContractOrderLine

    refs = {row.source_ref for row in demands if row.source == "contract" and row.source_ref}
    customers = {}
    if refs:
        customers = dict(
            db.query(cast(ContractOrderLine.id, SAString), ContractOrder.customer_id)
            .join(
                ContractOrder,
                (ContractOrder.org_id == ContractOrderLine.org_id) & (ContractOrder.id == ContractOrderLine.order_id),
            )
            .filter(ContractOrderLine.org_id == org_id, cast(ContractOrderLine.id, SAString).in_(refs))
            .all()
        )
    return {row.id: customers.get(row.source_ref) if row.source == "contract" else None for row in demands}


def on_hand(db, org_id: UUID, output_id: UUID, unit: str, site, owner_id, *, today: date):
    """(supplies, reasons). Each lot is one supply, ready today, expiring on its expiry date."""
    from app.core.services.lot_holds import held_lot_ids_subquery
    from app.features.planning.material_adapter import _pending_inputs

    query = db.query(InventoryItem).filter(
        InventoryItem.org_id == org_id,
        InventoryItem.source_output_id == output_id,
        InventoryItem.quantity > 0,
        _at_site(InventoryItem.site_id, site),
        # A lot under a quality hold (GL-P02) can't be sold or used until it is released.
        InventoryItem.id.notin_(held_lot_ids_subquery(org_id)),
    )
    query = query.filter(
        InventoryItem.contract_customer_id == owner_id
        if owner_id is not None
        else InventoryItem.contract_customer_id.is_(None)
    )
    items = query.order_by(InventoryItem.id).all()
    pending = _pending_inputs(db, org_id, [item.id for item in items])
    key = stock_key(output_id, unit, site, owner_id)
    supplies, reasons = [], []
    for item in items:
        if _held(item) or (item.expiry_date is not None and item.expiry_date < today):
            continue
        try:
            quantity = convert_quantity_decimal(Decimal(item.quantity), item.unit, unit)
            for used, used_unit in pending.get(str(item.id), ()):
                quantity -= convert_quantity_decimal(Decimal(str(used)), used_unit, unit)
        except (TypeError, ValueError, InvalidOperation):
            reasons.append(f"{item.name} is recorded in {item.unit}, which can't be counted as {unit}")
            continue
        if quantity > 0:
            supplies.append(Supply(f"lot:{item.id}", key, quantity, today, item.expiry_date))
    return supplies, list(dict.fromkeys(reasons))


def planned_output(
    db,
    org_id: UUID,
    output_id: UUID,
    unit: str,
    site,
    owner_id,
    *,
    today: date,
    exclude_demand_ids=(),
    sources=("manual", "contract", "forecast"),
):
    """Live batches of this output at this site: not started yet, or started and still being
    made (their output isn't in stock yet). Each is a supply on its ready date."""
    rows = (
        db.query(PlanningBatch, PlanningDemand)
        .join(
            PlanningDemand,
            (PlanningDemand.org_id == PlanningBatch.org_id) & (PlanningDemand.id == PlanningBatch.demand_id),
        )
        .outerjoin(Execution, (Execution.org_id == PlanningBatch.org_id) & (Execution.id == PlanningBatch.execution_id))
        .filter(
            PlanningBatch.org_id == org_id,
            PlanningBatch.source_output_id == output_id,
            PlanningBatch.unit == unit,
            PlanningBatch.site_id.is_(None) if site is None else PlanningBatch.site_id == site.id,
            or_(
                PlanningBatch.status.in_(("blocked", "planned")),
                (PlanningBatch.status == "started") & Execution.status.in_(LIVE_EXECUTION),
            ),
            PlanningDemand.source.in_(sources),
            PlanningDemand.status == "open",
        )
        .order_by(PlanningBatch.proposed_start_date, PlanningBatch.id)
        .all()
    )
    rows = [(batch, demand) for batch, demand in rows if demand.id not in set(exclude_demand_ids)]
    owners = demand_owners(db, org_id, [demand for _, demand in rows])
    key = stock_key(output_id, unit, site, owner_id)
    supplies = []
    for batch, demand in rows:
        if owners.get(demand.id) != owner_id:
            continue
        ready = batch.theoretical_ready_date or batch.proposed_start_date + timedelta(
            days=int(batch.snapshot.get("elapsed_days") or 0)
        )
        use_by = batch.snapshot.get("use_by_date")
        expiry = date.fromisoformat(use_by) if use_by else None
        if expiry is not None and expiry < max(ready, today):
            continue
        supplies.append(Supply(f"batch:{batch.id}", key, batch.quantity, max(ready, today), expiry))
    return supplies
