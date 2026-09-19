"""In-memory run of the replay's raw-material allocation, using the replay's own code.

The replay draws botanical lots one maceration step at a time. Whether a step used an expired
lot, or ran short, only shows up after a full rebuild against a live tenant. This module runs
the same functions the replay runs -- `_execute_purchase`, `_ingredient_inputs_for_step`,
`_recipe_fallback_inputs`, `allocate_fifo_lots` -- against in-memory lots, driven by the same
`build_timeline()` events, so the answer is known from the repository alone:

* `simulate(events)` returns every lot use, every unbacked shortfall, and each lot's remainder.
* `plan_restock(...)` and `plan_disposals(...)` derive the two curated inputs that make "no expired
  ingredient is used" true: modelled restock purchases for demand that only expired lots could have
  met, and the disposals of stock left over once its lot has expired.

    uv run python scripts/whistlebird_replay_simulation.py plan            # read-only report
    uv run python scripts/whistlebird_replay_simulation.py plan --write    # update the manifests
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
import whistlebird_disposals as disposals  # noqa: E402
import whistlebird_legacy as legacy  # noqa: E402
import whistlebird_migration as wm  # noqa: E402
import whistlebird_replay as replay  # noqa: E402
from whistlebird_replay_timeline import DEFAULT_RAW_MATERIAL_MANIFEST, ReplayEvent, build_timeline  # noqa: E402

DEFAULT_DISPOSALS_MANIFEST = disposals.DEFAULT_DISPOSALS_MANIFEST
MACERATION_STEPS = ("maceration", "rhubarb_maceration")
# An inferred purchase is dated this many days before the maceration it feeds -- the convention the
# existing `resolved_by_context` records follow (docs/whistlebird-raw-material-source.json _comment).
RESTOCK_LEAD_DAYS = 3


@dataclass
class SimLot:
    marker: str
    name: str
    unit: str
    quantity: Decimal
    purchase_date: date | None
    expiry_date: date | None
    ingredient_code: str | None
    supplier: str | None
    order: int
    last_used: date | None = None

    def as_row(self) -> dict[str, Any]:
        return {
            "id": self.marker,
            "name": self.name,
            "unit": self.unit,
            "quantity": self.quantity,
            "expiry_date": self.expiry_date,
            "ingredient_code": self.ingredient_code,
        }


@dataclass(frozen=True)
class Use:
    on: date
    lot: str
    name: str
    quantity: Decimal
    expiry_date: date | None
    batch: str


@dataclass(frozen=True)
class Shortfall:
    on: date
    batch: str
    name: str
    quantity: Decimal
    unit: str


@dataclass(frozen=True)
class ExpiredGap:
    """Demand that only lots already expired on `on` could have met."""

    on: date
    batch: str
    global_vat: int
    product_line: str
    name: str
    quantity: Decimal
    unit: str


@dataclass
class Simulation:
    lots: dict[str, SimLot] = field(default_factory=dict)
    uses: list[Use] = field(default_factory=list)
    shortfalls: list[Shortfall] = field(default_factory=list)
    gaps: list[ExpiredGap] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    referenced_codes: set[str] = field(default_factory=set)

    @property
    def uses_after_expiry(self) -> list[Use]:
        return [u for u in self.uses if u.expiry_date is not None and u.on > u.expiry_date]


class _SimStore:
    """The slice of MarkerStore the maceration path uses, over in-memory lots."""

    def __init__(self, sim: Simulation):
        self.sim = sim
        self._context: tuple[ReplayEvent, Any] | None = None

    def existing_inventory_item_id(self, marker: str) -> str | None:
        return marker if marker in self.sim.lots else None

    def _fifo_rows(self) -> list[dict[str, Any]]:
        lots = [lot for lot in self.sim.lots.values() if lot.quantity > 0]
        lots.sort(key=lambda lot: (lot.purchase_date is None, lot.purchase_date or date.min, lot.order))
        return [lot.as_row() for lot in lots]

    def consume_available_raw_material_up_to(self, name, quantity_needed, unit, as_of=None, reserved_codes=frozenset()):
        rows = self._fifo_rows()
        allocated, short = replay.allocate_fifo_lots(rows, name, quantity_needed, unit, as_of, reserved_codes)
        # What the pre-expiry-aware allocator would have done from the same stock: the difference
        # is demand that only an expired lot could have met.
        _, short_ignoring_expiry = replay.allocate_fifo_lots(rows, name, quantity_needed, unit, None, reserved_codes)
        gap = short - short_ignoring_expiry
        if gap > 0 and self._context is not None:
            event, batch = self._context
            self.sim.gaps.append(
                ExpiredGap(event.real_date, batch.marker, batch.global_vat, batch.product_line, name, gap, unit)
            )
        return allocated, short

    def raw_material_for_ingredient_code(self, code: str):
        for lot in self.sim.lots.values():
            if lot.ingredient_code == code:
                return (lot.marker, lot.name)
        return None


class _SimClient:
    """Captures the one call the simulation needs: creating a raw-material lot."""

    def __init__(self, sim: Simulation):
        self.sim = sim

    def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        if path != "/api/core/inventory" or body.get("inventory_type") != "raw_material":
            return {}
        metadata = body.get("metadata") or {}
        marker = metadata["import_ref"]
        purchase = body.get("purchase_date")
        expiry = body.get("expiry_date")
        self.sim.lots[marker] = SimLot(
            marker=marker,
            name=body["name"],
            unit=body["unit"],
            quantity=Decimal(str(body["quantity"])),
            purchase_date=date.fromisoformat(purchase) if purchase else None,
            expiry_date=date.fromisoformat(expiry) if expiry else None,
            ingredient_code=metadata.get("ingredient_code"),
            supplier=body.get("supplier"),
            order=len(self.sim.lots),
        )
        return {}


def simulate(events: list[ReplayEvent]) -> Simulation:
    sim = Simulation()
    store = _SimStore(sim)
    client = _SimClient(sim)
    for event in events:
        if event.event_type == "create_inventory_item":
            replay._execute_purchase(client, store, event)
            continue
        if event.event_type != "complete_step":
            continue
        batch = event.payload.get("batch")
        if batch is None:
            continue
        sim.referenced_codes.update(batch.ingredient_codes)
        if event.payload["step_key"] not in MACERATION_STEPS:
            continue
        store._context = (event, batch)
        try:
            precise = replay._ingredient_inputs_for_step(store, event.payload.get("known_input_quantities", {}))
            fallback = (
                []
                if batch.product_line == "rosella"
                else replay._recipe_fallback_inputs(
                    store, batch, precise, event.real_date, event.payload.get("reserved_ingredient_codes", frozenset())
                )
            )
        except replay.ReplayRejectedError as exc:
            sim.errors.append(f"{batch.marker} on {event.real_date}: {exc}")
            continue
        finally:
            store._context = None
        for item in [*precise, *fallback]:
            quantity = Decimal(str(item["quantity"]))
            lot = sim.lots.get(item.get("inventory_item_id", ""))
            if lot is None:
                sim.shortfalls.append(Shortfall(event.real_date, batch.marker, item["name"], quantity, item["unit"]))
                continue
            if lot.quantity < quantity:
                # The live replay's API call would refuse this: insufficient stock.
                sim.errors.append(
                    f"{batch.marker} on {event.real_date}: {lot.marker} holds {lot.quantity}, needs {quantity}"
                )
                continue
            lot.quantity -= quantity
            lot.last_used = event.real_date
            sim.uses.append(Use(event.real_date, lot.marker, lot.name, quantity, lot.expiry_date, batch.marker))
    return sim


# --- planning ---------------------------------------------------------------------------


def _code_parts(code: str) -> tuple[str, int] | None:
    match = re.fullmatch(r"([A-Za-z]+)(\d+)", code)
    return (match.group(1), int(match.group(2))) if match else None


def plan_restock(sim: Simulation) -> list[dict[str, Any]]:
    """One modelled `resolved_by_context` purchase per (batch, ingredient) that only expired lots could feed."""
    used_codes = {lot.ingredient_code for lot in sim.lots.values() if lot.ingredient_code} | sim.referenced_codes
    next_number: dict[str, int] = defaultdict(int)
    prefix_by_name: dict[str, str] = {}
    supplier_by_name: dict[str, str | None] = {}
    for lot in sorted(sim.lots.values(), key=lambda lot: lot.order):
        key = replay._canonical_material_name(lot.name)
        if lot.ingredient_code and (parts := _code_parts(lot.ingredient_code)):
            prefix_by_name.setdefault(key, parts[0])
        if lot.supplier:
            supplier_by_name[key] = lot.supplier
    for code in used_codes:
        if parts := _code_parts(code):
            next_number[parts[0]] = max(next_number[parts[0]], parts[1])

    grouped: dict[tuple[str, str], list[ExpiredGap]] = defaultdict(list)
    for gap in sim.gaps:
        grouped[(gap.batch, replay._canonical_material_name(gap.name))].append(gap)

    records: list[dict[str, Any]] = []
    for (_batch, key), gaps in sorted(grouped.items(), key=lambda kv: (kv[1][0].on, kv[0])):
        first = gaps[0]
        prefix = prefix_by_name.get(key)
        if prefix is None:
            raise ValueError(f"no ingredient code prefix known for {first.name!r}")
        next_number[prefix] += 1
        quantity = sum((g.quantity for g in gaps), Decimal("0"))
        records.append(
            {
                "code": f"{prefix}{next_number[prefix]:03d}",
                "ingredient": replay._canonical_material_display_name(first.name),
                "quantity": _number(quantity),
                "unit": first.unit,
                "date": (first.on - timedelta(days=RESTOCK_LEAD_DAYS)).isoformat(),
                "confidence": "resolved_by_context",
                "supplier": supplier_by_name.get(key),
                "supplier_order_ref": None,
                "supplier_batch_number": None,
                "price_nzd": None,
                "source": (
                    f"derived: {first.product_line} VAT{first.global_vat} maceration requirement; the "
                    f"{_number(quantity)} {first.unit} that only lots already past their recorded expiry could "
                    "have supplied is modelled as a fresh purchase, no email/DB purchase evidence"
                ),
                "consumed_by": {"global_vat": first.global_vat, "product": first.product_line},
            }
        )
    return records


def _number(value: Decimal) -> int | float:
    normalized = value.normalize()
    return int(normalized) if normalized == normalized.to_integral_value() else float(normalized)


def plan_disposals(sim: Simulation, through: date) -> list[dict[str, Any]]:
    """Every lot with stock left whose expiry is on or before `through`, disposed once it is both
    expired and no longer used (the later of its expiry and its last use)."""
    disposals: list[dict[str, Any]] = []
    for lot in sorted(sim.lots.values(), key=lambda lot: (lot.expiry_date or date.max, lot.order)):
        if lot.expiry_date is None or lot.expiry_date > through or lot.quantity <= 0:
            continue
        disposed_on = max(lot.expiry_date, lot.last_used or lot.expiry_date)
        disposals.append(
            {
                "lot": lot.marker,
                "ingredient": lot.name,
                "quantity": _number(lot.quantity),
                "unit": lot.unit,
                "date": disposed_on.isoformat(),
                "reason": f"Expired {lot.expiry_date.isoformat()}",
            }
        )
    return disposals


def check_disposals(sim: Simulation, listed: tuple[disposals.Disposal, ...]) -> list[str]:
    """Problems that would make the replay's disposals fail or mis-state history, found up front."""
    problems: list[str] = []
    for disposal in listed:
        lot = sim.lots.get(disposal.lot)
        if lot is None:
            problems.append(f"disposals: {disposal.lot} is not a lot the replay creates")
        elif lot.unit != disposal.unit or lot.quantity != disposal.quantity:
            problems.append(
                f"disposals: {disposal.lot} would hold {lot.quantity} {lot.unit}, manifest expects "
                f"{disposal.quantity} {disposal.unit}"
            )
        elif lot.last_used is not None and disposal.on < lot.last_used:
            problems.append(
                f"disposals: {disposal.lot} is disposed on {disposal.on}, before its last use {lot.last_used}"
            )
    return problems


def check_replay_plan(
    legacy_source: Any,
    production_manifest: Path,
    raw_material_manifest: Path,
    listed: tuple[disposals.Disposal, ...],
) -> list[str]:
    """Everything the simulation can prove before a rebuild touches the tenant."""
    sim = simulate(build_timeline(legacy_source, production_manifest, raw_material_manifest))
    problems = [f"stock: {message}" for message in sim.errors]
    problems += [
        f"expiry: {u.lot} used on {u.on} by {u.batch}, after it expired on {u.expiry_date}"
        for u in sim.uses_after_expiry
    ]
    problems += [f"expiry: {g.name} for {g.batch} on {g.on} has no unexpired stock" for g in sim.gaps]
    problems += check_disposals(sim, listed)
    return problems


# --- CLI --------------------------------------------------------------------------------


def _summary(sim: Simulation) -> str:
    late = sim.uses_after_expiry
    return (
        f"lots {len(sim.lots)} | uses {len(sim.uses)} | uses after expiry {len(late)} | "
        f"lot-less shortfalls {len(sim.shortfalls)} | expired-only gaps {len(sim.gaps)} | errors {len(sim.errors)}"
    )


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan", help="Report (or --write) the restock purchases and disposals.")
    plan.add_argument("--through", type=date.fromisoformat, default=date(2026, 9, 19))
    plan.add_argument("--write", action="store_true", help="Update the manifests in docs/.")
    plan.add_argument("--legacy-source", default=legacy.DEFAULT_LEGACY_SNAPSHOT)
    plan.add_argument("--production-manifest", type=Path, default=wm.DEFAULT_PRODUCTION_MANIFEST)
    plan.add_argument("--raw-material-manifest", type=Path, default=DEFAULT_RAW_MATERIAL_MANIFEST)
    plan.add_argument("--disposals-manifest", type=Path, default=DEFAULT_DISPOSALS_MANIFEST)
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    events = build_timeline(args.legacy_source, args.production_manifest, args.raw_material_manifest)
    sim = simulate(events)
    print("before:", _summary(sim))
    restock = plan_restock(sim)
    print(f"restock purchases needed: {len(restock)} ({sum(Decimal(str(r['quantity'])) for r in restock)} g)")
    if not args.write:
        for record in restock[:8]:
            print(
                f"  {record['date']}  {record['code']}  {record['ingredient']}  {record['quantity']} {record['unit']}"
            )
        return 0

    payload = json.loads(args.raw_material_manifest.read_text(encoding="utf-8"))
    existing = {r["code"] for r in payload["inferred_records"]}
    payload["inferred_records"].extend(r for r in restock if r["code"] not in existing)
    args.raw_material_manifest.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    after = simulate(build_timeline(args.legacy_source, args.production_manifest, args.raw_material_manifest))
    print("after restock:", _summary(after))
    disposals = plan_disposals(after, args.through)
    doc = {
        "_comment": (
            "Lots disposed of as expired, replayed through the real wastage API (POST /api/core/inventory/wastage) "
            "after the Core history by scripts/whistlebird_disposals.py. `lot` is the lot's import marker; "
            "`quantity` is what the replay expects to be left in it (the replay refuses to dispose a different "
            "amount); `date` is the later of the lot's expiry and its last use, so no disposal precedes a use. "
            "Generated by `scripts/whistlebird_replay_simulation.py plan --write`."
        ),
        "disposals": disposals,
    }
    args.disposals_manifest.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {len(disposals)} disposals to {args.disposals_manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
