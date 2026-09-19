"""Build the ordered event timeline the API-replay client executes against.

Pure data transformation: reads the same sources `whistlebird_migration.py` already
reads (the prior database, the production-sheet manifest, the raw-material manifest)
and produces one `ReplayEvent` list in an order that satisfies every hard dependency
(an execution must exist before its steps; step N before step N+1; a raw-material
purchase before the first step that consumes it; a Rosella base batch's vat-producing
step before its linked conversion's rhubarb-maceration step) while otherwise following
real chronological order as closely as the curated dates allow.

No network or database writes happen here -- this module only reads and computes. See
`scripts/whistlebird_replay.py` for the client that executes the resulting timeline
against the real application API, and `scripts/whistlebird_replay_correct_timestamps.py`
for the after-script that stamps real historical timestamps onto the rows it created.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

import whistlebird_migration as wm
from sqlalchemy import create_engine

DEFAULT_RAW_MATERIAL_MANIFEST = Path(__file__).parents[1] / "docs" / "whistlebird-raw-material-source.json"

# --- Neutral grain spirit (NGS) / dilution-water / foraged-botanical recipe -----------
#
# Founder-specified recipe (2026-09-16), applied as a fixed formula to every Wildflower/
# Solstice batch -- the distillery doesn't record these per-VAT, it follows a constant
# recipe, so unlike the botanical purchase manifest (which curates real per-batch receipt
# evidence) these are computed, not looked up. See docs/whistlebird-import-decisions.md
# for the full writeup, including the water-quantity correction (30.397L for Wildflower's
# VAT fill, superseding an earlier 29.124L reading off the Production sheet -- the founder
# confirmed a 1.273L "pyrex + tube" top-up line was added to the real recipe later to
# correct for contraction, after that reading was taken).
_NGS_STOCK_ABV = Decimal("0.964")  # purchases_gns.abv -- every legacy NGS purchase is 96.4%
_QUANT3 = Decimal("0.001")
_QUANT4 = Decimal("0.0001")

# The legacy purchase register records four Juniper receipts without an origin.  The
# product recipes, however, have always called for the Macedonian and Himalayan
# botanicals separately.  Do not expose a third, generic Juniper stock identity just
# because that older source omitted its origin: split those receipts deterministically
# in the same ratio as the founder-confirmed recipe demand across the replayed batches.
# The original receipt name and the allocation basis remain attached as metadata.
_GENERIC_JUNIPER_NAME = "juniper berries"
_JUNIPER_VARIANTS = ("Juniper Berries (Macedonian)", "Juniper Berries (Himalayan)")

# Retained for compatibility with the original fixture tests.  The production allocator
# now uses every dated legacy receipt before creating a deterministic shortfall receipt.
NGS_LEGACY_POOL_CUTOFF = date(2025, 4, 2)

# Foraged/untracked botanicals, per shot (founder, 2026-09-16); doubled below, same
# 2-shots-per-VAT convention as the tracked recipe (see the "Founder-confirmed 2026-09-14"
# note in docs/whistlebird-raw-material-source.json's _comment). Never purchased --
# recorded as "other materials" inputs, not real inventory items.
_FORAGED_BOTANICALS_PER_SHOT: dict[str, tuple[tuple[str, Decimal, str], ...]] = {
    "wildflower": (
        ("Lemon juice", Decimal("17"), "mL"),
        ("Grapefruit (pink) juice", Decimal("27"), "mL"),
        ("Lemon peel", Decimal("1.5"), "g"),
    ),
    "solstice": (
        ("Kawakawa leaf", Decimal("4"), "g"),
        ("Orange peel", Decimal("2.5"), "g"),
        ("Orange juice", Decimal("54"), "mL"),
    ),
}


def _round3(value: Decimal) -> Decimal:
    return value.quantize(_QUANT3, rounding=ROUND_HALF_UP)


def _flask_ngs_and_water_l() -> tuple[Decimal, Decimal]:
    """Each VAT distils 2 flasks of 1.8L @ 20% ABV; the raw NGS in each flask is diluted
    from the 96.4% purchased stock, the rest is water. Identical for Wildflower and
    Solstice -- returns (total NGS litres, total water litres) for both flasks combined.
    """
    flask_volume = Decimal("1.8")
    flask_abv = Decimal("0.20")
    flasks_per_vat = 2
    ngs_per_flask = _round3(flask_volume * flask_abv / _NGS_STOCK_ABV)
    water_per_flask = _round3(flask_volume - ngs_per_flask)
    return ngs_per_flask * flasks_per_vat, water_per_flask * flasks_per_vat


def _vat_fill_ngs_and_water_l(product_line: str) -> tuple[Decimal, Decimal]:
    """Post-distillation VAT fill that dilutes the concentrate to label strength.
    Returns (total NGS litres, total water litres)."""
    if product_line == "wildflower":
        ngs = Decimal("24.456")
        water = Decimal("30.397")
        # Wildflower only: a 1.260L top-up of 66.6% ethanol, cut from the same NGS stock.
        topup_volume = Decimal("1.260")
        topup_abv = Decimal("0.666")
        topup_ngs = _round3(topup_volume * topup_abv / _NGS_STOCK_ABV)
        topup_water = _round3(topup_volume - topup_ngs)
        return ngs + topup_ngs, water + topup_water
    if product_line == "solstice":
        return Decimal("17.776"), Decimal("25.064")
    raise ValueError(f"no VAT-fill recipe for product line {product_line!r}")


def _foraged_botanical_inputs(product_line: str) -> list[dict[str, Any]]:
    per_shot = _FORAGED_BOTANICALS_PER_SHOT.get(product_line, ())
    return [{"name": name, "quantity": str(quantity * 2), "unit": unit} for name, quantity, unit in per_shot]


def _ngs_required_l(batch: wm.ProductionBatch) -> Decimal:
    flask_ngs, _flask_water = _flask_ngs_and_water_l()
    fill_ngs, _fill_water = _vat_fill_ngs_and_water_l(batch.product_line)
    return flask_ngs + fill_ngs


def _ngs_purchase_event(
    batch: wm.ProductionBatch, governing_date: date, quantity_l: Decimal | None = None
) -> ReplayEvent | None:
    """Create only the deterministic NGS shortfall for a botanical VAT.

    ``quantity_l=None`` retains the old isolated-fixture behaviour.  The complete
    timeline always supplies the calculated shortfall after allocating dated legacy NGS
    receipts, so it never duplicates genuine stock with a formula-sized purchase.
    """
    if batch.product_line not in ("wildflower", "solstice"):
        return None
    if quantity_l is None:
        if governing_date < NGS_LEGACY_POOL_CUTOFF:
            return None
        quantity_l = _ngs_required_l(batch)
    if quantity_l <= 0:
        return None
    record = {
        "code": f"NGS-{batch.marker}",
        "ingredient": "Neutral grain spirit",
        "quantity": str(quantity_l),
        "unit": "L",
        "date": (governing_date - timedelta(days=3)).isoformat(),
        "supplier": "Southern Grain Spirits",
        "supplier_batch_number": None,
        "expiry_date": None,
    }
    return _purchase_event(record)


@dataclass(frozen=True)
class ReplayEvent:
    """One API call the replay client will make, plus everything needed to order it."""

    event_id: str
    event_type: str  # "create_execution" | "complete_step" | "create_inventory_item"
    real_date: date
    depends_on: tuple[str, ...]
    payload: dict[str, Any] = field(default_factory=dict)


def _load_raw_material_manifest(
    path: Path,
) -> tuple[list[dict[str, Any]], dict[int, list[str]], dict[int, dict[str, tuple[str, str]]]]:
    """Return (all purchase records, {global_vat: [codes purchased for it]},
    {global_vat: {code: (quantity, unit)}} -- only for records with a known exact
    per-batch amount, i.e. the inferred tier. See whistlebird-replay-plan.md's
    "real constraint that changes scope" note for why clean-tier/legacy codes never
    appear in the third return value.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = list(payload.get("clean_records", [])) + list(payload.get("inferred_records", []))
    codes_by_vat: dict[int, list[str]] = defaultdict(list)
    known_quantity_by_vat: dict[int, dict[str, tuple[str, str]]] = defaultdict(dict)
    for record in payload.get("inferred_records", []):
        consumed = record.get("consumed_by")
        if consumed and "global_vat" in consumed:
            vat = int(consumed["global_vat"])
            codes_by_vat[vat].append(record["code"])
            known_quantity_by_vat[vat][record["code"]] = (str(record["quantity"]), record["unit"])
    return records, dict(codes_by_vat), dict(known_quantity_by_vat)


def _enrich_ingredient_codes(
    batches: list[wm.ProductionBatch], codes_by_vat: dict[int, list[str]]
) -> list[wm.ProductionBatch]:
    """Attach the raw-material manifest's per-batch codes onto manifest-sourced batches.

    Legacy-DB batches already carry real `ingredient_codes` from `product_actions_flavors`;
    this only adds codes for VAT27+ batches, which the production-sheet manifest never sets
    (see `_load_manifest`'s `ingredient_codes=()`).
    """
    enriched = []
    for batch in batches:
        extra_codes = codes_by_vat.get(batch.global_vat, [])
        if not extra_codes:
            enriched.append(batch)
            continue
        combined = tuple(sorted(set(batch.ingredient_codes) | set(extra_codes)))
        # dataclasses.replace (not a field-by-field reconstruction) so every other field
        # -- including pending_steps -- passes through unchanged even as the dataclass
        # grows new fields later; a manual field list silently drops whatever it forgets.
        enriched.append(replace(batch, ingredient_codes=combined))
    return enriched


def _purchase_event(record: dict[str, Any]) -> ReplayEvent:
    is_legacy = "source_table" in record
    if is_legacy:
        code = f"legacy-{record['source_table']}-{record['source_id']}"
    else:
        code = record["code"]
    event_id = f"purchase:{code}"
    real_date = date.fromisoformat(record["date"] if isinstance(record["date"], str) else record["date"].isoformat())
    return ReplayEvent(
        event_id=event_id,
        event_type="create_inventory_item",
        real_date=real_date,
        depends_on=(),
        payload={"record": record, "marker": f"raw-{code}" if is_legacy else f"raw-manifest-{record['code']}"},
    )


def _split_legacy_generic_juniper_receipts(
    records: list[wm.RawMaterialRecord], batches: list[wm.ProductionBatch]
) -> list[wm.RawMaterialRecord]:
    """Replace origin-unspecified legacy Juniper with the two recipe botanicals.

    The old receipts establish a real total quantity but cannot evidence which of the
    two Juniper origins each gram belonged to. The only defensible deterministic basis
    is the known quantity demanded by the replayed Wildflower and Solstice recipes.
    This allocation is recorded in metadata rather than presented as source evidence.
    """
    demand = {variant: Decimal("0") for variant in _JUNIPER_VARIANTS}
    for batch in batches:
        if batch.product_line not in {"wildflower", "solstice"}:
            continue
        recipe = (
            wm._WILDFLOWER_MACERATION_INPUTS
            if batch.product_line == "wildflower"
            else wm._SOLSTICE_MACERATION_INPUTS
        )
        for ingredient in recipe:
            if ingredient["name"] in demand:
                demand[ingredient["name"]] += Decimal(str(ingredient["quantity"]))

    total_demand = sum(demand.values(), Decimal("0"))
    if total_demand <= 0:
        raise ValueError("cannot split generic Juniper without recipe demand")

    transformed: list[wm.RawMaterialRecord] = []
    for record in records:
        if " ".join(record.name.lower().split()) != _GENERIC_JUNIPER_NAME:
            transformed.append(record)
            continue

        # Round the first component to the stored inventory precision and give the
        # exact remainder to the second, preserving every source receipt total.
        macedonian = (record.quantity * demand[_JUNIPER_VARIANTS[0]] / total_demand).quantize(_QUANT4)
        components = (
            (_JUNIPER_VARIANTS[0], macedonian),
            (_JUNIPER_VARIANTS[1], record.quantity - macedonian),
        )
        for variant, quantity in components:
            if quantity <= 0:
                continue
            extra_data = {
                **record.extra_data,
                "source_material_name": record.name,
                "origin_allocation": "proportional_to_founder_confirmed_recipe_demand",
            }
            transformed.append(
                replace(
                    record,
                    source_id=f"{record.source_id}-{variant.rsplit(' ', 1)[-1].strip('()').lower()}",
                    name=variant,
                    quantity=quantity,
                    extra_data=extra_data,
                )
            )
    return transformed


# --- Label-batch numbering (sales FIFO groundwork) ------------------------------------
#
# Whistlebird buys pre-printed label rolls of 500 -- physically, the first 500 bottles of
# a product ever labelled are "batch 1", the next 500 are "batch 2", and so on, regardless
# of which VAT they came from. Founder request (2026-09-17): number every product line's
# bottles this way at Labelling, so a future FIFO sales allocation (e.g. from Xero invoice
# dates) can drain "batch 1" before "batch 2" the same way the physical labels were used.
# See docs/whistlebird-import-decisions.md and app/core/db/repositories/inventory_repo.py's
# consume_final_product_fifo, which is the thing that eventually drains these.
LABEL_BATCH_SIZE = Decimal("500")


def _assign_flask_codes(batches: list[wm.ProductionBatch]) -> dict[str, tuple[str, str]]:
    """Allocate the two physical flask codes used by each Wildflower/Solstice VAT.

    Codes are line-specific and advance in distillation-date order (with the global VAT
    as a stable tie-breaker), rather than the arbitrary order in which the legacy and
    sheet records happened to be loaded.  A process step represents both physical
    flasks, so its required ``Flask code`` prompt receives the two codes as a pair.
    """
    prefixes = {"wildflower": "WBWF", "solstice": "WBSS"}
    assignments: dict[str, tuple[str, str]] = {}
    for product_line, prefix in prefixes.items():
        entries = [(_resolved_step_dates(batch)[1], batch) for batch in batches if batch.product_line == product_line]
        entries.sort(key=lambda entry: (entry[0], entry[1].global_vat))
        next_code = 1
        for _distillation_date, batch in entries:
            assignments[batch.marker] = (f"{prefix}{next_code:02d}", f"{prefix}{next_code + 1:02d}")
            next_code += 2
    return assignments


def _assign_label_batches(
    batches: list[wm.ProductionBatch], batch_size: Decimal = LABEL_BATCH_SIZE
) -> dict[str, list[tuple[int, Decimal]]]:
    """FIFO-number every product line's bottles into fixed-size label batches, in real
    production order (each product line's own labelling dates, oldest first; global_vat
    breaks ties on the same date). Returns {batch.marker: [(batch_number, bottle_count),
    ...]} -- almost always one entry per batch, more when a VAT's own bottle run happens
    to straddle a 500-bottle boundary.
    """
    by_product: dict[str, list[tuple[date, wm.ProductionBatch, Decimal]]] = defaultdict(list)
    for batch in batches:
        total_bottles = sum((Decimal(str(b["bottles"])) for b in batch.bottlings), Decimal("0"))
        if total_bottles <= 0:
            continue
        labelling_date = _resolved_step_dates(batch)[-1]
        by_product[batch.product_line].append((labelling_date, batch, total_bottles))

    assignment: dict[str, list[tuple[int, Decimal]]] = {}
    for entries in by_product.values():
        entries.sort(key=lambda entry: (entry[0], entry[1].global_vat))
        cumulative = Decimal("0")
        for _labelling_date, batch, total_bottles in entries:
            splits: list[tuple[int, Decimal]] = []
            remaining = total_bottles
            position = cumulative
            while remaining > 0:
                batch_number = int(position // batch_size) + 1
                room_in_batch = batch_size - (position % batch_size)
                take = min(remaining, room_in_batch)
                splits.append((batch_number, take))
                position += take
                remaining -= take
            assignment[batch.marker] = splits
            cumulative += total_bottles
    return assignment


def _resolved_step_dates(batch: wm.ProductionBatch) -> list[date]:
    step_keys = wm.RHUBARB_GIN_STEP_KEYS if batch.product_line == "rosella" else wm.BOTANICAL_GIN_STEP_KEYS
    raw_dates = [batch.steps[key].step_date if key in batch.steps else None for key in step_keys]
    resolved, _adjusted = wm._monotonic_step_dates(raw_dates)
    return resolved


def manifest_ngs_receipts(raw_records: list[dict[str, Any]]) -> list[wm.RawMaterialRecord]:
    """Real Neutral grain spirit receipts sourced from the raw-material manifest.

    Southern Grain Spirits' full purchase history (2023-04-24 onward) lives in
    ``docs/whistlebird-raw-material-source.json`` now, not the legacy ``purchases_gns``
    table (see the manifest's own ``_comment``) -- this is what makes NGS pooling in
    ``_ngs_allocations`` independent of legacy-DB access. ``source_id`` is unused by
    that pool (only ``source_date``/``quantity``/``name`` are read), so it's a
    placeholder rather than a real legacy row id.
    """
    return [
        wm.RawMaterialRecord(
            source_table="raw_material_manifest",
            source_id=0,
            source_date=date.fromisoformat(record["date"]),
            name=record["ingredient"],
            quantity=Decimal(str(record["quantity"])),
            unit=record["unit"],
            supplier=record.get("supplier"),
            supplier_batch_number=record.get("supplier_batch_number"),
            expiry_date=None,
            extra_data={},
        )
        for record in raw_records
        if record.get("ingredient") == "Neutral grain spirit"
    ]


def _ngs_allocations(
    batches: list[wm.ProductionBatch], legacy_raw_materials: list[wm.RawMaterialRecord]
) -> dict[str, tuple[Decimal, Decimal]]:
    """Return ``{batch_marker: (legacy_pool_l, generated_shortfall_l)}``.

    Allocation is chronological by maceration date and global VAT, with each source
    receipt becoming available only on its recorded date.  This preserves real stock,
    consumes it before generating any inferred NGS, and is stable across every replay.
    """
    receipts = sorted(
        (
            (record.source_date, Decimal(str(record.quantity)))
            for record in legacy_raw_materials
            if record.name == "Neutral grain spirit" and record.quantity > 0
        ),
        key=lambda entry: entry[0],
    )
    botanical_batches = sorted(
        (batch for batch in batches if batch.product_line in ("wildflower", "solstice")),
        key=lambda batch: (_resolved_step_dates(batch)[0], batch.global_vat),
    )
    receipt_index = 0
    available = Decimal("0")
    allocations: dict[str, tuple[Decimal, Decimal]] = {}
    for batch in botanical_batches:
        governing_date = _resolved_step_dates(batch)[0]
        while receipt_index < len(receipts) and receipts[receipt_index][0] <= governing_date:
            available += receipts[receipt_index][1]
            receipt_index += 1
        required = _ngs_required_l(batch)
        from_legacy = min(required, available)
        available -= from_legacy
        allocations[batch.marker] = (from_legacy, required - from_legacy)
    return allocations


def count_dedicated_ngs_purchases(
    batches: list[wm.ProductionBatch], legacy_raw_materials: list[wm.RawMaterialRecord]
) -> int:
    """Count only batches that need an inferred NGS shortfall receipt."""
    return sum(1 for _legacy, shortfall in _ngs_allocations(batches, legacy_raw_materials).values() if shortfall > 0)


def _batch_events(
    batch: wm.ProductionBatch,
    purchase_event_by_code: dict[str, str],
    marker_by_vat: dict[int, str],
    known_quantities: dict[str, tuple[str, str]],
    label_batches: dict[str, list[tuple[int, Decimal]]] | None = None,
    flask_codes: dict[str, tuple[str, str]] | None = None,
    ngs_allocation: tuple[Decimal, Decimal] | None = None,
) -> list[ReplayEvent]:
    step_keys = wm.RHUBARB_GIN_STEP_KEYS if batch.product_line == "rosella" else wm.BOTANICAL_GIN_STEP_KEYS
    resolved = _resolved_step_dates(batch)

    exec_id = f"exec:{batch.marker}"
    events = [
        ReplayEvent(
            event_id=exec_id,
            event_type="create_execution",
            real_date=resolved[0],
            depends_on=(),
            payload={"batch": batch},
        )
    ]
    if batch.product_line in ("wildflower", "solstice"):
        legacy_ngs_remaining, generated_ngs_remaining = ngs_allocation or (Decimal("0"), _ngs_required_l(batch))
    else:
        legacy_ngs_remaining, generated_ngs_remaining = Decimal("0"), Decimal("0")
    ngs_purchase = _ngs_purchase_event(batch, resolved[0], generated_ngs_remaining)
    if ngs_purchase is not None:
        events.append(ngs_purchase)
    prev_step_id = exec_id
    for index, key in enumerate(step_keys):
        if key in batch.pending_steps:
            # Real, still-in-progress work: this step and every step after it (a suffix,
            # enforced by _load_manifest) haven't happened yet. Stop completing steps here
            # -- the execution and everything already done stay real; the rest is left
            # PENDING in the target, same as a real user mid-process.
            break
        step_id = f"step:{batch.marker}:{key}"
        depends: list[str] = [prev_step_id]
        if key in ("maceration", "rhubarb_maceration"):
            for code in batch.ingredient_codes:
                dep = purchase_event_by_code.get(code)
                if dep:
                    depends.append(dep)
            if key == "rhubarb_maceration" and batch.base_vat is not None:
                base_marker = marker_by_vat.get(batch.base_vat)
                if base_marker is None:
                    raise ValueError(f"Rosella {batch.marker} needs base VAT{batch.base_vat}, which was never loaded")
                depends.append(f"step:{base_marker}:aging")
        payload: dict[str, Any] = {"batch": batch, "step_key": key, "step_index": index}
        if key in ("maceration", "rhubarb_maceration"):
            payload["known_input_quantities"] = {
                code: known_quantities[code] for code in batch.ingredient_codes if code in known_quantities
            }
        ngs_needed = Decimal("0")
        if key == "maceration":
            # A post-cutoff batch's formula-sized NGS receipt is not just dated before
            # this step: it is the stock this step must draw. Keep that relationship
            # explicit so a future date correction cannot accidentally reorder the API
            # calls into an impossible consume-before-purchase sequence.
            if ngs_purchase is not None:
                depends.append(ngs_purchase.event_id)
            flask_ngs, flask_water = _flask_ngs_and_water_l()
            ngs_needed = flask_ngs
            payload["other_material_inputs"] = [
                {"name": "Water", "quantity": str(flask_water), "unit": "L"},
                *_foraged_botanical_inputs(batch.product_line),
            ]
        if key == "aging" and batch.product_line != "rosella":
            fill_ngs, fill_water = _vat_fill_ngs_and_water_l(batch.product_line)
            ngs_needed = fill_ngs
            payload["other_material_inputs"] = [{"name": "Water", "quantity": str(fill_water), "unit": "L"}]
        if ngs_needed:
            from_legacy = min(ngs_needed, legacy_ngs_remaining)
            legacy_ngs_remaining -= from_legacy
            from_generated = ngs_needed - from_legacy
            generated_ngs_remaining -= from_generated
            if from_legacy:
                payload["legacy_ngs_quantity_l"] = str(from_legacy)
            if from_generated:
                assert ngs_purchase is not None
                payload["dedicated_ngs_marker"] = ngs_purchase.payload["marker"]
                payload["dedicated_ngs_quantity_l"] = str(from_generated)
        if key == "distilling" and flask_codes and batch.marker in flask_codes:
            payload["flask_codes"] = flask_codes[batch.marker]
        if key in ("bottling", "labelling") and label_batches:
            splits = label_batches.get(batch.marker)
            if splits:
                payload["label_batches"] = [(number, str(quantity)) for number, quantity in splits]
        events.append(
            ReplayEvent(
                event_id=step_id,
                event_type="complete_step",
                real_date=resolved[index],
                depends_on=tuple(depends),
                payload=payload,
            )
        )
        prev_step_id = step_id
    return events


def _trial_events(trial: wm.TrialRecord) -> list[ReplayEvent]:
    exec_id = f"trial-exec:{trial.marker}"
    events = [
        ReplayEvent(
            event_id=exec_id,
            event_type="create_execution",
            real_date=trial.source_date,
            depends_on=(),
            payload={"trial": trial},
        )
    ]
    prev = exec_id
    for index, key in enumerate(wm.TRIAL_STEP_KEYS):
        step_id = f"trial-step:{trial.marker}:{key}"
        events.append(
            ReplayEvent(
                event_id=step_id,
                event_type="complete_step",
                real_date=trial.source_date,
                depends_on=(prev,),
                payload={"trial": trial, "step_key": key, "step_index": index},
            )
        )
        prev = step_id
    return events


def _customs_events(rows: list[dict[str, Any]]) -> list[ReplayEvent]:
    events = []
    for row in rows:
        events.append(
            ReplayEvent(
                event_id=f"customs:{row['id']}",
                event_type="create_customs_lodgement",
                real_date=row["date"],
                depends_on=(),
                payload={"row": dict(row)},
            )
        )
    return events


def date_prioritised_topological_sort(events: list[ReplayEvent]) -> list[ReplayEvent]:
    """Kahn's algorithm, always picking the earliest-dated ready event next.

    Guarantees every `depends_on` edge is honoured; raises if the graph has a cycle
    (a real bug in the curated data or the dependency wiring, not something to paper
    over) or if an event depends on an id that was never produced.
    """
    by_id = {e.event_id: e for e in events}
    for event in events:
        for dep in event.depends_on:
            if dep not in by_id:
                raise ValueError(f"{event.event_id} depends on unknown event {dep!r}")

    remaining_deps = {e.event_id: set(e.depends_on) for e in events}
    dependents: dict[str, list[str]] = defaultdict(list)
    for event in events:
        for dep in event.depends_on:
            dependents[dep].append(event.event_id)

    ready = [eid for eid, deps in remaining_deps.items() if not deps]
    ordered: list[ReplayEvent] = []
    seen = set()
    while ready:
        ready.sort(key=lambda eid: (by_id[eid].real_date, eid))
        eid = ready.pop(0)
        seen.add(eid)
        ordered.append(by_id[eid])
        for dependent in dependents.get(eid, []):
            remaining_deps[dependent].discard(eid)
            if not remaining_deps[dependent] and dependent not in seen and dependent not in ready:
                ready.append(dependent)

    if len(ordered) != len(events):
        stuck = sorted(set(by_id) - seen)
        raise ValueError(f"dependency cycle or unresolved deps involving: {stuck[:10]}")
    return ordered


def build_timeline(
    legacy_url: str,
    production_manifest_path: Path,
    raw_material_manifest_path: Path = DEFAULT_RAW_MATERIAL_MANIFEST,
) -> list[ReplayEvent]:
    engine = create_engine(legacy_url)
    with engine.connect() as connection:
        legacy_batches = wm._legacy_batches(connection)
        trials = list(wm._trial_records(connection))
        customs_rows = wm._customs_lodgement_rows(connection)
        legacy_raw_materials = wm._disambiguate_reused_supplier_batches(list(wm._raw_material_records(connection)))
    engine.dispose()

    # Neutral grain spirit's full purchase history now lives in the raw-material
    # manifest (see its _comment), not the legacy purchases_gns table -- drop it here
    # so it's never double-purchased across both sources, and so NGS handling in this
    # replay no longer depends on legacy-DB access at all.
    legacy_raw_materials = [record for record in legacy_raw_materials if record.name != "Neutral grain spirit"]

    manifest_batches, _excluded = wm._load_manifest(production_manifest_path)
    merged = wm._merge_batches(legacy_batches, manifest_batches)

    raw_records, codes_by_vat, known_quantity_by_vat = _load_raw_material_manifest(raw_material_manifest_path)
    merged = _enrich_ingredient_codes(merged, codes_by_vat)
    legacy_raw_materials = _split_legacy_generic_juniper_receipts(legacy_raw_materials, merged)
    ngs_allocations = _ngs_allocations(merged, manifest_ngs_receipts(raw_records))

    events: list[ReplayEvent] = []

    purchase_event_by_code: dict[str, str] = {}
    for legacy_record in legacy_raw_materials:
        if legacy_record.quantity <= 0:
            # purchases_ingredients id 17 ("liquorice root", LR001) is recorded with
            # ingredients_amount = 0 in the legacy database -- a genuine pre-existing
            # data anomaly (a zero purchase contributes nothing to inventory either
            # way), not something this replay introduces. The real API correctly
            # rejects a non-positive quantity ("quantity must be greater than 0"),
            # which is exactly the kind of thing the old ORM-direct script's bypass of
            # the endpoint silently let through. Skip rather than fabricate a number.
            continue
        event = _purchase_event(
            {
                "source_table": legacy_record.source_table,
                "source_id": legacy_record.source_id,
                "date": legacy_record.source_date.isoformat(),
                "name": legacy_record.name,
                "quantity": str(legacy_record.quantity),
                "unit": legacy_record.unit,
                "supplier": legacy_record.supplier,
                "supplier_batch_number": legacy_record.supplier_batch_number,
                "expiry_date": legacy_record.expiry_date.isoformat() if legacy_record.expiry_date else None,
                "extra_data": legacy_record.extra_data,
            }
        )
        events.append(event)
        code = legacy_record.extra_data.get("ingredient_code")
        if code:
            purchase_event_by_code[code] = event.event_id
    for record in raw_records:
        event = _purchase_event(record)
        events.append(event)
        purchase_event_by_code[record["code"]] = event.event_id

    marker_by_vat = {batch.global_vat: batch.marker for batch in merged}
    label_batches = _assign_label_batches(merged)
    flask_codes = _assign_flask_codes(merged)
    for batch in merged:
        events.extend(
            _batch_events(
                batch,
                purchase_event_by_code,
                marker_by_vat,
                known_quantity_by_vat.get(batch.global_vat, {}),
                label_batches,
                flask_codes,
                ngs_allocations.get(batch.marker),
            )
        )

    for trial in trials:
        events.extend(_trial_events(trial))

    events.extend(_customs_events(customs_rows))

    return date_prioritised_topological_sort(events)
