"""In-memory run of the replay's raw-material allocation, using the replay's own code.

The replay draws botanical lots one maceration step at a time. Whether a step used an expired
lot, or ran short, only shows up after a full rebuild against a live tenant. This module runs
the same functions the replay runs -- `_execute_purchase`, `_ingredient_inputs_for_step`,
`_recipe_fallback_inputs`, `allocate_fifo_lots` -- against in-memory lots, driven by the same
`build_timeline()` events, so the answer is known from the repository alone:

* `simulate(events)` returns every lot use, every unbacked shortfall, and each lot's remainder.
* `plan_restock(...)` and `plan_disposals(...)` derive the two curated inputs that make "no expired
  ingredient is used" true: modelled restock purchases for demand that no unexpired lot could meet,
  and the disposals of stock left over once its lot has expired.

A restock is one real-sized pack (`restock_packs` in the raw-material manifest: 500 g of Sumac, 1 kg of
Dried mango, ...), bought only when stock runs out and left unpinned, so it is drawn down FIFO by every
batch that follows and the trace shows the one purchase fanning out to all of them. It is never a lot
sized to a single batch's use.

    uv run python scripts/whistlebird_replay_simulation.py plan            # read-only report
    uv run python scripts/whistlebird_replay_simulation.py plan --write    # update the manifests
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
import tempfile
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
# From this date the legacy database no longer carries the botanical stock (the raw-material manifest
# takes over, and NGS is likewise pooled from here -- see whistlebird_replay_timeline.NGS_LEGACY_POOL_CUTOFF),
# so a recipe with no lot left to draw on is restocked. Before it, a recipe with no lot at all predates every
# receipt and stays an unbacked "other material" line, exactly as it always has.
RESTOCK_FROM = date(2025, 4, 2)


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
    global_vat: int = 0
    product_line: str = ""


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
                sim.shortfalls.append(
                    Shortfall(
                        event.real_date,
                        batch.marker,
                        item["name"],
                        quantity,
                        item["unit"],
                        batch.global_vat,
                        batch.product_line,
                    )
                )
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


@dataclass(frozen=True)
class Pack:
    """The size a botanical is really bought in, and who it is bought from."""

    name: str
    prefix: str
    quantity: Decimal
    unit: str
    supplier: str | None


def load_restock_packs(manifest: Path | dict[str, Any]) -> dict[str, Pack]:
    """`restock_packs` from the raw-material manifest, keyed by canonical material name."""
    payload = manifest if isinstance(manifest, dict) else json.loads(manifest.read_text(encoding="utf-8"))
    packs: dict[str, Pack] = {}
    for name, entry in payload.get("restock_packs", {}).items():
        quantity = Decimal(str(entry["quantity"]))
        if quantity <= 0 or not re.fullmatch(r"[A-Za-z]+", entry["code_prefix"]) or not entry["unit"]:
            raise ValueError(f"restock_packs[{name!r}] needs a positive quantity, a unit and an alphabetic code_prefix")
        packs[replay._canonical_material_name(name)] = Pack(
            name=replay._canonical_material_display_name(name),
            prefix=entry["code_prefix"],
            quantity=quantity,
            unit=entry["unit"],
            supplier=entry.get("supplier"),
        )
    return packs


def is_modelled_record(record: dict[str, Any], packs: dict[str, Pack]) -> bool:
    """A manifest record the planner owns: a pack restock, or the per-batch stand-in it replaces.

    A `consumed_by` record with a `purchase_quantity` is a real receipt (a physical supplier lot label
    was found) and is left alone.
    """
    if "first_needed_by" in record:
        return True
    if "consumed_by" in record and "purchase_quantity" not in record:
        return replay._canonical_material_name(record["ingredient"]) in packs
    return False


def _may_restock(sim: Simulation, shortfall: Shortfall, key: str) -> bool:
    """Is there a receipt history (or a post-legacy date) for a purchase to continue?"""
    if shortfall.on >= RESTOCK_FROM:
        return True
    return any(
        replay._canonical_material_name(lot.name) == key
        and lot.purchase_date is not None
        and lot.purchase_date <= shortfall.on
        for lot in sim.lots.values()
    )


def plan_restock(sim: Simulation, packs: dict[str, Pack]) -> list[dict[str, Any]]:
    """One pack purchase per ingredient, for the earliest demand its stock could not meet.

    Each call adds at most one pack per ingredient: it changes what every later batch draws, so
    the caller re-simulates and asks again until nothing more is short.
    """
    used_codes = {lot.ingredient_code for lot in sim.lots.values() if lot.ingredient_code} | sim.referenced_codes
    next_number: dict[str, int] = defaultdict(int)
    for code in used_codes:
        if parts := _code_parts(code):
            next_number[parts[0]] = max(next_number[parts[0]], parts[1])

    earliest: dict[str, Shortfall] = {}
    for shortfall in sorted(sim.shortfalls, key=lambda s: (s.on, s.batch)):
        key = replay._canonical_material_name(shortfall.name)
        if key in packs and key not in earliest and _may_restock(sim, shortfall, key):
            earliest[key] = shortfall

    records: list[dict[str, Any]] = []
    for key, shortfall in sorted(earliest.items(), key=lambda kv: (kv[1].on, kv[0])):
        pack = packs[key]
        if shortfall.unit != pack.unit:
            raise ValueError(f"{pack.name!r} is short in {shortfall.unit} but its pack is sized in {pack.unit}")
        if shortfall.quantity > pack.quantity:
            raise ValueError(
                f"{shortfall.batch} needs {shortfall.quantity} {shortfall.unit} of {pack.name!r}, more than one "
                f"{pack.quantity} {pack.unit} pack"
            )
        next_number[pack.prefix] += 1
        code = f"{pack.prefix}{next_number[pack.prefix]:03d}"
        records.append(
            {
                "code": code,
                "ingredient": pack.name,
                "quantity": _number(pack.quantity),
                "unit": pack.unit,
                "date": (shortfall.on - timedelta(days=RESTOCK_LEAD_DAYS)).isoformat(),
                "confidence": "resolved_by_context",
                "supplier": pack.supplier,
                "supplier_order_ref": None,
                # Every manifest lot carries its own code as its batch number, so the source map can
                # trace it by batch (docs commit d34ddaf0 did the same for the records it replaced).
                "supplier_batch_number": code,
                "price_nzd": None,
                "source": (
                    f"derived: modelled restock of one {_number(pack.quantity)} {pack.unit} pack, bought when stock "
                    f"ran out; first needed by {shortfall.product_line} VAT{shortfall.global_vat}. No email/DB "
                    "purchase evidence; drawn down FIFO by every later batch, not sized to one"
                ),
                "first_needed_by": {"global_vat": shortfall.global_vat, "product": shortfall.product_line},
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
        f"restock: {r['ingredient']} for VAT{r['first_needed_by']['global_vat']} is short and its pack is not "
        "bought -- re-run `whistlebird_replay_simulation.py plan --write`"
        for r in plan_restock(sim, load_restock_packs(raw_material_manifest))
    ]
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


MAX_RESTOCK_ROUNDS = 50


def _plan_manifest(args: argparse.Namespace, payload: dict[str, Any]) -> tuple[dict[str, Any], Simulation]:
    """Drop every modelled record, then buy one pack at a time until no batch is short.

    Works on a scratch copy of the manifest so a read-only `plan` never touches docs/.
    """
    packs = load_restock_packs(payload)
    payload["inferred_records"] = [r for r in payload["inferred_records"] if not is_modelled_record(r, packs)]
    with tempfile.TemporaryDirectory() as scratch:
        scratch_path = Path(scratch) / "raw-material-source.json"
        for _round in range(MAX_RESTOCK_ROUNDS):
            scratch_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            sim = simulate(build_timeline(args.legacy_source, args.production_manifest, scratch_path))
            restock = plan_restock(sim, packs)
            if not restock:
                return payload, sim
            payload["inferred_records"].extend(restock)
    raise RuntimeError(f"restock did not converge in {MAX_RESTOCK_ROUNDS} rounds")


def main() -> int:
    args = _arguments()
    current = json.loads(args.raw_material_manifest.read_text(encoding="utf-8"))
    print(
        "before:",
        _summary(simulate(build_timeline(args.legacy_source, args.production_manifest, args.raw_material_manifest))),
    )
    payload, sim = _plan_manifest(args, copy.deepcopy(current))
    restock = [r for r in payload["inferred_records"] if "first_needed_by" in r]
    print("after: ", _summary(sim))
    print(f"pack purchases: {len(restock)}")
    for record in restock:
        print(f"  {record['date']}  {record['code']}  {record['ingredient']}  {record['quantity']} {record['unit']}")
    if not args.write:
        return 0

    args.raw_material_manifest.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    disposals_plan = plan_disposals(sim, args.through)
    doc = {
        "_comment": (
            "Lots disposed of as expired, replayed through the real wastage API (POST /api/core/inventory/wastage) "
            "after the Core history by scripts/whistlebird_disposals.py. `lot` is the lot's import marker; "
            "`quantity` is what the replay expects to be left in it (the replay refuses to dispose a different "
            "amount); `date` is the later of the lot's expiry and its last use, so no disposal precedes a use. "
            "Generated by `scripts/whistlebird_replay_simulation.py plan --write`."
        ),
        "disposals": disposals_plan,
    }
    args.disposals_manifest.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {len(restock)} pack purchases and {len(disposals_plan)} disposals")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
