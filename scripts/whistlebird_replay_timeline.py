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
from dataclasses import dataclass, field
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

# Day after the last real purchases_gns row (2025-04-01, 100L, "Southern Grain Spirits").
# Batches macerating before this date draw from that real legacy purchase pool (see
# whistlebird_replay.MarkerStore.consume_available_raw_material); batches on or after it
# get their own dedicated, formula-sized purchase (see _ngs_purchase_event) so the real
# legacy pool is never double-counted against production it didn't actually fund.
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


def _ngs_purchase_event(batch: wm.ProductionBatch, governing_date: date) -> ReplayEvent | None:
    """A dedicated NGS purchase for batches the real legacy `purchases_gns` purchases
    can't reach (see NGS_LEGACY_POOL_CUTOFF). Sized to exactly this batch's own computed
    need (flask charge + VAT fill), dated 3 days before its governing date -- the same
    "resolved by context" convention already used for post-cutoff botanicals (see
    docs/whistlebird-raw-material-source.json's _comment and
    docs/whistlebird-import-decisions.md).
    """
    if batch.product_line not in ("wildflower", "solstice") or governing_date < NGS_LEGACY_POOL_CUTOFF:
        return None
    flask_ngs, _flask_water = _flask_ngs_and_water_l()
    fill_ngs, _fill_water = _vat_fill_ngs_and_water_l(batch.product_line)
    record = {
        "code": f"NGS-{batch.marker}",
        "ingredient": "Neutral grain spirit",
        "quantity": str(flask_ngs + fill_ngs),
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
        enriched.append(
            wm.ProductionBatch(
                global_vat=batch.global_vat,
                product_line=batch.product_line,
                batch_label=batch.batch_label,
                steps=batch.steps,
                vat_volume_l=batch.vat_volume_l,
                vat_abv=batch.vat_abv,
                bottlings=batch.bottlings,
                ingredient_codes=combined,
                base_vat=batch.base_vat,
                extra_data=batch.extra_data,
            )
        )
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


def _resolved_step_dates(batch: wm.ProductionBatch) -> list[date]:
    step_keys = wm.RHUBARB_GIN_STEP_KEYS if batch.product_line == "rosella" else wm.BOTANICAL_GIN_STEP_KEYS
    raw_dates = [batch.steps[key].step_date if key in batch.steps else None for key in step_keys]
    resolved, _adjusted = wm._monotonic_step_dates(raw_dates)
    return resolved


def count_dedicated_ngs_purchases(batches: list[wm.ProductionBatch]) -> int:
    """How many `_ngs_purchase_event` will fire across `batches` -- used by
    `whistlebird_migration.build_import_verification` so its expected raw-material count
    includes these without duplicating the cutoff/formula logic there."""
    return sum(1 for batch in batches if _ngs_purchase_event(batch, _resolved_step_dates(batch)[0]) is not None)


def _batch_events(
    batch: wm.ProductionBatch,
    purchase_event_by_code: dict[str, str],
    marker_by_vat: dict[int, str],
    known_quantities: dict[str, tuple[str, str]],
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
    ngs_purchase = _ngs_purchase_event(batch, resolved[0])
    if ngs_purchase is not None:
        events.append(ngs_purchase)
    prev_step_id = exec_id
    for index, key in enumerate(step_keys):
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
        if key == "maceration":
            # A post-cutoff batch's formula-sized NGS receipt is not just dated before
            # this step: it is the stock this step must draw. Keep that relationship
            # explicit so a future date correction cannot accidentally reorder the API
            # calls into an impossible consume-before-purchase sequence.
            if ngs_purchase is not None:
                depends.append(ngs_purchase.event_id)
            flask_ngs, flask_water = _flask_ngs_and_water_l()
            payload["ngs_quantity_l"] = str(flask_ngs)
            payload["other_material_inputs"] = [
                {"name": "Water", "quantity": str(flask_water), "unit": "L"},
                *_foraged_botanical_inputs(batch.product_line),
            ]
        if key == "aging" and batch.product_line != "rosella":
            fill_ngs, fill_water = _vat_fill_ngs_and_water_l(batch.product_line)
            payload["ngs_quantity_l"] = str(fill_ngs)
            payload["other_material_inputs"] = [{"name": "Water", "quantity": str(fill_water), "unit": "L"}]
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

    manifest_batches, _excluded = wm._load_manifest(production_manifest_path)
    merged = wm._merge_batches(legacy_batches, manifest_batches)

    raw_records, codes_by_vat, known_quantity_by_vat = _load_raw_material_manifest(raw_material_manifest_path)
    merged = _enrich_ingredient_codes(merged, codes_by_vat)

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
    for batch in merged:
        events.extend(
            _batch_events(
                batch,
                purchase_event_by_code,
                marker_by_vat,
                known_quantity_by_vat.get(batch.global_vat, {}),
            )
        )

    for trial in trials:
        events.extend(_trial_events(trial))

    events.extend(_customs_events(customs_rows))

    return date_prioritised_topological_sort(events)
