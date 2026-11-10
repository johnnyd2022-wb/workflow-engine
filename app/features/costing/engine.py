"""The cost roll-up, computed on read (live-cogs 8.1a).

Spec .agents/specs/live-cogs.md, "Cost roll-up" and "Recompute". Reads facts only
(``cost_flows``, ``lot_cost_entries``, lots, executions, transfers) and writes nothing. One
``CostEngine`` is one computation: results are memoised for its lifetime, so build a new one
per request.

Every value carries ``known`` (the dollars of inputs that have a cost — a floor when anything
is missing), a ``status`` (actual < estimated < partial < unknown), the ``missing`` lots it
depends on, and ``warnings``. Arithmetic is unrounded ``Decimal``; rounding happens only on
allocations (4 dp) and at the payload boundary.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.db.models.execution import Execution
from app.core.db.models.execution_step import ExecutionStep
from app.core.db.models.inventory_item import InventoryItem, InventoryType
from app.core.db.models.site_transfer import SiteStockReceipt, SiteStockTransfer
from app.core.utils.unit_conversion import are_units_compatible, convert_to_inventory_unit_decimal
from app.features.costing.models import DIRECT_KINDS, CostFlow, LotCostEntry
from app.features.costing.service import CostingNotFoundError, get_settings
from app.observability import get_logger

logger = get_logger(__name__)

ACTUAL, ESTIMATED, PARTIAL, UNKNOWN = "actual", "estimated", "partial", "unknown"
_RANK = {ACTUAL: 0, ESTIMATED: 1, PARTIAL: 2, UNKNOWN: 3}
MONEY = Decimal("0.0001")
UNIT = Decimal("0.000001")
QTY = Decimal("0.0001")
MAX_NODES = 20_000
ZERO = Decimal("0")
_TYPE_RANK = {
    InventoryType.FINAL_PRODUCT.value: 0,
    InventoryType.WORK_IN_PROGRESS.value: 1,
    InventoryType.RAW_MATERIAL.value: 2,
}
_LIBRARY_SUFFIX = " - library stock"


class TooLargeError(RuntimeError):
    pass


def worst(*statuses: str) -> str:
    return max(statuses, key=lambda s: _RANK[s]) if statuses else ACTUAL


def normalise(name: str | None) -> str:
    text = re.sub(r"\s+", " ", (name or "").strip().lower())
    if text.endswith(_LIBRARY_SUFFIX):
        text = text[: -len(_LIBRARY_SUFFIX)].strip()
    return text


def _d(value) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return ZERO


def money(value: Decimal | None) -> str | None:
    return None if value is None else str(value.quantize(MONEY, rounding=ROUND_HALF_UP))


def unit_str(value: Decimal | None) -> str | None:
    return None if value is None else str(value.quantize(UNIT, rounding=ROUND_HALF_UP))


def qty(value: Decimal) -> str:
    return str(value.quantize(QTY, rounding=ROUND_HALF_UP))


@dataclass
class LotCost:
    unit_known: Decimal | None
    status: str
    source: str
    missing: dict = field(default_factory=dict)  # str(lot id) -> name
    warnings: set = field(default_factory=set)
    priced_quantity: Decimal = ZERO
    unpriced_quantity: Decimal = ZERO
    estimate_from: InventoryItem | None = None


@dataclass
class Alloc:
    known: Decimal
    status: str
    missing: dict
    warnings: set
    weight: Decimal


@dataclass
class ExecCost:
    execution_id: UUID
    alloc: dict = field(default_factory=dict)  # flow id -> Alloc
    inputs: list = field(default_factory=list)
    outputs: list = field(default_factory=list)
    pool_known: Decimal = ZERO
    pool_status: str = ACTUAL
    status: str = ACTUAL
    missing: dict = field(default_factory=dict)
    warnings: set = field(default_factory=set)
    split_assumed: bool = False


class CostEngine:
    def __init__(self, db: Session, org_id: UUID):
        self.db = db
        self.org_id = org_id
        self.use_last_known_price = get_settings(db, org_id)["use_last_known_price"]
        self._lots: dict[UUID, InventoryItem | None] = {}
        self._lot_memo: dict[tuple[UUID, bool], LotCost] = {}
        self._lot_visiting: set[UUID] = set()
        self._exec_memo: dict[UUID, ExecCost] = {}
        self._exec_building: dict[UUID, ExecCost] = {}
        self._materials: dict[str, list[InventoryItem]] | None = None
        self._nodes = 0

    # --- public payloads -----------------------------------------------------------------

    def lot(self, item_id) -> dict:
        item = self._load_lot_or_404(item_id)
        try:
            cost = self._lot(item)
        except TooLargeError:
            return self._too_large_lot(item)
        from app.features.costing.service import active_entries, editable_reason

        entries = active_entries(self.db, self.org_id, item.id)
        public = cost.unit_known if cost.status in (ACTUAL, ESTIMATED) else None
        return {
            "inventory_item_id": str(item.id),
            "name": item.name,
            "unit": item.unit,
            "unit_cost": unit_str(public),
            "known_unit_cost": unit_str(cost.unit_known),
            "status": cost.status,
            "source": cost.source,
            "estimate_from": (
                {"inventory_item_id": str(cost.estimate_from.id), "name": cost.estimate_from.name}
                if cost.estimate_from is not None
                else None
            ),
            "priced_quantity": qty(cost.priced_quantity),
            "unpriced_quantity": qty(cost.unpriced_quantity),
            "missing": _missing_list(cost.missing),
            "warnings": sorted(cost.warnings),
            "entries": [
                {
                    "id": str(e.id),
                    "kind": e.kind,
                    "amount": money(_d(e.amount)),
                    "quantity": qty(_d(e.quantity)),
                    "cost_flow_id": str(e.cost_flow_id) if e.cost_flow_id else None,
                    "note": e.note,
                    "created_at": e.created_at.isoformat() if e.created_at else None,
                }
                for e in entries
            ],
            "editable": editable_reason(self.db, self.org_id, item) is None,
        }

    def execution(self, execution_id) -> dict:
        execution = self._load_execution_or_404(execution_id)
        try:
            cost = self._exec(execution.id)
        except TooLargeError:
            return {
                "execution_id": str(execution.id),
                "status": UNKNOWN,
                "known_input_cost": None,
                "cost_so_far": None,
                "cost_so_far_status": UNKNOWN,
                "split_assumed": False,
                "missing": [],
                "warnings": ["too_large"],
                "inputs": [],
                "outputs": [],
            }
        external = sum((i["_known"] for i in cost.inputs if not i["internal"]), ZERO)
        return {
            "execution_id": str(execution.id),
            "status": cost.status,
            "known_input_cost": money(external),
            "cost_so_far": money(cost.pool_known),
            "cost_so_far_status": cost.pool_status,
            "split_assumed": cost.split_assumed,
            "missing": _missing_list(cost.missing),
            "warnings": sorted(cost.warnings),
            "inputs": [{k: v for k, v in i.items() if not k.startswith("_")} for i in cost.inputs],
            "outputs": cost.outputs,
        }

    # --- loading ---------------------------------------------------------------------------

    def _tick(self) -> None:
        self._nodes += 1
        if self._nodes > MAX_NODES:
            raise TooLargeError()

    def _get_lot(self, item_id: UUID) -> InventoryItem | None:
        if item_id not in self._lots:
            self._lots[item_id] = (
                self.db.query(InventoryItem)
                .filter(InventoryItem.org_id == self.org_id, InventoryItem.id == item_id)
                .one_or_none()
            )
        return self._lots[item_id]

    def _load_lot_or_404(self, item_id) -> InventoryItem:
        try:
            uuid = UUID(str(item_id))
        except (ValueError, TypeError):
            raise CostingNotFoundError("Lot not found") from None
        item = self._get_lot(uuid)
        if item is None:
            raise CostingNotFoundError("Lot not found")
        return item

    def _load_execution_or_404(self, execution_id) -> Execution:
        try:
            uuid = UUID(str(execution_id))
        except (ValueError, TypeError):
            raise CostingNotFoundError("Batch not found") from None
        execution = self.db.query(Execution).filter(Execution.org_id == self.org_id, Execution.id == uuid).one_or_none()
        if execution is None:
            raise CostingNotFoundError("Batch not found")
        return execution

    def _in_flows(self, item_id: UUID) -> list[CostFlow]:
        return (
            self.db.query(CostFlow)
            .filter(CostFlow.org_id == self.org_id, CostFlow.inventory_item_id == item_id, CostFlow.direction == "in")
            .order_by(CostFlow.created_at, CostFlow.id)
            .all()
        )

    def _entries(self, item_id: UUID) -> list[LotCostEntry]:
        return (
            self.db.query(LotCostEntry)
            .filter(
                LotCostEntry.org_id == self.org_id,
                LotCostEntry.inventory_item_id == item_id,
                LotCostEntry.is_active.is_(True),
            )
            .all()
        )

    def _transfer_source(self, item: InventoryItem) -> InventoryItem | None:
        receipt = (
            self.db.query(SiteStockReceipt)
            .filter(SiteStockReceipt.org_id == self.org_id, SiteStockReceipt.id == item.transfer_receipt_id)
            .one_or_none()
        )
        if receipt is None:
            return None
        transfer = (
            self.db.query(SiteStockTransfer)
            .filter(SiteStockTransfer.org_id == self.org_id, SiteStockTransfer.id == receipt.transfer_id)
            .one_or_none()
        )
        if transfer is None or transfer.source_item_id == item.id:
            return None
        return self._get_lot(transfer.source_item_id)

    # --- lots --------------------------------------------------------------------------------

    def _lot(self, item: InventoryItem, allow_estimate: bool = True) -> LotCost:
        key = (item.id, allow_estimate)
        if key in self._lot_memo:
            return self._lot_memo[key]
        if item.contract_customer_id:
            result = LotCost(ZERO, ACTUAL, "customer_owned")
            self._lot_memo[key] = result
            return result
        if item.id in self._lot_visiting:
            return LotCost(None, UNKNOWN, "none", missing={str(item.id): item.name}, warnings={"cycle"})
        self._tick()
        self._lot_visiting.add(item.id)
        try:
            result = self._compute_lot(item, allow_estimate)
        finally:
            self._lot_visiting.discard(item.id)
        self._lot_memo[key] = result
        return result

    def _compute_lot(self, item: InventoryItem, allow_estimate: bool) -> LotCost:
        ins = self._in_flows(item.id)
        entries = self._entries(item.id)
        flow_prices = {e.cost_flow_id: e for e in entries if e.cost_flow_id is not None}
        whole = next((e for e in entries if e.cost_flow_id is None), None)

        parts: list[tuple[Decimal, Decimal, str]] = []
        missing: dict = {}
        warnings: set = set()
        sources: set = set()
        unpriced_direct = ZERO
        unpriced_other = ZERO

        for f in ins:
            q = _d(f.quantity)
            if f.kind == "transfer_in":
                src = self._transfer_source(item)
                c = self._lot(src) if src is not None else None
                if c is None:
                    warnings.add("transfer_source_missing")
                    unpriced_other += q
                    continue
                missing.update(c.missing)
                warnings |= c.warnings
                factor = self._unit_factor(item.unit, src.unit)
                if c.unit_known is None or factor is None:
                    unpriced_other += q
                    continue
                parts.append((q, q * c.unit_known * factor, c.status))
                sources.add("transfer")
            elif f.kind in ("produced", "reconciled_in"):
                a = self._allocation(f, item)
                parts.append((q, a.known, a.status))
                missing.update(a.missing)
                warnings |= a.warnings
                sources.add("production")
            else:
                fp = flow_prices.get(f.id)
                if fp is not None:
                    pq, amount = _d(fp.quantity), _d(fp.amount)
                    if pq > q:  # can't happen through the service; never price more than the flow
                        amount, pq = amount * q / pq, q
                    parts.append((pq, amount, ACTUAL))
                    sources.add("free" if fp.kind == "free" else "manual")
                    unpriced_direct += q - pq
                else:
                    unpriced_direct += q

        if whole is not None:
            p = _d(whole.amount) / _d(whole.quantity)
            source = "free" if whole.kind == "free" else "manual"
            if unpriced_direct > 0:
                parts.append((unpriced_direct, unpriced_direct * p, ACTUAL))
                sources.add(source)
                unpriced_direct = ZERO
            elif not ins:  # a lot from before flows existed: the typed price is its price
                return LotCost(p, ACTUAL, source, priced_quantity=_d(whole.quantity))

        unpriced = unpriced_direct + unpriced_other
        if parts:
            total_q = sum((p[0] for p in parts), ZERO)
            total_k = sum((p[1] for p in parts), ZERO)
            status = worst(*(p[2] for p in parts))
            if unpriced > 0:
                status = worst(status, ESTIMATED)
            unit = total_k / total_q if total_q > 0 else None
            source = sources.pop() if len(sources) == 1 else "mixed"
            return LotCost(unit, status, source, missing, warnings, total_q, unpriced)

        if allow_estimate and self.use_last_known_price:
            estimate = self._estimate(item)
            if estimate is not None:
                source_lot, unit = estimate
                return LotCost(unit, ESTIMATED, "estimate", missing, warnings, ZERO, unpriced, estimate_from=source_lot)
        missing = {**missing, str(item.id): item.name}
        return LotCost(None, UNKNOWN, "none", missing, warnings, ZERO, unpriced)

    def _unit_factor(self, lot_unit: str, source_unit: str) -> Decimal | None:
        """How many ``source_unit`` there are in one ``lot_unit`` (price conversion)."""
        if (lot_unit or "").strip().lower() == (source_unit or "").strip().lower():
            return Decimal("1")
        if not are_units_compatible(lot_unit, source_unit):
            return None
        try:
            return convert_to_inventory_unit_decimal(Decimal("1"), lot_unit, source_unit)
        except (ValueError, InvalidOperation):
            return None

    def _material_index(self) -> dict[str, list[InventoryItem]]:
        if self._materials is None:
            index: dict[str, list[InventoryItem]] = defaultdict(list)
            for lot in self.db.query(InventoryItem).filter(InventoryItem.org_id == self.org_id).all():
                self._lots.setdefault(lot.id, lot)
                if not lot.contract_customer_id:
                    index[normalise(lot.name)].append(lot)
            self._materials = index
        return self._materials

    def _is_direct(self, lot: InventoryItem) -> bool:
        if lot.transfer_receipt_id or lot.source_execution_step_id:
            return False
        return all(f.kind in DIRECT_KINDS for f in self._in_flows(lot.id))

    def _estimate(self, item: InventoryItem) -> tuple[InventoryItem, Decimal] | None:
        target = _lot_date(item)
        candidates = []
        for other in self._material_index().get(normalise(item.name), []):
            if other.id == item.id or not self._is_direct(other):
                continue
            factor = self._unit_factor(item.unit, other.unit)
            if factor is None:
                continue
            cost = self._lot(other, allow_estimate=False)
            if cost.status != ACTUAL or cost.unit_known is None or cost.source not in ("manual", "free", "purchase"):
                continue
            candidates.append((other, cost.unit_known * factor))
        if not candidates:
            return None
        before = [c for c in candidates if _lot_date(c[0]) <= target]
        if before:
            return max(before, key=lambda c: (_lot_date(c[0]), c[0].created_at, str(c[0].id)))
        return min(candidates, key=lambda c: (_lot_date(c[0]), c[0].created_at, str(c[0].id)))

    # --- executions ----------------------------------------------------------------------------

    def _allocation(self, flow: CostFlow, item: InventoryItem) -> Alloc:
        building = self._exec_building.get(flow.execution_id)
        if building is not None:  # inside that execution: only earlier steps are settled
            found = building.alloc.get(flow.id)
            if found is not None:
                return found
            return Alloc(ZERO, PARTIAL, {str(item.id): item.name}, {"cycle"}, ZERO)
        found = self._exec(flow.execution_id).alloc.get(flow.id)
        if found is None:
            return Alloc(ZERO, PARTIAL, {str(item.id): item.name}, {"unallocated_output"}, ZERO)
        return found

    def _exec(self, execution_id: UUID) -> ExecCost:
        if execution_id in self._exec_memo:
            return self._exec_memo[execution_id]
        if execution_id in self._exec_building:
            return self._exec_building[execution_id]
        self._tick()
        cost = ExecCost(execution_id=execution_id)
        self._exec_building[execution_id] = cost
        try:
            self._compute_exec(cost)
        finally:
            self._exec_building.pop(execution_id, None)
        self._exec_memo[execution_id] = cost
        return cost

    def _compute_exec(self, cost: ExecCost) -> None:
        steps = (
            self.db.query(ExecutionStep)
            .filter(ExecutionStep.org_id == self.org_id, ExecutionStep.execution_id == cost.execution_id)
            .order_by(ExecutionStep.step_number, ExecutionStep.id)
            .all()
        )
        flows = (
            self.db.query(CostFlow)
            .filter(CostFlow.org_id == self.org_id, CostFlow.execution_id == cost.execution_id)
            .order_by(CostFlow.created_at, CostFlow.id)
            .all()
        )
        consumed, outs = defaultdict(list), defaultdict(list)
        for f in flows:
            (consumed if f.direction == "out" else outs)[f.execution_step_id].append(f)
        internal = {f.inventory_item_id for f in flows if f.direction == "in"}

        pool_known, pool_status, pool_missing, pool_warnings = ZERO, ACTUAL, {}, set()
        input_statuses: list[str] = []

        for step in steps:
            step_consumed = consumed.get(step.id, [])
            if not step_consumed and _completed(step):
                named = _named_input_lots(step)
                if named:
                    pool_status = worst(pool_status, PARTIAL)
                    for item_id, name in named:
                        lot = self._get_lot(item_id)
                        pool_missing[str(item_id)] = lot.name if lot is not None else name
                    pool_warnings.add("no_flow_history")
                    input_statuses.append(PARTIAL)

            for c in step_consumed:
                lot = self._get_lot(c.inventory_item_id)
                if lot is None:
                    cost.warnings.add("input_lot_missing")
                    continue
                u = self._lot(lot)
                q = _d(c.quantity)
                known = q * u.unit_known if u.unit_known is not None else ZERO
                status = u.status if u.status != UNKNOWN else PARTIAL
                pool_known += known
                pool_status = worst(pool_status, status)
                pool_missing.update(u.missing)
                pool_warnings |= u.warnings
                input_statuses.append(status)
                cost.inputs.append(
                    {
                        "inventory_item_id": str(lot.id),
                        "name": lot.name,
                        "step_number": step.step_number,
                        "quantity": qty(q),
                        "unit": lot.unit,
                        "unit_cost": unit_str(u.unit_known if u.status in (ACTUAL, ESTIMATED) else None),
                        "known_amount": money(known),
                        "status": u.status,
                        "internal": lot.id in internal,
                        "_known": known,
                    }
                )

            step_outs = outs.get(step.id, [])
            if not step_outs:
                continue
            weights, assumed = self._split_weights(step, step_outs)
            cost.split_assumed = cost.split_assumed or assumed
            amounts = _allocate(pool_known, step_outs, weights)
            cost.missing.update(pool_missing)
            cost.warnings |= pool_warnings
            for f in step_outs:
                w = weights[f.id]
                if w == 0:
                    a = Alloc(ZERO, ACTUAL, {}, set(), ZERO)
                else:
                    a = Alloc(amounts[f.id], pool_status, dict(pool_missing), set(pool_warnings), w)
                cost.alloc[f.id] = a
                lot = self._get_lot(f.inventory_item_id)
                q = _d(f.quantity)
                known_unit = a.known / q if q > 0 else None
                cost.outputs.append(
                    {
                        "inventory_item_id": str(f.inventory_item_id),
                        "flow_id": str(f.id),
                        "kind": f.kind,
                        "name": lot.name if lot is not None else None,
                        "step_number": step.step_number,
                        "quantity": qty(q),
                        "unit": lot.unit if lot is not None else None,
                        "known_amount": money(a.known),
                        "unit_cost": unit_str(known_unit if a.status in (ACTUAL, ESTIMATED) else None),
                        "known_unit_cost": unit_str(known_unit),
                        "status": a.status,
                        "missing": _missing_list(a.missing),
                        "weight": unit_str(w),
                    }
                )
            pool_known, pool_status, pool_missing, pool_warnings = ZERO, ACTUAL, {}, set()

        cost.missing.update(pool_missing)
        cost.warnings |= pool_warnings
        cost.pool_known = pool_known
        cost.pool_status = pool_status
        cost.status = worst(ACTUAL, *input_statuses, pool_status)

    def _split_weights(self, step: ExecutionStep, outs: list[CostFlow]) -> tuple[dict, bool]:
        """Spec "split_weights": a weight per output flow summing to 1, and whether it was assumed."""
        defs = {
            str(d.get("id")): d
            for d in ((step.step.outputs if step.step is not None else None) or [])
            if isinstance(d, dict) and d.get("id")
        }
        lots = {f.id: self._get_lot(f.inventory_item_id) for f in outs}

        def is_library(f):
            lot = lots[f.id]
            return bool(lot is not None and (lot.extra_data or {}).get("library_stock"))

        weights = {f.id: ZERO for f in outs}
        library = [f for f in outs if is_library(f)]
        candidates = [f for f in outs if not is_library(f)] or library
        assumed = False

        percent, byproduct, free = {}, [], []
        for f in candidates:
            cfg = _cost_share(defs.get(str(f.source_output_id)) if f.source_output_id else None)
            if cfg is None:
                free.append(f)
            elif cfg == "byproduct":
                byproduct.append(f)
            else:
                percent[f.id] = cfg
        if not percent and not free:
            free, byproduct, assumed = byproduct, [], True

        total_percent = sum(percent.values(), ZERO)
        hundred = Decimal("100")
        if percent and (total_percent > hundred or not free):
            for fid, v in percent.items():
                weights[fid] = v / total_percent
            return weights, assumed
        for fid, v in percent.items():
            weights[fid] = v / hundred
        rest = (hundred - total_percent) / hundred
        if not free or rest <= 0:
            return weights, assumed
        if len(free) == 1:
            weights[free[0].id] = rest
            return weights, assumed
        base_unit = lots[free[0].id].unit if lots[free[0].id] is not None else None
        converted = {}
        for f in free:
            lot = lots[f.id]
            factor = self._unit_factor(base_unit, lot.unit) if lot is not None and base_unit else None
            if factor is None:
                converted = None
                break
            # quantity of f in base units = q * (base units per one lot unit) = q / factor
            converted[f.id] = _d(f.quantity) / factor
        if converted and sum(converted.values(), ZERO) > 0:
            total = sum(converted.values(), ZERO)
            for fid, q in converted.items():
                weights[fid] = rest * q / total
            return weights, assumed
        primary = min(free, key=lambda f: _primary_key(f, lots[f.id]))
        weights[primary.id] = rest
        return weights, True

    def _too_large_lot(self, item: InventoryItem) -> dict:
        return {
            "inventory_item_id": str(item.id),
            "name": item.name,
            "unit": item.unit,
            "unit_cost": None,
            "known_unit_cost": None,
            "status": UNKNOWN,
            "source": "none",
            "estimate_from": None,
            "priced_quantity": qty(ZERO),
            "unpriced_quantity": qty(ZERO),
            "missing": [],
            "warnings": ["too_large"],
            "entries": [],
            "editable": False,
        }


# --- helpers ---------------------------------------------------------------------------------


def _lot_date(lot: InventoryItem) -> date:
    if lot.purchase_date:
        return lot.purchase_date
    return lot.created_at.date() if lot.created_at else date.min


def _missing_list(missing: dict) -> list[dict]:
    return [
        {"inventory_item_id": k, "name": v} for k, v in sorted(missing.items(), key=lambda kv: (kv[1] or "", kv[0]))
    ]


def _completed(step: ExecutionStep) -> bool:
    status = getattr(step.status, "value", step.status)
    return str(status).lower() == "completed" or step.completed_at is not None


def _named_input_lots(step: ExecutionStep) -> list[tuple[UUID, str]]:
    found = {}
    for row in step.actual_inputs or []:
        if not isinstance(row, dict) or not row.get("inventory_item_id"):
            continue
        try:
            found[UUID(str(row["inventory_item_id"]))] = str(row.get("name") or "")
        except (ValueError, TypeError):
            continue
    return list(found.items())


def _cost_share(definition: dict | None):
    """Decimal percent, 'byproduct', or None (no valid config)."""
    if not definition:
        return None
    share = definition.get("cost_share")
    if not isinstance(share, dict):
        return None
    mode = share.get("mode")
    if mode == "byproduct":
        return "byproduct"
    if mode == "percent":
        raw = share.get("value")
        if isinstance(raw, bool):
            return None
        try:
            value = Decimal(str(raw))
        except (InvalidOperation, ValueError, TypeError):
            return None
        if value.is_finite() and Decimal("0") < value <= Decimal("100"):
            return value
    return None


def _primary_key(flow: CostFlow, lot: InventoryItem | None):
    rank = _TYPE_RANK.get(lot.inventory_type if lot is not None else "", 3)
    return (rank, -_d(flow.quantity), flow.created_at, str(flow.id))


def _allocate(pool: Decimal, outs: list[CostFlow], weights: dict) -> dict:
    """Quantise each share to 4 dp; the rounding remainder goes to the largest weight."""
    total = pool.quantize(MONEY, rounding=ROUND_HALF_UP)
    shares = {f.id: (pool * weights[f.id]).quantize(MONEY, rounding=ROUND_HALF_UP) for f in outs}
    weighted = [f for f in outs if weights[f.id] > 0]
    if weighted:
        remainder = total - sum(shares.values(), ZERO)
        if remainder:
            top = max(weights[f.id] for f in weighted)
            biggest = min((f for f in weighted if weights[f.id] == top), key=lambda f: (f.created_at, str(f.id)))
            shares[biggest.id] += remainder
    return shares
