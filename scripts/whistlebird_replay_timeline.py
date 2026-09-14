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
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.engine import Connection

import whistlebird_migration as wm

DEFAULT_RAW_MATERIAL_MANIFEST = Path(__file__).parents[1] / "docs" / "whistlebird-raw-material-source.json"


@dataclass(frozen=True)
class ReplayEvent:
    """One API call the replay client will make, plus everything needed to order it."""

    event_id: str
    event_type: str  # "create_execution" | "complete_step" | "create_inventory_item"
    real_date: date
    depends_on: tuple[str, ...]
    payload: dict[str, Any] = field(default_factory=dict)


def _load_raw_material_manifest(path: Path) -> tuple[list[dict[str, Any]], dict[int, list[str]]]:
    """Return (all purchase records, {global_vat: [codes purchased for it]})."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = list(payload.get("clean_records", [])) + list(payload.get("inferred_records", []))
    codes_by_vat: dict[int, list[str]] = defaultdict(list)
    for record in payload.get("inferred_records", []):
        consumed = record.get("consumed_by")
        if consumed and "global_vat" in consumed:
            codes_by_vat[int(consumed["global_vat"])].append(record["code"])
    return records, dict(codes_by_vat)


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
        payload={"record": record, "marker": f"raw-{code}" if is_legacy else f"raw-botanical-{record['code']}"},
    )


def _batch_events(
    batch: wm.ProductionBatch, purchase_event_by_code: dict[str, str], marker_by_vat: dict[int, str]
) -> list[ReplayEvent]:
    step_keys = wm.RHUBARB_GIN_STEP_KEYS if batch.product_line == "rosella" else wm.BOTANICAL_GIN_STEP_KEYS
    raw_dates = [batch.steps[key].step_date if key in batch.steps else None for key in step_keys]
    resolved, _adjusted = wm._monotonic_step_dates(raw_dates)

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
        events.append(
            ReplayEvent(
                event_id=step_id,
                event_type="complete_step",
                real_date=resolved[index],
                depends_on=tuple(depends),
                payload={"batch": batch, "step_key": key, "step_index": index},
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

    raw_records, codes_by_vat = _load_raw_material_manifest(raw_material_manifest_path)
    merged = _enrich_ingredient_codes(merged, codes_by_vat)

    events: list[ReplayEvent] = []

    purchase_event_by_code: dict[str, str] = {}
    for legacy_record in legacy_raw_materials:
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
        events.extend(_batch_events(batch, purchase_event_by_code, marker_by_vat))

    for trial in trials:
        events.extend(_trial_events(trial))

    events.extend(_customs_events(customs_rows))

    return date_prioritised_topological_sort(events)
