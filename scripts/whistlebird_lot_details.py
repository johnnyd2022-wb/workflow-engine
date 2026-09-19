"""Give every whistlebird_test inventory lot the batch code and process link its own history proves.

The Live Inventory page reads a lot's `supplier_batch_number`, `expiry_date` and process name off
the inventory item itself. The replay recorded the underlying facts elsewhere, so the page showed
"No batch number" and "Process: —" for lots the Source Map and the consumption history describe
perfectly well:

* **Produced lots** (bottled product, finished gin, VAT batches, trial library stock). The
  production batch lives on the completing step (`execution_data.batch_label`, e.g. ``VAT56``) and
  a labelled lot's pre-printed label-roll number lives in `extra_data.batch_number`. Neither is the
  lot's `supplier_batch_number`, which is the one first-class batch column and the only one the page
  shows. This pass sets it to ``<label roll> (<production batch>)``, e.g. ``6 (VAT56)``, or to the
  production batch alone where there is no label roll. The label roll number is not unique per
  product (one roll spans several VATs), while `(org, name, supplier_batch_number)` is, so the
  production batch is what keeps two lots of the same product apart.
* **Raw-material lots.** Consumption events already name the process that used a lot, but the lot
  carries no link of its own. This pass tags each lot with `extra_data.producing_process_name`
  (and `producing_process_id` when exactly one process applies) -- the same tag the app's "Add
  missing input" flow puts on stock created for a process, and the one the API turns into
  `process_name` -- from the processes that declare the material as a step input plus every process
  that actually consumed the lot.

Expiry is deliberately *not* touched here: `expiry_date` is written verbatim from the curated
sources when a lot is purchased (`whistlebird_replay._execute_purchase`), and every source expiry
already lands. A lot with no expiry has none in any source; this pass will not invent one.

Like the timestamp pass this is internal tooling for the disposable demo tenant, run after the
replay (`whistlebird_rebuild_api.py` does), and it is idempotent, so it can also be run on its own
against an existing tenant without a reset:

    uv run python scripts/whistlebird_lot_details.py plan   --target-url postgresql://...
    uv run python scripts/whistlebird_lot_details.py apply  --target-url postgresql://...
    uv run python scripts/whistlebird_lot_details.py verify --target-url postgresql://...

It never overwrites a batch code someone already set, and it only writes non-quantity columns, so
stock levels and the audit trail are untouched.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

sys.path.insert(0, str(Path(__file__).parent))
import whistlebird_migration as wm  # noqa: E402
import whistlebird_replay as replay  # noqa: E402

_PRODUCED_TYPES = ("work_in_progress", "final_product")
_PROCESS_KEYS = ("producing_process_id", "producing_process_name")


class LotDetailsError(RuntimeError):
    """The lots cannot be given unambiguous details; nothing was written."""


@dataclass(frozen=True)
class BatchChange:
    item_id: UUID
    name: str
    code: str


@dataclass(frozen=True)
class ProcessTagChange:
    item_id: UUID
    name: str
    processes: tuple[tuple[UUID, str], ...]  # (id, name), by name

    def tag(self) -> dict[str, str]:
        tag = {"producing_process_name": ", ".join(name for _, name in self.processes)}
        if len(self.processes) == 1:
            tag["producing_process_id"] = str(self.processes[0][0])
        return tag


@dataclass(frozen=True)
class LotDetailsPlan:
    batch_changes: tuple[BatchChange, ...]
    process_changes: tuple[ProcessTagChange, ...]
    produced_lots: int
    raw_lots: int
    raw_lots_without_process: tuple[str, ...]  # names, for the report

    def summary(self) -> dict[str, Any]:
        return {
            "produced_lots": self.produced_lots,
            "batch_codes_to_set": len(self.batch_changes),
            "raw_lots": self.raw_lots,
            "process_tags_to_set": len(self.process_changes),
            "raw_lots_with_no_known_process": sorted(set(self.raw_lots_without_process)),
        }


def production_lot_code(batch_label: str | None, label_batch: Any) -> str | None:
    """The batch code a produced lot shows: ``<label roll> (<production batch>)``, or just the batch."""
    label = (batch_label or "").strip()
    label_roll = str(label_batch).strip() if label_batch is not None else ""
    if label_roll and label:
        return f"{label_roll} ({label})"
    if label_roll:
        return label_roll
    return label or None


def _material_key(name: str) -> str:
    return replay._canonical_material_name(name)


def _org_id(conn: Connection, org_name: str) -> UUID:
    org_id = conn.execute(text("SELECT id FROM organisations WHERE name = :name"), {"name": org_name}).scalar()
    if org_id is None:
        raise LotDetailsError(f"organisation {org_name!r} does not exist")
    return org_id


def _declared_processes(conn: Connection, org_id: UUID) -> dict[str, dict[UUID, str]]:
    """Canonical material name -> {process id: process name} for every declared step input."""
    declared: dict[str, dict[UUID, str]] = defaultdict(dict)
    rows = conn.execute(
        text(
            "SELECT p.id, p.name, s.inputs FROM processes p JOIN steps s ON s.process_id = p.id "
            "WHERE p.org_id = :org_id"
        ),
        {"org_id": org_id},
    ).all()
    for process_id, process_name, inputs in rows:
        for entry in inputs or []:
            name = entry.get("name") if isinstance(entry, dict) else None
            if name:
                declared[_material_key(name)][process_id] = process_name
    return declared


def _consuming_processes(conn: Connection, org_id: UUID) -> dict[UUID, dict[UUID, str]]:
    """Inventory item id -> {process id: process name} for every process that consumed it."""
    consumers: dict[UUID, dict[UUID, str]] = defaultdict(dict)
    rows = conn.execute(
        text(
            "SELECT e.entity_id, p.id, p.name FROM entity_events e "
            "JOIN processes p ON p.id = CAST(e.payload ->> 'process_id' AS uuid) AND p.org_id = e.org_id "
            "WHERE e.org_id = :org_id AND e.event_type = 'inventory_item.consumed' "
            "AND e.payload ->> 'process_id' IS NOT NULL"
        ),
        {"org_id": org_id},
    ).all()
    for item_id, process_id, process_name in rows:
        consumers[item_id][process_id] = process_name
    return consumers


def _linked_processes(name: str, item_id: UUID, declared: dict, consumers: dict) -> tuple[tuple[UUID, str], ...]:
    merged = {**declared.get(_material_key(name), {}), **consumers.get(item_id, {})}
    return tuple(sorted(merged.items(), key=lambda pair: (pair[1], str(pair[0]))))


def _current_tag(extra_data: dict[str, Any] | None) -> dict[str, Any]:
    return {key: (extra_data or {}).get(key) for key in _PROCESS_KEYS if (extra_data or {}).get(key)}


def plan_lot_details(conn: Connection, org_id: UUID) -> LotDetailsPlan:
    declared = _declared_processes(conn, org_id)
    consumers = _consuming_processes(conn, org_id)

    raw_rows = conn.execute(
        text(
            "SELECT id, name, extra_data FROM inventory_items "
            "WHERE org_id = :org_id AND inventory_type = 'raw_material' ORDER BY name, purchase_date, id"
        ),
        {"org_id": org_id},
    ).all()
    process_changes: list[ProcessTagChange] = []
    unlinked: list[str] = []
    for item_id, name, extra_data in raw_rows:
        processes = _linked_processes(name, item_id, declared, consumers)
        if not processes:
            unlinked.append(name)
            continue
        change = ProcessTagChange(item_id, name, processes)
        if _current_tag(extra_data) != change.tag():
            process_changes.append(change)

    produced_rows = conn.execute(
        text(
            "SELECT i.id, i.name, i.supplier_batch_number, i.extra_data, s.execution_data ->> 'batch_label' "
            "FROM inventory_items i "
            "LEFT JOIN execution_steps s ON s.id = i.source_execution_step_id AND s.org_id = i.org_id "
            "WHERE i.org_id = :org_id AND i.inventory_type = ANY(:types) ORDER BY i.name, i.created_at, i.id"
        ),
        {"org_id": org_id, "types": list(_PRODUCED_TYPES)},
    ).all()
    taken = {
        (name, batch)
        for name, batch in conn.execute(
            text(
                "SELECT name, supplier_batch_number FROM inventory_items "
                "WHERE org_id = :org_id AND supplier_batch_number IS NOT NULL"
            ),
            {"org_id": org_id},
        ).all()
    }
    batch_changes: list[BatchChange] = []
    collisions: list[str] = []
    for item_id, name, existing, extra_data, batch_label in produced_rows:
        if existing:
            continue  # someone (or an earlier run) already set it; never overwrite
        code = production_lot_code(batch_label, (extra_data or {}).get("batch_number"))
        if code is None:
            continue
        if (name, code) in taken:
            collisions.append(f"{name!r} {code!r}")
            continue
        taken.add((name, code))
        batch_changes.append(BatchChange(item_id, name, code))
    if collisions:
        raise LotDetailsError(
            "two lots of one product would share a batch code (the database allows one per name): "
            + "; ".join(sorted(collisions))
        )

    return LotDetailsPlan(
        batch_changes=tuple(batch_changes),
        process_changes=tuple(process_changes),
        produced_lots=len(produced_rows),
        raw_lots=len(raw_rows),
        raw_lots_without_process=tuple(unlinked),
    )


def apply_plan(conn: Connection, org_id: UUID, plan: LotDetailsPlan) -> None:
    """Non-quantity column writes only; `updated_at` is left alone so the dated audit trail stays true."""
    for change in plan.batch_changes:
        conn.execute(
            text(
                "UPDATE inventory_items SET supplier_batch_number = :code "
                "WHERE id = :id AND org_id = :org_id AND supplier_batch_number IS NULL"
            ),
            {"code": change.code, "id": change.item_id, "org_id": org_id},
        )
    for change in plan.process_changes:
        conn.execute(
            text(
                "UPDATE inventory_items "
                "SET extra_data = (COALESCE(extra_data, CAST('{}' AS jsonb)) - 'producing_process_id' "
                "- 'producing_process_name') || CAST(:tag AS jsonb) "
                "WHERE id = :id AND org_id = :org_id"
            ),
            {"tag": json.dumps(change.tag()), "id": change.item_id, "org_id": org_id},
        )


def _require_test_tenant(org_name: str) -> None:
    if org_name != wm.RESET_ORG_NAME:
        raise LotDetailsError(f"lot details may only be written for {wm.RESET_ORG_NAME!r}, not {org_name!r}")


def plan_for_target(target_url: str, org_name: str) -> LotDetailsPlan:
    _require_test_tenant(org_name)
    engine = create_engine(target_url)
    try:
        with engine.connect() as conn:
            return plan_lot_details(conn, _org_id(conn, org_name))
    finally:
        engine.dispose()


def apply_lot_details(target_url: str, org_name: str) -> dict[str, Any]:
    """Plan and write in one transaction; a rerun finds nothing left to do."""
    _require_test_tenant(org_name)
    engine = create_engine(target_url)
    try:
        with engine.begin() as conn:
            org_id = _org_id(conn, org_name)
            plan = plan_lot_details(conn, org_id)
            apply_plan(conn, org_id, plan)
    finally:
        engine.dispose()
    return plan.summary()


def verify_lot_details(target_url: str, org_name: str) -> dict[str, Any]:
    """Read-only. Each figure is a count of lots still missing something the history proves; expect 0."""
    _require_test_tenant(org_name)
    engine = create_engine(target_url)
    try:
        with engine.connect() as conn:
            org_id = _org_id(conn, org_name)
            plan = plan_lot_details(conn, org_id)
            consumers = _consuming_processes(conn, org_id)
            tags = dict(
                conn.execute(
                    text(
                        "SELECT id, extra_data ->> 'producing_process_name' FROM inventory_items "
                        "WHERE org_id = :org_id AND inventory_type = 'raw_material'"
                    ),
                    {"org_id": org_id},
                ).all()
            )
    finally:
        engine.dispose()
    # A lot's Process must name every process its consumption history names, or the sheet's
    # "Process" line and its audit history contradict each other.
    contradicted = sum(
        1
        for item_id, used_by in consumers.items()
        if item_id in tags and not {name for name in used_by.values()} <= set((tags[item_id] or "").split(", "))
    )
    return {
        "lot_batch_codes_missing": {"expected": 0, "actual": len(plan.batch_changes)},
        "lot_process_links_missing": {"expected": 0, "actual": len(plan.process_changes)},
        "lot_process_contradicts_consumption": {"expected": 0, "actual": contradicted},
    }


def _arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("plan", "apply", "verify"))
    parser.add_argument("--target-url", default=os.environ.get("BIZE_MIGRATION_DATABASE_URL"))
    parser.add_argument("--org-name", default=wm.RESET_ORG_NAME)
    args = parser.parse_args(argv)
    if not args.target_url:
        parser.error("--target-url is required (or set BIZE_MIGRATION_DATABASE_URL)")
    return args


def main(argv: list[str] | None = None) -> int:
    args = _arguments(argv)
    try:
        if args.command == "plan":
            report: dict[str, Any] = plan_for_target(args.target_url, args.org_name).summary()
        elif args.command == "apply":
            report = apply_lot_details(args.target_url, args.org_name)
        else:
            report = verify_lot_details(args.target_url, args.org_name)
    except LotDetailsError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
