"""The cost roll-up, computed on read (live-cogs 8.1a).

Spec .agents/specs/live-cogs.md, "Cost roll-up" and "Recompute". Reads facts only
(``cost_flows``, ``lot_cost_entries``, lots, executions, transfers) and writes nothing. One
``CostEngine`` is one computation: results are memoised for its lifetime, so build a new one
per request.

The graph has two kinds of node: a **lot**, and a **batch step** (the batch's cost pool after
that step). A lot made by step *n* depends on node (batch, *n*); step *n* depends on step
*n − 1* and on the lots it consumed. Working at step granularity keeps a WIP handed from step 1
to step 2 of one batch acyclic. The walk is an explicit stack, not recursion, so depth is
bounded only by ``MAX_NODES``; a node met again while it is still being worked on is a cycle,
and that edge contributes an unknown (``partial`` + warning ``cycle``).

Every value carries ``known`` (dollars of inputs that have a cost — a floor when anything is
missing), a ``status`` (actual < estimated < partial < unknown), the ``missing`` lots and
``warnings``. Arithmetic is unrounded ``Decimal``; rounding happens only on allocations (4 dp)
and at the payload boundary.
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
# Operational cap on rows a single computation may load (steps, flows), whatever the semantic
# node count: bounds the work one request can make the database do.
MAX_WORK = 200_000
ZERO = Decimal("0")
HUNDRED = Decimal("100")
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
class StepCost:
    """The batch's pool after one step, and what that step consumed and handed out."""

    carry_known: Decimal = ZERO
    carry_status: str = ACTUAL
    carry_missing: dict = field(default_factory=dict)
    carry_warnings: set = field(default_factory=set)
    alloc: dict = field(default_factory=dict)  # flow id -> Alloc, for this step's outputs
    inputs: list = field(default_factory=list)
    outputs: list = field(default_factory=list)
    statuses: list = field(default_factory=list)
    absorbed_missing: dict = field(default_factory=dict)
    absorbed_warnings: set = field(default_factory=set)
    split_assumed: bool = False


@dataclass
class ExecInfo:
    steps: list
    index: dict  # execution_step id -> position
    consumed: dict  # position -> [CostFlow]
    outs: dict  # position -> [CostFlow]
    internal: set  # lots produced by this execution


def _cycle_lot(item: InventoryItem) -> LotCost:
    return LotCost(None, UNKNOWN, "none", missing={str(item.id): item.name}, warnings={"cycle"})


class CostEngine:
    def __init__(self, db: Session, org_id: UUID):
        self.db = db
        self.org_id = org_id
        self.use_last_known_price = get_settings(db, org_id)["use_last_known_price"]
        self._lots: dict[UUID, InventoryItem | None] = {}
        self._in_flow_cache: dict[UUID, list[CostFlow]] = {}
        self._entry_cache: dict[UUID, list[LotCostEntry]] = {}
        self._allocation_cache: dict[UUID, list] = {}
        self._transfer_cache: dict[UUID, InventoryItem | None] = {}
        self._exec_info: dict[UUID, ExecInfo | None] = {}
        self._memo: dict[tuple, object] = {}
        self._active: set[tuple] = set()  # entered, not finished: met again = cycle
        self._direct_memo: dict[UUID, LotCost] = {}
        self._materials: dict[str, list[InventoryItem]] | None = None
        self._charged: set[tuple] = set()
        self._work = 0

    # --- public payloads -----------------------------------------------------------------

    def lot(self, item_id) -> dict:
        item = self._load_lot_or_404(item_id)
        try:
            cost = self._solve(("lot", item.id))
        except TooLargeError:
            return self._too_large_lot(item)
        from app.features.costing.service import active_entries, editable_reason, lot_provenance

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
            "provenance": lot_provenance(self.db, self.org_id, item),
        }

    def execution(self, execution_id) -> dict:
        execution = self._load_execution_or_404(execution_id)
        try:
            info = self._info(execution.id)
            steps = [self._solve(("step", execution.id, i)) for i in range(len(info.steps))]
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
        inputs = [i for s in steps for i in s.inputs]
        missing: dict = {}
        warnings: set = set()
        for s in steps:
            missing.update(s.absorbed_missing)
            warnings |= s.absorbed_warnings
        last = steps[-1] if steps else StepCost()
        missing.update(last.carry_missing)
        warnings |= last.carry_warnings
        statuses = [st for s in steps for st in s.statuses]
        external = sum((i["_known"] for i in inputs if not i["internal"]), ZERO)
        return {
            "execution_id": str(execution.id),
            "status": worst(ACTUAL, *statuses, last.carry_status),
            "known_input_cost": money(external),
            "cost_so_far": money(last.carry_known),
            "cost_so_far_status": last.carry_status,
            "split_assumed": any(s.split_assumed for s in steps),
            "missing": _missing_list(missing),
            "warnings": sorted(warnings),
            "inputs": [{k: v for k, v in i.items() if not k.startswith("_")} for i in inputs],
            "outputs": [o for s in steps for o in s.outputs],
        }

    # --- the walk ------------------------------------------------------------------------------

    def _solve(self, root: tuple):
        """Evaluate ``root`` after everything it depends on, without recursion."""
        stack = [root]
        while stack:
            node = stack[-1]
            if node in self._memo:
                stack.pop()
                continue
            if node not in self._active:
                self._charge(node)
                self._active.add(node)
                pending = [d for d in self._deps(node) if d not in self._memo and d not in self._active]
                if pending:
                    stack.extend(reversed(pending))
                    continue
            # every dependency is now settled, or is an ancestor still being worked on (a cycle)
            self._memo[node] = self._evaluate(node)
            self._active.discard(node)
            stack.pop()
        return self._memo[root]

    def _charge(self, node: tuple) -> None:
        """The budget is lots + executions (spec "Recompute"); steps are internal detail."""
        key = ("lot", node[1]) if node[0] == "lot" else ("execution", node[1])
        if key in self._charged:
            return
        self._charged.add(key)
        if len(self._charged) > MAX_NODES:
            raise TooLargeError()

    def _spend(self, rows: int) -> None:
        self._work += rows
        if self._work > MAX_WORK:
            raise TooLargeError()

    def _deps(self, node: tuple) -> list[tuple]:
        if node[0] == "lot":
            item = self._get_lot(node[1])
            if item is None or item.contract_customer_id:
                return []
            deps = []
            for f in self._in_flows(item.id):
                if f.kind == "transfer_in":
                    src = self._transfer_source(item)
                    if src is not None:
                        deps.append(("lot", src.id))
                elif f.kind in ("produced", "reconciled_in"):
                    info = self._info(f.execution_id)
                    position = info.index.get(f.execution_step_id) if info else None
                    if position is not None:
                        deps.append(("step", f.execution_id, position))
            return deps
        _, execution_id, position = node
        info = self._info(execution_id)
        deps = [("step", execution_id, position - 1)] if position > 0 else []
        for c in info.consumed.get(position, []):
            if self._get_lot(c.inventory_item_id) is not None:
                deps.append(("lot", c.inventory_item_id))
        return deps

    def _evaluate(self, node: tuple):
        if node[0] == "lot":
            return self._evaluate_lot(self._get_lot(node[1]), allow_estimate=True)
        return self._evaluate_step(node[1], node[2])

    def _lot_value(self, item: InventoryItem) -> LotCost:
        node = ("lot", item.id)
        if node in self._memo:
            return self._memo[node]
        return _cycle_lot(item)  # only reachable for an ancestor still on the stack

    def _step_value(self, execution_id: UUID, position: int) -> StepCost | None:
        return self._memo.get(("step", execution_id, position))

    # --- loading ---------------------------------------------------------------------------

    def prime(self, item_ids) -> None:
        """Bulk-load lots, in-flows, entries and allocations for many lots in four queries, so a
        caller costing a list of lots (readiness) doesn't pay one round of queries per lot."""
        from app.features.costing.models import PurchaseAllocation

        ids = [i for i in {*item_ids} if i is not None and i not in self._in_flow_cache]
        for start in range(0, len(ids), 1000):
            chunk = ids[start : start + 1000]
            for lot in self.db.query(InventoryItem).filter(
                InventoryItem.org_id == self.org_id, InventoryItem.id.in_(chunk)
            ):
                self._lots.setdefault(lot.id, lot)
            for item_id in chunk:
                self._lots.setdefault(item_id, None)
                self._in_flow_cache[item_id] = []
                self._entry_cache.setdefault(item_id, [])
                self._allocation_cache.setdefault(item_id, [])
            flows = (
                self.db.query(CostFlow)
                .filter(
                    CostFlow.org_id == self.org_id, CostFlow.inventory_item_id.in_(chunk), CostFlow.direction == "in"
                )
                .order_by(CostFlow.created_at, CostFlow.id)
                .all()
            )
            self._spend(len(flows))
            for flow in flows:
                self._in_flow_cache[flow.inventory_item_id].append(flow)
            fresh_entries = {i for i in chunk if not self._entry_cache[i]}
            for entry in self.db.query(LotCostEntry).filter(
                LotCostEntry.org_id == self.org_id,
                LotCostEntry.inventory_item_id.in_(fresh_entries),
                LotCostEntry.is_active.is_(True),
            ):
                self._entry_cache[entry.inventory_item_id].append(entry)
            fresh_allocs = {i for i in chunk if not self._allocation_cache[i]}
            for alloc in self.db.query(PurchaseAllocation).filter(
                PurchaseAllocation.org_id == self.org_id,
                PurchaseAllocation.inventory_item_id.in_(fresh_allocs),
                PurchaseAllocation.status.in_(("active", "orphaned")),
            ):
                self._allocation_cache[alloc.inventory_item_id].append(alloc)

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
        if item_id not in self._in_flow_cache:
            self._in_flow_cache[item_id] = (
                self.db.query(CostFlow)
                .filter(
                    CostFlow.org_id == self.org_id,
                    CostFlow.inventory_item_id == item_id,
                    CostFlow.direction == "in",
                )
                .order_by(CostFlow.created_at, CostFlow.id)
                .all()
            )
            self._spend(len(self._in_flow_cache[item_id]))
        return self._in_flow_cache[item_id]

    def _entries(self, item_id: UUID) -> list[LotCostEntry]:
        if item_id not in self._entry_cache:
            self._entry_cache[item_id] = (
                self.db.query(LotCostEntry)
                .filter(
                    LotCostEntry.org_id == self.org_id,
                    LotCostEntry.inventory_item_id == item_id,
                    LotCostEntry.is_active.is_(True),
                )
                .all()
            )
        return self._entry_cache[item_id]

    def _allocations(self, item_id: UUID) -> list:
        """Purchase allocations (8.1c) priced on this lot: active and orphaned."""
        from app.features.costing.models import PurchaseAllocation

        if item_id not in self._allocation_cache:
            self._allocation_cache[item_id] = (
                self.db.query(PurchaseAllocation)
                .filter(
                    PurchaseAllocation.org_id == self.org_id,
                    PurchaseAllocation.inventory_item_id == item_id,
                    PurchaseAllocation.status.in_(("active", "orphaned")),
                )
                .all()
            )
        return self._allocation_cache[item_id]

    def _transfer_source(self, item: InventoryItem) -> InventoryItem | None:
        if item.id in self._transfer_cache:
            return self._transfer_cache[item.id]
        src = None
        receipt = (
            self.db.query(SiteStockReceipt)
            .filter(SiteStockReceipt.org_id == self.org_id, SiteStockReceipt.id == item.transfer_receipt_id)
            .one_or_none()
            if item.transfer_receipt_id
            else None
        )
        if receipt is not None:
            transfer = (
                self.db.query(SiteStockTransfer)
                .filter(SiteStockTransfer.org_id == self.org_id, SiteStockTransfer.id == receipt.transfer_id)
                .one_or_none()
            )
            if transfer is not None and transfer.source_item_id != item.id:
                src = self._get_lot(transfer.source_item_id)
        self._transfer_cache[item.id] = src
        return src

    def _info(self, execution_id: UUID) -> ExecInfo | None:
        if execution_id in self._exec_info:
            return self._exec_info[execution_id]
        steps = (
            self.db.query(ExecutionStep)
            .filter(ExecutionStep.org_id == self.org_id, ExecutionStep.execution_id == execution_id)
            .order_by(ExecutionStep.step_number, ExecutionStep.id)
            .all()
        )
        self._spend(len(steps))
        index = {s.id: i for i, s in enumerate(steps)}
        consumed, outs = defaultdict(list), defaultdict(list)
        internal = set()
        flows = (
            self.db.query(CostFlow)
            .filter(CostFlow.org_id == self.org_id, CostFlow.execution_id == execution_id)
            .order_by(CostFlow.created_at, CostFlow.id)
            .all()
        )
        self._spend(len(flows))
        for f in flows:
            position = index.get(f.execution_step_id)
            if f.direction == "in":
                internal.add(f.inventory_item_id)
            if position is None:
                continue
            (consumed if f.direction == "out" else outs)[position].append(f)
        info = ExecInfo(steps, index, consumed, outs, internal)
        self._exec_info[execution_id] = info
        return info

    # --- lots --------------------------------------------------------------------------------

    def _evaluate_lot(self, item: InventoryItem, allow_estimate: bool) -> LotCost:
        if item.contract_customer_id:
            return LotCost(ZERO, ACTUAL, "customer_owned")
        ins = self._in_flows(item.id)
        entries = self._entries(item.id)
        whole = next((e for e in entries if e.cost_flow_id is None), None)
        # A flow's price = its active entry plus its positive purchase allocations (summed);
        # negative allocations are refunds, applied once after pricing.
        flow_prices: dict = defaultdict(lambda: [ZERO, ZERO, ACTUAL, set()])  # qty, amount, status, sources
        for e in entries:
            if e.cost_flow_id is not None:
                fp = flow_prices[e.cost_flow_id]
                fp[0] += _d(e.quantity)
                fp[1] += _d(e.amount)
                fp[3].add("free" if e.kind == "free" else "manual")
        refunds = ZERO
        refund_status = ACTUAL
        for alloc in self._allocations(item.id):
            amount = _d(alloc.amount)
            if amount < 0:
                refunds += amount
                if alloc.status == "orphaned":  # the refund is gone from Xero
                    refund_status = ESTIMATED
                continue
            if alloc.cost_flow_id is None:
                continue
            fp = flow_prices[alloc.cost_flow_id]
            fp[0] += _d(alloc.quantity)
            fp[1] += amount
            fp[3].add("purchase")
            if alloc.status == "orphaned":  # its purchase was deleted or changed in Xero
                fp[2] = ESTIMATED

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
                if src is None:
                    warnings.add("transfer_source_missing")
                    unpriced_other += q
                    continue
                c = self._lot_value(src)
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
                if fp is not None and fp[0] > 0:
                    pq, amount, fstatus, fsources = fp
                    if pq > q:  # can't happen through the services; never price more than the flow
                        amount, pq = amount * q / pq, q
                    parts.append((pq, amount, fstatus))
                    sources |= fsources
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
            if refunds:
                status = worst(status, refund_status)
                total_k += refunds
                if total_k < 0:
                    total_k = ZERO
                    warnings.add("refund_exceeds_cost")
            unit = total_k / total_q if total_q > 0 else None
            source = sources.pop() if len(sources) == 1 else "mixed"
            return LotCost(unit, status, source, missing, warnings, total_q, unpriced)
        if refunds:
            warnings.add("refund_without_cost")

        if allow_estimate and self.use_last_known_price:
            estimate = self._estimate(item)
            if estimate is not None:
                source_lot, unit = estimate
                return LotCost(unit, ESTIMATED, "estimate", missing, warnings, ZERO, unpriced, estimate_from=source_lot)
        missing = {**missing, str(item.id): item.name}
        return LotCost(None, UNKNOWN, "none", missing, warnings, ZERO, unpriced)

    def _unit_factor(self, lot_unit: str | None, source_unit: str | None) -> Decimal | None:
        """How many ``source_unit`` there are in one ``lot_unit`` (price conversion)."""
        if (lot_unit or "").strip().lower() == (source_unit or "").strip().lower():
            return Decimal("1")
        if not lot_unit or not source_unit or not are_units_compatible(lot_unit, source_unit):
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
        if lot.transfer_receipt_id or lot.source_execution_step_id or lot.contract_customer_id:
            return False
        return all(f.kind in DIRECT_KINDS for f in self._in_flows(lot.id))

    def _direct_cost(self, lot: InventoryItem) -> LotCost:
        """A directly priced lot's own cost — no estimate, and no dependencies to walk."""
        if lot.id not in self._direct_memo:
            self._direct_memo[lot.id] = self._evaluate_lot(lot, allow_estimate=False)
        return self._direct_memo[lot.id]

    def _estimate(self, item: InventoryItem) -> tuple[InventoryItem, Decimal] | None:
        target = _lot_date(item)
        candidates = []
        for other in self._material_index().get(normalise(item.name), []):
            if other.id == item.id:
                continue
            self._charge(("lot", other.id))
            if not self._is_direct(other):
                continue
            factor = self._unit_factor(item.unit, other.unit)
            if factor is None:
                continue
            cost = self._direct_cost(other)
            if cost.status != ACTUAL or cost.unit_known is None:
                continue
            candidates.append((other, cost.unit_known * factor))
        if not candidates:
            return None
        before = [c for c in candidates if _lot_date(c[0]) <= target]
        if before:
            return max(before, key=lambda c: (_lot_date(c[0]), c[0].created_at, str(c[0].id)))
        return min(candidates, key=lambda c: (_lot_date(c[0]), c[0].created_at, str(c[0].id)))

    # --- batch steps --------------------------------------------------------------------------

    def _allocation(self, flow: CostFlow, item: InventoryItem) -> Alloc:
        info = self._info(flow.execution_id)
        position = info.index.get(flow.execution_step_id) if info else None
        if position is None:
            return Alloc(ZERO, PARTIAL, {str(item.id): item.name}, {"unallocated_output"}, ZERO)
        step = self._step_value(flow.execution_id, position)
        if step is None:  # that step is an ancestor still being worked on
            return Alloc(ZERO, PARTIAL, {str(item.id): item.name}, {"cycle"}, ZERO)
        found = step.alloc.get(flow.id)
        if found is None:
            return Alloc(ZERO, PARTIAL, {str(item.id): item.name}, {"unallocated_output"}, ZERO)
        return found

    def _evaluate_step(self, execution_id: UUID, position: int) -> StepCost:
        info = self._info(execution_id)
        step = info.steps[position]
        cost = StepCost()
        if position > 0:
            prev = self._step_value(execution_id, position - 1)
            if prev is None:  # cycle through an earlier step of this batch
                cost.carry_status = PARTIAL
                cost.carry_warnings = {"cycle"}
            else:
                cost.carry_known = prev.carry_known
                cost.carry_status = prev.carry_status
                cost.carry_missing = dict(prev.carry_missing)
                cost.carry_warnings = set(prev.carry_warnings)

        step_consumed = info.consumed.get(position, [])
        if not step_consumed and _completed(step):
            named = _named_input_lots(step)
            if named:
                cost.carry_status = worst(cost.carry_status, PARTIAL)
                for item_id, name in named:
                    lot = self._get_lot(item_id)
                    cost.carry_missing[str(item_id)] = lot.name if lot is not None else name
                cost.carry_warnings.add("no_flow_history")
                cost.statuses.append(PARTIAL)

        for c in step_consumed:
            lot = self._get_lot(c.inventory_item_id)
            if lot is None:
                cost.carry_warnings.add("input_lot_missing")
                continue
            u = self._lot_value(lot)
            q = _d(c.quantity)
            known = q * u.unit_known if u.unit_known is not None else ZERO
            status = u.status if u.status != UNKNOWN else PARTIAL
            cost.carry_known += known
            cost.carry_status = worst(cost.carry_status, status)
            cost.carry_missing.update(u.missing)
            cost.carry_warnings |= u.warnings
            cost.statuses.append(status)
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
                    "internal": lot.id in info.internal,
                    "_known": known,
                }
            )

        step_outs = info.outs.get(position, [])
        if not step_outs:
            return cost
        weights, assumed = self._split_weights(step, step_outs)
        cost.split_assumed = assumed
        amounts = _allocate(cost.carry_known, step_outs, weights)
        for f in step_outs:
            w = weights[f.id]
            if w == 0:
                a = Alloc(ZERO, ACTUAL, {}, set(), ZERO)
            else:
                a = Alloc(amounts[f.id], cost.carry_status, dict(cost.carry_missing), set(cost.carry_warnings), w)
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
        # the outputs absorb the whole pool
        cost.absorbed_missing = cost.carry_missing
        cost.absorbed_warnings = cost.carry_warnings
        cost.carry_known, cost.carry_status, cost.carry_missing, cost.carry_warnings = ZERO, ACTUAL, {}, set()
        return cost

    @staticmethod
    def _logical_output(flow: CostFlow, lot: InventoryItem | None) -> tuple:
        """Which output of the step a flow belongs to — never inferred from a name.

        A declared output is its definition id. Without one, the only flows that are one output
        are an output's reconciled part and its surplus lot, which records the untracked lot it
        was reconciled into; anything else stands alone.
        """
        if flow.source_output_id:
            return ("id", str(flow.source_output_id))
        if flow.kind == "reconciled_in":
            return ("reconciled", str(flow.inventory_item_id))
        target = (lot.extra_data or {}).get("reconciled_untracked_item_id") if lot is not None else None
        if target:
            return ("reconciled", str(target))
        return ("flow", str(flow.id))

    def _quantity_in(self, flow: CostFlow, unit: str | None) -> Decimal | None:
        lot = self._get_lot(flow.inventory_item_id)
        if lot is None or not unit:
            return None
        factor = self._unit_factor(unit, lot.unit)  # lot units in one `unit`
        return _d(flow.quantity) / factor if factor else None

    def _split_weights(self, step: ExecutionStep, outs: list[CostFlow]) -> tuple[dict, bool]:
        """Spec "split_weights": a weight per output flow summing to 1, and whether it was assumed.

        Shares belong to logical outputs (one step output definition), not to flows: an output
        partly reconciled into an untracked lot and partly new stock is two flows of one
        output, which share that output's weight by quantity.
        """
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
        candidates = [f for f in outs if not is_library(f)] or [f for f in outs if is_library(f)]

        groups: dict[tuple, list[CostFlow]] = {}
        for f in candidates:
            groups.setdefault(self._logical_output(f, lots[f.id]), []).append(f)

        def group_unit(key):
            lot = lots[groups[key][0].id]
            return lot.unit if lot is not None else None

        def group_quantity(key, unit):
            values = [self._quantity_in(f, unit) for f in groups[key]]
            return None if any(v is None for v in values) else sum(values, ZERO)

        percent, byproduct, free = {}, [], []
        for key in groups:
            cfg = _cost_share(defs.get(key[1])) if key[0] == "id" else None
            if cfg is None:
                free.append(key)
            elif cfg == "byproduct":
                byproduct.append(key)
            else:
                percent[key] = cfg
        assumed = False
        if not percent and not free:
            free, byproduct, assumed = byproduct, [], True

        group_weight = {key: ZERO for key in groups}
        total_percent = sum(percent.values(), ZERO)
        if percent and (total_percent > HUNDRED or not free):
            for key, v in percent.items():
                group_weight[key] = v / total_percent
        else:
            for key, v in percent.items():
                group_weight[key] = v / HUNDRED
            rest = (HUNDRED - total_percent) / HUNDRED
            if free and rest > 0:
                if len(free) == 1:
                    group_weight[free[0]] = rest
                else:
                    base = group_unit(free[0])
                    sizes = {key: group_quantity(key, base) for key in free}
                    if all(v is not None for v in sizes.values()) and sum(sizes.values(), ZERO) > 0:
                        total = sum(sizes.values(), ZERO)
                        for key, v in sizes.items():
                            group_weight[key] = rest * v / total
                    else:
                        primary = min(free, key=lambda key: min(_primary_key(f, lots[f.id]) for f in groups[key]))
                        group_weight[primary] = rest
                        assumed = True

        for key, flows in groups.items():
            gw = group_weight[key]
            if gw == 0:
                continue
            if len(flows) == 1:
                weights[flows[0].id] = gw
                continue
            unit = group_unit(key)
            sizes = {f.id: self._quantity_in(f, unit) for f in flows}
            if any(v is None for v in sizes.values()):
                sizes = {f.id: _d(f.quantity) for f in flows}
            total = sum(sizes.values(), ZERO)
            for f in flows:
                weights[f.id] = gw * sizes[f.id] / total if total > 0 else gw / len(flows)
        return weights, assumed

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
        if value.is_finite() and ZERO < value <= HUNDRED:
            return value
    return None


def _primary_key(flow: CostFlow, lot: InventoryItem | None):
    rank = _TYPE_RANK.get(lot.inventory_type if lot is not None else "", 3)
    return (rank, -_d(flow.quantity), flow.created_at, str(flow.id))


def _allocate(pool: Decimal, outs: list[CostFlow], weights: dict) -> dict:
    """Quantise each share to 4 dp; the rounding remainder goes to the largest weight
    (ties: the earliest flow by (created_at, id))."""
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
