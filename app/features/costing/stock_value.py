"""Stock value and snapshots (live-cogs 8.1g; spec "8.1g build contract").

Stock value is on-hand quantity × the engine's unit cost per lot, plus the unabsorbed pool of every
batch still running. A snapshot freezes that at a cutoff and, when an earlier snapshot exists,
values what moved between the two (``stock_value_movements``) so the bridge to Xero can explain
the difference exactly. Nothing stored here is ever updated.

Unknown cost is never $0: a lot with no cost is listed with no value and counted; a partly costed
lot carries its floor and is labelled ``partial``.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy import func, or_, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db.models.entity_event import EntityEvent
from app.core.db.models.execution import Execution, ExecutionStatus
from app.core.db.models.inventory_item import InventoryItem, InventoryType
from app.core.db.models.inventory_movement import InventoryMovement, InventoryMovementType
from app.core.db.models.process import Process
from app.core.utils.time import utc_now
from app.core.utils.unit_conversion import convert_to_inventory_unit_decimal
from app.features.costing import FEATURE_KEY, purchase_sources
from app.features.costing.engine import (
    ACTUAL,
    ESTIMATED,
    PARTIAL,
    UNKNOWN,
    CostEngine,
    TooLargeError,
    money,
    qty,
    unit_str,
    worst,
)
from app.features.costing.models import (
    CostFlow,
    CostingSettings,
    PurchaseAllocation,
    PurchaseDocument,
    PurchaseLine,
    StockValueLine,
    StockValueMovement,
    StockValueSnapshot,
)
from app.features.costing.service import CostingError, CostingNotFoundError
from app.observability import get_logger

logger = get_logger(__name__)

ZERO = Decimal("0")
MONEY = Decimal("0.0001")
UNIT = Decimal("0.000001")
MAX_MANUAL_PER_DAY = 20
MAX_MONTHS_CATCH_UP = 12
CATEGORIES = ("raw", "in_production", "wip", "finished")
CATEGORY_LABELS = {
    "raw": "Raw materials",
    "wip": "Work in progress",
    "finished": "Finished goods",
    "in_production": "In production",
}
_CATEGORY_OF = {
    InventoryType.RAW_MATERIAL.value: "raw",
    InventoryType.WORK_IN_PROGRESS.value: "wip",
    InventoryType.FINAL_PRODUCT.value: "finished",
}
_SALES_REASONS = frozenset({"sales_fifo_consumption", "sales_manual_allocation", "sales_fifo_reversal"})
_TRANSFER_REASONS = frozenset({"site_transfer_dispatch", "stock_transfer"})
_EVENT_TYPES = (
    "inventory_item.created",
    "inventory_item.quantity_adjusted",
    "inventory_item.consumed",
    "inventory_item.updated",
)
_ADD_REASON = "repository_add_quantity"
_ACTIVE_STATUSES = (ExecutionStatus.PENDING, ExecutionStatus.IN_PROGRESS)


class StockValueError(CostingError):
    """The snapshot can't be taken or read as asked (400)."""


def _d(value) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return ZERO
    return number if number.is_finite() else ZERO


def q4(value: Decimal) -> Decimal:
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)


def month_end_cutoff(as_of: date) -> datetime:
    """00:00 NZ on the day after ``as_of``, in UTC: an event before it is inside the month."""
    return datetime.combine(as_of + timedelta(days=1), time.min, tzinfo=purchase_sources.NZ).astimezone(UTC)


def last_day_before_month(day: date) -> date:
    return day.replace(day=1) - timedelta(days=1)


def nz_date_of(moment: datetime) -> date:
    return moment.astimezone(purchase_sources.NZ).date()


# --- lines and totals ------------------------------------------------------------------------------


@dataclass
class Line:
    kind: str  # lot | in_production
    category: str
    name: str
    unit: str | None
    batch: str | None
    quantity: Decimal
    unit_cost: Decimal | None
    known_unit_cost: Decimal | None
    value: Decimal | None
    status: str
    item_id: UUID | None = None
    execution_id: UUID | None = None


@dataclass
class Valuation:
    cutoff_at: datetime | None
    lines: list[Line] = field(default_factory=list)
    basis: str = "exact"
    quantities: dict = field(default_factory=dict)  # lot id -> quantity at the cutoff (every lot with any)
    pricer: _Pricer | None = None

    def totals(self) -> dict:
        return totals_of(self.lines)


def totals_of(lines) -> dict:
    """Totals over ``Line``-like rows (anything with kind, category, status, value)."""
    out = {
        "total": ZERO,
        "categories": {c: {"value": ZERO, "lots": 0} for c in CATEGORIES},
        "split": {"actual": ZERO, "estimated": ZERO, "partial": ZERO},
        "unknown_lots": 0,
        "partial_lots": 0,
        "lot_count": 0,
    }
    for line in lines:
        value = line.value
        if value is not None:
            out["total"] += value
            out["categories"][line.category]["value"] += value
            bucket = line.status if line.status in out["split"] else "partial"
            out["split"][bucket] += value
        if line.kind == "lot":
            out["lot_count"] += 1
            out["categories"][line.category]["lots"] += 1
        if line.status == UNKNOWN:
            out["unknown_lots"] += 1
        elif line.status == PARTIAL:
            out["partial_lots"] += 1
    out["complete"] = out["unknown_lots"] == 0 and out["partial_lots"] == 0
    return out


# --- pricing ----------------------------------------------------------------------------------------


class _Pricer:
    """Unit costs and batch pools from one engine, so a snapshot prices every lot once."""

    def __init__(self, db: Session, org_id: UUID, item_ids=()):
        self.db, self.org_id = db, org_id
        self.engine = CostEngine(db, org_id)
        ids = set(item_ids)
        if ids:
            try:
                self.engine.prime(ids)
            except TooLargeError:
                self.engine = CostEngine(db, org_id)  # price lot by lot; an over-budget lot reads unknown
        self._lots: dict[UUID, tuple[Decimal | None, str]] = {}

    def lot(self, item_id: UUID) -> tuple[Decimal | None, str]:
        """(floor unit cost or None, status)."""
        if item_id not in self._lots:
            try:
                cost = self.engine._solve(("lot", item_id))
            except TooLargeError:
                self._lots[item_id] = (None, UNKNOWN)
            else:
                self._lots[item_id] = (cost.unit_known, cost.status)
        return self._lots[item_id]

    def pool(self, execution_id: UUID, cutoff_at: datetime | None) -> tuple[Decimal, str]:
        """What the batch has consumed and not yet handed to an output, as at ``cutoff_at``
        (None: all of it), at today's lot costs."""
        engine = self.engine
        try:
            info = engine._info(execution_id)
            if info is None:
                return ZERO, ACTUAL
            known, status = ZERO, ACTUAL
            for position in range(len(info.steps)):
                step = engine._solve(("step", execution_id, position))
                for flow in info.consumed.get(position, []):
                    if cutoff_at is not None and flow.created_at >= cutoff_at:
                        continue
                    unit, lot_status = self.lot(flow.inventory_item_id)
                    status = worst(status, PARTIAL if lot_status == UNKNOWN else lot_status)
                    if unit is not None:
                        known += _d(flow.quantity) * unit
                for flow in info.outs.get(position, []):
                    if cutoff_at is not None and flow.created_at >= cutoff_at:
                        continue
                    allocation = step.alloc.get(flow.id)
                    if allocation is not None:
                        known -= allocation.known
            return known, status
        except TooLargeError:
            return ZERO, PARTIAL


# --- as at a cutoff -----------------------------------------------------------------------------------


def _events_since(db: Session, org_id: UUID, since: datetime) -> list[EntityEvent]:
    return (
        db.query(EntityEvent)
        .filter(
            EntityEvent.org_id == org_id,
            EntityEvent.entity_type == "inventory_item",
            EntityEvent.event_type.in_(_EVENT_TYPES),
            EntityEvent.created_at >= since,
        )
        .order_by(EntityEvent.seq)
        .all()
    )


def _wastage_since(db: Session, org_id: UUID, since: datetime) -> list[InventoryMovement]:
    return (
        db.query(InventoryMovement)
        .filter(
            InventoryMovement.org_id == org_id,
            InventoryMovement.movement_type == InventoryMovementType.WASTAGE.value,
            InventoryMovement.created_at >= since,
        )
        .all()
    )


def _quantities_as_of(db: Session, org_id: UUID, cutoff_at: datetime | None, items: dict[UUID, InventoryItem]):
    """Quantity of every lot at the cutoff: now, with every later movement reversed out (the
    arithmetic of the nightly stock-integrity check). Returns (quantities, basis)."""
    now = {item_id: _d(item.quantity) for item_id, item in items.items()}
    if cutoff_at is None:
        return now, "exact"
    events = _events_since(db, org_id, cutoff_at)
    wastage = _wastage_since(db, org_id, cutoff_at)
    if not events and not wastage:
        return now, "exact"
    delta: dict[UUID, Decimal] = defaultdict(lambda: ZERO)  # net change since the cutoff
    born_after: set[UUID] = set()
    for event in events:
        item = items.get(event.entity_id)
        if item is None:
            continue
        payload = event.payload or {}
        if event.event_type == "inventory_item.created":
            born_after.add(item.id)
        elif event.event_type == "inventory_item.quantity_adjusted":
            delta[item.id] += _d(payload.get("delta"))
        elif event.event_type == "inventory_item.consumed":
            used = _d(payload.get("quantity_consumed"))
            try:
                used = convert_to_inventory_unit_decimal(used, payload.get("unit") or item.unit, item.unit)
            except (ValueError, InvalidOperation, TypeError):
                pass
            delta[item.id] -= used
        elif event.event_type == "inventory_item.updated":
            change = (event.diff or {}).get("quantity") or {}
            if change:
                delta[item.id] += _d(change.get("after")) - _d(change.get("before"))
    for movement in wastage:
        if movement.inventory_item_id in items:
            delta[movement.inventory_item_id] += _d(movement.quantity)  # signed: wastage is negative
    out = {}
    for item_id, current in now.items():
        if item_id in born_after:
            out[item_id] = ZERO
        else:
            out[item_id] = max(current - delta.get(item_id, ZERO), ZERO)
    return out, "reconstructed"


def _lots(db: Session, org_id: UUID) -> dict[UUID, InventoryItem]:
    """Every producer-owned lot. Customer-owned stock is never the org's to value."""
    return {
        item.id: item
        for item in db.query(InventoryItem).filter(
            InventoryItem.org_id == org_id, InventoryItem.contract_customer_id.is_(None)
        )
    }


def _in_progress(db: Session, org_id: UUID, cutoff_at: datetime | None) -> list[Execution]:
    """Batches running at the cutoff: started before it and not ended by it."""
    query = db.query(Execution).filter(Execution.org_id == org_id)
    if cutoff_at is None:
        return query.filter(Execution.status.in_(_ACTIVE_STATUSES)).all()
    ended = func.coalesce(Execution.completed_at, Execution.updated_at)
    return query.filter(
        Execution.started_at < cutoff_at,
        or_(Execution.status.in_(_ACTIVE_STATUSES), ended >= cutoff_at),
    ).all()


def value_stock(db: Session, org_id: UUID, cutoff_at: datetime | None = None, *, extra_ids=()) -> Valuation:
    """Stock value at ``cutoff_at`` (None: now). ``extra_ids``: lots to price as well (a window's)."""
    items = _lots(db, org_id)
    quantities, basis = _quantities_as_of(db, org_id, cutoff_at, items)
    held = [item for item in items.values() if quantities.get(item.id, ZERO) > 0]
    executions = _in_progress(db, org_id, cutoff_at)
    pricer = _Pricer(db, org_id, {i.id for i in held} | set(extra_ids))
    lines: list[Line] = []
    for item in sorted(held, key=lambda i: (i.name.casefold(), str(i.id))):
        quantity = quantities[item.id]
        known, status = pricer.lot(item.id)
        value = None if known is None else q4(quantity * known)
        lines.append(
            Line(
                kind="lot",
                category=_CATEGORY_OF.get(item.inventory_type, "raw"),
                name=item.name,
                unit=item.unit,
                batch=item.supplier_batch_number or (item.extra_data or {}).get("batch_number"),
                quantity=quantity,
                unit_cost=known if status in (ACTUAL, ESTIMATED) else None,
                known_unit_cost=known,
                value=value,
                status=status if status in (ACTUAL, ESTIMATED, PARTIAL) else UNKNOWN,
                item_id=item.id,
            )
        )
    names = {}
    if executions:
        names = {
            row.id: row.name
            for row in db.query(Process.id, Process.name).filter(
                Process.org_id == org_id, Process.id.in_({e.process_id for e in executions})
            )
        }
    for execution in sorted(executions, key=lambda e: (e.started_at, str(e.id))):
        known, status = pricer.pool(execution.id, cutoff_at)
        if known == ZERO and status == ACTUAL:
            continue
        lines.append(
            Line(
                kind="in_production",
                category="in_production",
                name=names.get(execution.process_id) or "Batch in progress",
                unit=None,
                batch=nz_date_of(execution.started_at).isoformat() if execution.started_at else None,
                quantity=ZERO,
                unit_cost=None,
                known_unit_cost=None,
                value=q4(max(known, ZERO)),
                status=status,
                execution_id=execution.id,
            )
        )
    return Valuation(cutoff_at=cutoff_at, lines=lines, basis=basis, quantities=quantities, pricer=pricer)


# --- payloads ----------------------------------------------------------------------------------------


def _line_payload(line) -> dict:
    return {
        "kind": line.kind,
        "inventory_item_id": str(line.item_id) if line.item_id else None,
        "execution_id": str(line.execution_id) if line.execution_id else None,
        "name": line.name,
        "category": line.category,
        "batch": line.batch,
        "unit": line.unit,
        "quantity": qty(line.quantity),
        "unit_cost": unit_str(line.unit_cost),
        "known_unit_cost": unit_str(line.known_unit_cost),
        "value": money(line.value),
        "status": line.status,
    }


def _totals_payload(totals: dict) -> dict:
    return {
        "total": money(totals["total"]),
        "complete": totals["complete"],
        "unknown_lots": totals["unknown_lots"],
        "partial_lots": totals["partial_lots"],
        "lot_count": totals["lot_count"],
        "categories": {c: {"value": money(v["value"]), "lots": v["lots"]} for c, v in totals["categories"].items()},
        "split": {k: money(v) for k, v in totals["split"].items()},
    }


def current_payload(db: Session, org_id: UUID, *, auto: list | None = None) -> dict:
    valuation = value_stock(db, org_id)
    body = {
        "as_of": utc_now().isoformat(),
        "currency": _currency(db, org_id),
        **_totals_payload(valuation.totals()),
        "lines": [_line_payload(line) for line in valuation.lines],
    }
    if auto:
        body["auto_snapshots"] = [str(s.id) for s in auto]
    return body


def _currency(db: Session, org_id: UUID) -> str:
    settings = db.query(CostingSettings).filter(CostingSettings.org_id == org_id).one_or_none()
    return (settings.base_currency if settings and settings.base_currency else "NZD").upper()


def snapshot_header(snapshot: StockValueSnapshot) -> dict:
    complete = snapshot.unknown_lots == 0 and snapshot.partial_lots == 0
    return {
        "id": str(snapshot.id),
        "kind": snapshot.kind,
        "as_of_date": snapshot.as_of_date.isoformat(),
        "cutoff_at": snapshot.cutoff_at.isoformat(),
        "taken_at": snapshot.taken_at.isoformat() if snapshot.taken_at else None,
        "trigger": snapshot.trigger,
        "automatic": snapshot.taken_by_user_id is None,
        "quantity_basis": snapshot.quantity_basis,
        "previous_id": str(snapshot.previous_snapshot_id) if snapshot.previous_snapshot_id else None,
        "currency": snapshot.currency,
        "total": money(_d(snapshot.total_value)),
        "complete": complete,
        "unknown_lots": snapshot.unknown_lots,
        "partial_lots": snapshot.partial_lots,
        "lot_count": snapshot.lot_count,
        "categories": {
            "raw": {"value": money(_d(snapshot.raw_value))},
            "in_production": {"value": money(_d(snapshot.in_production_value))},
            "wip": {"value": money(_d(snapshot.wip_value))},
            "finished": {"value": money(_d(snapshot.finished_value))},
        },
        "split": {
            "actual": money(_d(snapshot.actual_value)),
            "estimated": money(_d(snapshot.estimated_value)),
            "partial": money(_d(snapshot.partial_value)),
        },
    }


def stored_lines(db: Session, org_id: UUID, snapshot_id: UUID) -> list[StockValueLine]:
    return (
        db.query(StockValueLine)
        .filter(StockValueLine.org_id == org_id, StockValueLine.snapshot_id == snapshot_id)
        .order_by(StockValueLine.category, StockValueLine.name, StockValueLine.id)
        .all()
    )


def snapshot_payload(db: Session, org_id: UUID, snapshot: StockValueSnapshot, *, detail: bool = False) -> dict:
    body = snapshot_header(snapshot)
    if detail:
        lines = stored_lines(db, org_id, snapshot.id)
        body["lines"] = [_line_payload(_StoredLine(row)) for row in lines]
        body["changes_since_close"] = changes_since_close(db, org_id, snapshot, lines)
    return body


class _StoredLine:
    """A stored line shaped like ``Line``."""

    def __init__(self, row: StockValueLine):
        self.kind = row.line_type
        self.category = row.category
        self.name = row.name
        self.unit = row.unit
        self.batch = row.batch
        self.quantity = _d(row.quantity)
        self.unit_cost = None if row.unit_cost is None else _d(row.unit_cost)
        self.known_unit_cost = None if row.known_unit_cost is None else _d(row.known_unit_cost)
        self.value = None if row.value is None else _d(row.value)
        self.status = row.status
        self.item_id = row.inventory_item_id
        self.execution_id = row.execution_id


def get_snapshot(db: Session, org_id: UUID, snapshot_id) -> StockValueSnapshot:
    try:
        wanted = UUID(str(snapshot_id))
    except (ValueError, TypeError, AttributeError):
        raise CostingNotFoundError("Snapshot not found") from None
    snapshot = (
        db.query(StockValueSnapshot)
        .filter(StockValueSnapshot.org_id == org_id, StockValueSnapshot.id == wanted)
        .one_or_none()
    )
    if snapshot is None:
        raise CostingNotFoundError("Snapshot not found")
    return snapshot


def list_snapshots(db: Session, org_id: UUID) -> list[StockValueSnapshot]:
    return (
        db.query(StockValueSnapshot)
        .filter(StockValueSnapshot.org_id == org_id)
        .order_by(StockValueSnapshot.cutoff_at.desc(), StockValueSnapshot.created_at.desc())
        .all()
    )


# --- changes since close ------------------------------------------------------------------------------


def changes_since_close(db: Session, org_id: UUID, snapshot: StockValueSnapshot, lines=None) -> dict:
    """The stored quantities re-priced with today's costs. Never touches the snapshot."""
    lines = stored_lines(db, org_id, snapshot.id) if lines is None else lines
    lot_ids = {row.inventory_item_id for row in lines if row.inventory_item_id}
    pricer = _Pricer(db, org_id, lot_ids)
    now_total = ZERO
    changed = 0
    for row in lines:
        before = ZERO if row.value is None else _d(row.value)
        if row.line_type == "in_production":
            if row.execution_id is None:
                after = before
            else:
                known, _status = pricer.pool(row.execution_id, snapshot.cutoff_at)
                after = q4(max(known, ZERO))
        elif row.inventory_item_id is None:
            after = before
        else:
            known, _status = pricer.lot(row.inventory_item_id)
            after = ZERO if known is None else q4(_d(row.quantity) * known)
        now_total += after
        if after != before:
            changed += 1
    then = _d(snapshot.total_value)
    out = {
        "total_then": money(then),
        "total_now": money(now_total),
        "delta": money(now_total - then),
        "lines_changed": changed,
    }
    if snapshot.previous_snapshot_id is not None and snapshot.purchases_value is not None:
        previous = get_snapshot(db, org_id, snapshot.previous_snapshot_id)
        purchases_now = purchases_in_period(db, org_id, previous.as_of_date + timedelta(days=1), snapshot.as_of_date)
        purchases_then = _d(snapshot.purchases_value)
        out["purchases_then"] = money(purchases_then)
        out["purchases_now"] = money(purchases_now)
        out["purchases_delta"] = money(purchases_now - purchases_then)
    return out


# --- purchases recorded into stock ---------------------------------------------------------------------


def purchase_allocations(db: Session, org_id: UUID, start: date, end: date):
    """(allocation, line, document) for every active or orphaned allocation on a line dated in
    [start, end] — refunds negative."""
    return (
        db.query(PurchaseAllocation, PurchaseLine, PurchaseDocument)
        .join(
            PurchaseLine,
            (PurchaseLine.org_id == PurchaseAllocation.org_id)
            & (PurchaseLine.id == PurchaseAllocation.purchase_line_id),
        )
        .join(
            PurchaseDocument,
            (PurchaseDocument.org_id == PurchaseLine.org_id) & (PurchaseDocument.id == PurchaseLine.document_id),
        )
        .filter(
            PurchaseAllocation.org_id == org_id,
            PurchaseAllocation.status.in_(("active", "orphaned")),
            PurchaseDocument.document_date >= start,
            PurchaseDocument.document_date <= end,
        )
        .all()
    )


def purchases_in_period(db: Session, org_id: UUID, start: date, end: date) -> Decimal:
    return sum((_d(a.amount) for a, _l, _d_ in purchase_allocations(db, org_id, start, end)), ZERO)


# --- the movements between two snapshots -----------------------------------------------------------------


@dataclass
class _Movement:
    kind: str
    value: Decimal
    item_id: UUID | None = None
    execution_id: UUID | None = None
    name: str | None = None
    quantity: Decimal = ZERO
    unit_cost: Decimal | None = None


def _window_flows(db: Session, org_id: UUID, start: datetime, end: datetime) -> dict[UUID, dict[str, Decimal]]:
    """Quantities that came into or went out of each lot in [start, end), from the cost facts
    written live (the backfill's reconstructed rows are history, not movements)."""
    out: dict[UUID, dict[str, Decimal]] = defaultdict(lambda: defaultdict(lambda: ZERO))
    rows = (
        db.query(CostFlow)
        .filter(
            CostFlow.org_id == org_id,
            CostFlow.reconstructed.is_(False),
            CostFlow.created_at >= start,
            CostFlow.created_at < end,
        )
        .all()
    )
    for flow in rows:
        bucket = {
            "created": "direct",
            "added": "direct",
            "produced": "produced",
            "reconciled_in": "produced",
            "transfer_in": "transfer_in",
            "consumed": "consumed",
        }[flow.kind]
        out[flow.inventory_item_id][bucket] += _d(flow.quantity)
    return out


def _window_decreases(db: Session, org_id: UUID, start: datetime, end: datetime) -> dict[UUID, dict[str, Decimal]]:
    """Decreases the ledgers explain, by kind, in [start, end): positive means stock left."""
    out: dict[UUID, dict[str, Decimal]] = defaultdict(lambda: defaultdict(lambda: ZERO))
    for event in _events_since(db, org_id, start):
        if event.created_at >= end:
            continue
        payload = event.payload or {}
        if event.event_type == "inventory_item.quantity_adjusted":
            reason = payload.get("reason")
            if reason == _ADD_REASON:
                continue  # an inflow: it has its own cost flow
            if reason in _SALES_REASONS:
                kind = "sale"
            elif reason == "tasting_dispatch":
                kind = "sample"
            elif reason in _TRANSFER_REASONS:
                kind = "transfer"
            else:
                kind = "variance"
            out[event.entity_id][kind] -= _d(payload.get("delta"))
        elif event.event_type == "inventory_item.updated":
            change = (event.diff or {}).get("quantity") or {}
            if change:
                out[event.entity_id]["variance"] -= _d(change.get("after")) - _d(change.get("before"))
    for movement in _wastage_since(db, org_id, start):
        if movement.created_at < end:
            out[movement.inventory_item_id]["wastage"] -= _d(movement.quantity)
    return out


def compute_movements(
    db: Session,
    org_id: UUID,
    previous: StockValueSnapshot,
    previous_lines: list[StockValueLine],
    current: Valuation,
    start: datetime,
    end: datetime,
    *,
    period_start: date,
    period_end: date,
) -> list[_Movement]:
    """Value what moved between ``previous`` and ``current`` at the closing costs. The rows sum to
    exactly closing minus opening: whatever the independent figures leave over is ``rounding``."""
    opening_qty = {
        r.inventory_item_id: _d(r.quantity) for r in previous_lines if r.line_type == "lot" and r.inventory_item_id
    }
    opening_unit = {
        r.inventory_item_id: ZERO if r.known_unit_cost is None else _d(r.known_unit_cost)
        for r in previous_lines
        if r.line_type == "lot" and r.inventory_item_id
    }
    closing_qty = {ln.item_id: ln.quantity for ln in current.lines if ln.kind == "lot"}
    flows = _window_flows(db, org_id, start, end)
    decreases = _window_decreases(db, org_id, start, end)
    allocations = purchase_allocations(db, org_id, period_start, period_end)
    bought: dict[UUID, Decimal] = defaultdict(lambda: ZERO)
    for allocation, _line, _doc in allocations:
        bought[allocation.inventory_item_id] += _d(allocation.amount)

    lot_ids = set(opening_qty) | set(closing_qty) | set(flows) | set(decreases) | set(bought)
    items = (
        {
            item.id: item
            for item in db.query(InventoryItem).filter(InventoryItem.org_id == org_id, InventoryItem.id.in_(lot_ids))
        }
        if lot_ids
        else {}
    )
    pricer = current.pricer or _Pricer(db, org_id, lot_ids)
    rows: list[_Movement] = []

    def add(kind, value, item=None, quantity=ZERO, unit_cost=None, execution_id=None, name=None):
        value = q4(value)
        if value == ZERO and quantity == ZERO:
            return
        rows.append(
            _Movement(
                kind=kind,
                value=value,
                item_id=item.id if item is not None else None,
                execution_id=execution_id,
                name=name if name is not None else (item.name if item is not None else None),
                quantity=quantity,
                unit_cost=unit_cost,
            )
        )

    for item_id in sorted(lot_ids, key=str):
        item = items.get(item_id)
        if item is None:
            continue
        known, _status = pricer.lot(item_id)
        u1 = ZERO if known is None else known
        q0, q1 = opening_qty.get(item_id, ZERO), closing_qty.get(item_id, ZERO)
        flow = flows.get(item_id, {})
        direct, produced = flow.get("direct", ZERO), flow.get("produced", ZERO)
        moved_in, consumed = flow.get("transfer_in", ZERO), flow.get("consumed", ZERO)
        left = decreases.get(item_id, {})
        explained = sum((left.get(k, ZERO) for k in ("sale", "sample", "wastage", "variance", "transfer")), ZERO)
        unexplained = (q0 + direct + produced + moved_in - consumed - q1) - explained
        for kind in ("sale", "sample", "wastage"):
            if left.get(kind, ZERO):
                add(kind, -left[kind] * u1, item, left[kind], u1)
        variance = left.get("variance", ZERO) + unexplained
        if variance:
            add("variance", -variance * u1, item, variance, u1)
        transfer = moved_in - left.get("transfer", ZERO)
        if transfer:
            add("transfer", transfer * u1, item, transfer, u1)
        reval = q0 * (u1 - opening_unit.get(item_id, ZERO))
        if reval:
            add("revaluation", reval, item, q0, u1)
        paid = bought.get(item_id, ZERO)
        if paid:
            add("purchase", paid, item, ZERO, u1)
        if direct or paid:
            add("added_other", direct * u1 - paid, item, direct, u1)

    # batches: pools carried across the window, and what a finished batch leaves unabsorbed
    open_then = {
        r.execution_id: _d(r.value) for r in previous_lines if r.line_type == "in_production" and r.execution_id
    }
    open_now = {ln.execution_id for ln in current.lines if ln.kind == "in_production"}
    window_executions = {
        row[0]
        for row in db.query(CostFlow.execution_id)
        .filter(
            CostFlow.org_id == org_id,
            CostFlow.execution_id.isnot(None),
            CostFlow.created_at >= start,
            CostFlow.created_at < end,
        )
        .distinct()
    }
    for execution_id in sorted(set(open_then) | open_now | window_executions, key=str):
        pool_then, _ = pricer.pool(execution_id, start)
        pool_now, _ = pricer.pool(execution_id, end)
        was_open, is_open = execution_id in open_then, execution_id in open_now
        if was_open:
            add("revaluation", pool_then - open_then[execution_id], execution_id=execution_id, name="Batch in progress")
        loss = (ZERO if is_open else pool_now) - (ZERO if was_open else pool_then)
        if loss:
            add("production_loss", -loss, execution_id=execution_id, name="Batch")
    return rows


# --- taking a snapshot -----------------------------------------------------------------------------------------


def _lock(db: Session, org_id: UUID) -> None:
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": f"stock_value:{org_id}"})


def _latest(db: Session, org_id: UUID) -> StockValueSnapshot | None:
    return (
        db.query(StockValueSnapshot)
        .filter(StockValueSnapshot.org_id == org_id)
        .order_by(StockValueSnapshot.cutoff_at.desc(), StockValueSnapshot.created_at.desc())
        .first()
    )


def take_snapshot(
    db: Session,
    org_id: UUID,
    *,
    kind: str = "manual",
    trigger: str = "manual",
    cutoff_at: datetime | None = None,
    as_of_date: date | None = None,
    user_id: UUID | None = None,
) -> StockValueSnapshot:
    """Freeze the stock value at ``cutoff_at`` (default: now, or a month end's close). The caller
    commits. Snapshots go in cutoff order: one can't be taken for a time before an earlier one."""
    if kind not in ("month_end", "manual"):
        raise StockValueError("kind must be month_end or manual")
    if kind == "month_end" and as_of_date is None:
        raise StockValueError("A month-end snapshot needs its date")
    _lock(db, org_id)
    cutoff = cutoff_at or (month_end_cutoff(as_of_date) if kind == "month_end" else utc_now())
    as_of = as_of_date or nz_date_of(cutoff)
    taken_at = utc_now()
    if kind == "manual":
        midnight = datetime.combine(nz_date_of(taken_at), time.min, tzinfo=purchase_sources.NZ).astimezone(UTC)
        today_count = (
            db.query(func.count(StockValueSnapshot.id))
            .filter(
                StockValueSnapshot.org_id == org_id,
                StockValueSnapshot.kind == "manual",
                StockValueSnapshot.taken_at >= midnight,
            )
            .scalar()
        )
        if today_count >= MAX_MANUAL_PER_DAY:
            raise StockValueError(f"At most {MAX_MANUAL_PER_DAY} snapshots a day; use one you took earlier today")
    previous = _latest(db, org_id)
    if previous is not None and cutoff < previous.cutoff_at:
        raise StockValueError("A snapshot can't be taken for a time before an earlier one")

    previous_lines = stored_lines(db, org_id, previous.id) if previous is not None else []
    previous_item_ids = {r.inventory_item_id for r in previous_lines if r.inventory_item_id}
    valuation = value_stock(db, org_id, cutoff, extra_ids=previous_item_ids)
    totals = valuation.totals()
    snapshot = StockValueSnapshot(
        org_id=org_id,
        kind=kind,
        as_of_date=as_of,
        cutoff_at=cutoff,
        taken_at=taken_at,
        trigger=trigger,
        taken_by_user_id=user_id,
        previous_snapshot_id=previous.id if previous is not None else None,
        quantity_basis=valuation.basis,
        currency=_currency(db, org_id),
        total_value=q4(totals["total"]),
        raw_value=q4(totals["categories"]["raw"]["value"]),
        in_production_value=q4(totals["categories"]["in_production"]["value"]),
        wip_value=q4(totals["categories"]["wip"]["value"]),
        finished_value=q4(totals["categories"]["finished"]["value"]),
        actual_value=q4(totals["split"]["actual"]),
        estimated_value=q4(totals["split"]["estimated"]),
        partial_value=q4(totals["split"]["partial"]),
        unknown_lots=totals["unknown_lots"],
        partial_lots=totals["partial_lots"],
        lot_count=totals["lot_count"],
    )
    db.add(snapshot)
    db.flush()
    for line in valuation.lines:
        db.add(
            StockValueLine(
                org_id=org_id,
                snapshot_id=snapshot.id,
                line_type=line.kind,
                inventory_item_id=line.item_id,
                execution_id=line.execution_id,
                name=line.name[:255],
                unit=line.unit,
                batch=(line.batch or None) and line.batch[:255],
                category=line.category,
                quantity=line.quantity,
                unit_cost=None if line.unit_cost is None else line.unit_cost.quantize(UNIT, rounding=ROUND_HALF_UP),
                known_unit_cost=None
                if line.known_unit_cost is None
                else line.known_unit_cost.quantize(UNIT, rounding=ROUND_HALF_UP),
                value=line.value,
                status=line.status,
            )
        )
    db.flush()
    if previous is not None:
        movements = compute_movements(
            db,
            org_id,
            previous,
            previous_lines,
            valuation,
            previous.cutoff_at,
            cutoff,
            period_start=previous.as_of_date + timedelta(days=1),
            period_end=as_of,
        )
        residue = q4(snapshot.total_value) - q4(_d(previous.total_value)) - sum((m.value for m in movements), ZERO)
        if residue:
            movements.append(_Movement(kind="rounding", value=q4(residue)))
        for movement in movements:
            db.add(
                StockValueMovement(
                    org_id=org_id,
                    snapshot_id=snapshot.id,
                    kind=movement.kind,
                    inventory_item_id=movement.item_id,
                    execution_id=movement.execution_id,
                    name=(movement.name or None) and movement.name[:255],
                    quantity=movement.quantity,
                    unit_cost=None
                    if movement.unit_cost is None
                    else movement.unit_cost.quantize(UNIT, rounding=ROUND_HALF_UP),
                    value=movement.value,
                )
            )
        snapshot.purchases_value = q4(sum((m.value for m in movements if m.kind == "purchase"), ZERO))
        db.flush()
    return snapshot


def ensure_month_end_snapshots(db: Session, org_id: UUID, *, trigger: str) -> list[StockValueSnapshot]:
    """Take the month-end snapshot of every completed NZ month after the latest one (oldest first,
    at most 12). With none yet, only the latest completed month, and never an empty first
    snapshot. Idempotent; the caller commits."""
    from app.core.security.entitlements import org_has_feature

    if not org_has_feature(db, org_id, FEATURE_KEY):
        return []
    last = last_day_before_month(purchase_sources.nz_today())
    _lock(db, org_id)
    month_ends = (
        db.query(StockValueSnapshot.as_of_date)
        .filter(StockValueSnapshot.org_id == org_id, StockValueSnapshot.kind == "month_end")
        .order_by(StockValueSnapshot.as_of_date.desc())
        .first()
    )
    latest = _latest(db, org_id)
    if month_ends is not None and month_ends[0] >= last:
        return []
    wanted: list[date] = []
    cursor = last
    while len(wanted) < MAX_MONTHS_CATCH_UP and (month_ends is None or cursor > month_ends[0]):
        wanted.append(cursor)
        if month_ends is None:
            break
        cursor = last_day_before_month(cursor)
    made: list[StockValueSnapshot] = []
    for as_of in reversed(wanted):
        cutoff = month_end_cutoff(as_of)
        if latest is not None and cutoff < latest.cutoff_at:
            continue  # a later snapshot exists: one can't be slotted in before it
        if latest is None and not _anything_to_value(db, org_id, cutoff):
            continue
        try:
            with db.begin_nested():
                snapshot = take_snapshot(
                    db, org_id, kind="month_end", trigger=trigger, as_of_date=as_of, cutoff_at=cutoff
                )
                if latest is None and snapshot.lot_count == 0 and not stored_lines(db, org_id, snapshot.id):
                    raise _EmptyError()
        except _EmptyError:
            continue
        except IntegrityError:
            continue  # another request took it first
        made.append(snapshot)
        latest = snapshot
    return made


class _EmptyError(Exception):
    """Nothing in stock at the cutoff: a first snapshot would only be noise."""


def _anything_to_value(db: Session, org_id: UUID, cutoff: datetime) -> bool:
    """Cheap pre-check: a lot or batch must exist from before the cutoff to be in stock at it."""
    lot = db.query(InventoryItem.id).filter(InventoryItem.org_id == org_id, InventoryItem.created_at < cutoff).first()
    return lot is not None


# --- the accountant's CSV ---------------------------------------------------------------------------------


def _csv_text(value) -> str:
    """Text a person typed, safe to open in a spreadsheet: no cell may start a formula."""
    text_value = "" if value is None else str(value)
    return "'" + text_value if text_value[:1] in ("=", "+", "-", "@", "\t", "\r") else text_value


def _cents(value) -> str:
    return "" if value is None else f"{value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):f}"


def export_csv(snapshot: StockValueSnapshot, rows: list[StockValueLine]) -> str:
    import csv
    import io

    buffer = io.StringIO()
    out = csv.writer(buffer)
    out.writerow(["Category", "Item", "Batch", "Quantity", "Unit", "Unit cost", "Value", "Cost status"])
    order = ("raw", "wip", "finished", "in_production")
    stored = [_StoredLine(r) for r in rows]
    subtotals = {}
    for category in order:
        part = [ln for ln in stored if ln.category == category]
        for line in sorted(part, key=lambda ln: (ln.name.casefold(), ln.batch or "")):
            out.writerow(
                [
                    CATEGORY_LABELS[category],
                    _csv_text(line.name),
                    _csv_text(line.batch),
                    "" if line.kind == "in_production" else qty(line.quantity),
                    _csv_text(line.unit),
                    "" if line.unit_cost is None else f"{line.unit_cost:.4f}",
                    _cents(line.value),
                    line.status,
                ]
            )
        if part:
            subtotals[category] = sum((ln.value for ln in part if ln.value is not None), ZERO)
    for category, amount in subtotals.items():
        out.writerow(["Subtotal", CATEGORY_LABELS[category], "", "", "", "", _cents(amount), ""])
    out.writerow(
        ["Total", f"As at {snapshot.as_of_date.isoformat()}", "", "", "", "", _cents(_d(snapshot.total_value)), ""]
    )
    if snapshot.unknown_lots:
        n = snapshot.unknown_lots
        out.writerow(["", f"{n} lot{' has' if n == 1 else 's have'} no cost, so this total is a floor"])
    if snapshot.partial_lots:
        out.writerow(["", f"{snapshot.partial_lots} partly costed (value is what is known)"])
    return buffer.getvalue()
