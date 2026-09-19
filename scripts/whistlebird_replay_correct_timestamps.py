"""Stamp real historical dates onto rows created by scripts/whistlebird_replay.py.

The replay client deliberately never asks the live application for anything but "now" --
that's the whole point of driving it through the real API instead of writing around it
(see docs/whistlebird-replay-plan.md). This script is the second, separate pass: it
recomputes the exact same deterministic event timeline
(`whistlebird_replay_timeline.build_timeline`), and for every row the replay created,
sets its business timestamp columns directly at the database level to the real date
that event actually happened on.

This is internal tooling for populating and resetting a DEMO/TEST tenant only. It is not,
and must never become, a capability the live application exposes to a user -- the API
itself has no backdating path and none should be added to it. Running this script is a
deliberate, one-off maintenance operation against `whistlebird_test`, the same way
--rebuild-whistlebird-test's reset-and-replay is.

No `date_confidence`, `timestamp_policy`, or similar internal-curation language is written
here -- only a plain, real timestamp per row. The curation trail for how each date was
determined lives in docs/whistlebird-import-decisions.md and the JSON manifests, never in
the loaded data itself.

Usage:
    uv run python scripts/whistlebird_replay_correct_timestamps.py \\
        --target-url postgresql://workflow_rw:...@localhost:8401/workflow-engine-test \\
        --org-name whistlebird_test
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).parent))
import whistlebird_legacy as legacy  # noqa: E402
import whistlebird_migration as wm  # noqa: E402
import whistlebird_np3 as np3  # noqa: E402
from whistlebird_replay_timeline import ReplayEvent, build_timeline  # noqa: E402


def _business_at(real_date: date) -> datetime:
    """Same deterministic noon-local convention whistlebird_migration.py already uses
    for every historical timestamp (WB-001) -- reused here rather than reinvented."""
    return wm._derived_timestamp(real_date)


def _marker_of(event: ReplayEvent) -> str | None:
    if event.event_type == "create_inventory_item":
        return event.payload["marker"]
    if event.event_type in ("create_execution", "complete_step"):
        record = event.payload.get("batch") or event.payload.get("trial") or event.payload.get("green_gold")
        return record.marker
    if event.event_type == "create_customs_lodgement":
        return f"customs-{event.payload['row']['id']}"
    return None


def _execution_date_ranges(events: list[ReplayEvent]) -> dict[str, tuple[date, date]]:
    """{marker: (first_step_date, last_step_date)} for every execution/trial."""
    dates_by_marker: dict[str, list[date]] = defaultdict(list)
    for event in events:
        if event.event_type not in ("create_execution", "complete_step"):
            continue
        marker = _marker_of(event)
        dates_by_marker[marker].append(event.real_date)
    return {marker: (min(dates), max(dates)) for marker, dates in dates_by_marker.items()}


def correct_timestamps(
    legacy_source: str | Path,
    target_url: str,
    org_name: str,
    np3_manifest_path: Path | None = np3.DEFAULT_NP3_MANIFEST,
) -> dict[str, int]:
    events = build_timeline(legacy_source, Path(wm.DEFAULT_PRODUCTION_MANIFEST))
    exec_ranges = _execution_date_ranges(events)

    engine = create_engine(target_url)
    counts = {
        "executions": 0,
        "execution_steps": 0,
        "inventory_items": 0,
        "replacement_inventory_items": 0,
        "expiry_wastage": 0,
        "compliance_records": 0,
    }
    with engine.begin() as conn:
        row = conn.execute(text("SELECT id FROM organisations WHERE name = :name"), {"name": org_name}).first()
        if not row:
            raise ValueError(f"org {org_name!r} does not exist")
        org_id = row[0]

        for marker, (first_date, last_date) in exec_ranges.items():
            started_at = _business_at(first_date)
            completed_at = _business_at(last_date)
            result = conn.execute(
                text(
                    "UPDATE executions SET started_at = :started_at, created_at = :started_at, "
                    "completed_at = :completed_at, updated_at = :completed_at "
                    "WHERE org_id = :org_id AND id IN ("
                    "  SELECT DISTINCT execution_id FROM execution_steps "
                    "  WHERE org_id = :org_id AND execution_data->>'batch_ref' = :marker"
                    ")"
                ),
                {"started_at": started_at, "completed_at": completed_at, "org_id": org_id, "marker": marker},
            )
            counts["executions"] += result.rowcount

        for event in events:
            if event.event_type != "complete_step":
                continue
            marker = _marker_of(event)
            step_index = event.payload["step_index"]
            business_at = _business_at(event.real_date)
            result = conn.execute(
                text(
                    "UPDATE execution_steps SET started_at = :at, created_at = :at, "
                    "completed_at = :at, updated_at = :at "
                    "WHERE org_id = :org_id AND execution_id IN ("
                    "  SELECT DISTINCT execution_id FROM execution_steps "
                    "  WHERE org_id = :org_id AND execution_data->>'batch_ref' = :marker"
                    ") AND step_number = :step_number"
                ),
                {"at": business_at, "org_id": org_id, "marker": marker, "step_number": step_index + 1},
            )
            counts["execution_steps"] += result.rowcount

        for event in events:
            if event.event_type != "create_inventory_item":
                continue
            marker = event.payload["marker"]
            business_at = _business_at(event.real_date)
            result = conn.execute(
                text(
                    "UPDATE inventory_items SET created_at = :at, updated_at = :at "
                    "WHERE org_id = :org_id AND extra_data->>'import_ref' = :marker"
                ),
                {"at": business_at, "org_id": org_id, "marker": marker},
            )
            counts["inventory_items"] += result.rowcount

        # Replacement receipts are generated only when an expired/source-short lot
        # cannot meet a documented recipe demand.  They carry their real replay date
        # as metadata because they are created immediately before the consuming step,
        # rather than being a source-manifest purchase event.
        replacement_rows = conn.execute(
            text(
                "SELECT id, extra_data->>'replay_replacement_date' FROM inventory_items "
                "WHERE org_id = :org_id AND extra_data->>'replay_replacement_date' IS NOT NULL"
            ),
            {"org_id": org_id},
        ).fetchall()
        for item_id, raw_date in replacement_rows:
            business_at = _business_at(date.fromisoformat(raw_date))
            result = conn.execute(
                text("UPDATE inventory_items SET created_at = :at, updated_at = :at WHERE id = :id"),
                {"at": business_at, "id": item_id},
            )
            counts["replacement_inventory_items"] += result.rowcount
            conn.execute(
                text("UPDATE inventory_movements SET created_at = :at WHERE inventory_item_id = :id AND type = 'ADD'"),
                {"at": business_at, "id": item_id},
            )

        # Outputs the replay created (VAT batches, bottled product, trial library stock)
        # carry no purchase-manifest marker -- they're identified by which execution step
        # produced them, so backdate them to that step's own real date instead.
        for event in events:
            if event.event_type != "complete_step":
                continue
            marker = _marker_of(event)
            business_at = _business_at(event.real_date)
            result = conn.execute(
                text(
                    "UPDATE inventory_items SET created_at = :at, updated_at = :at "
                    "WHERE org_id = :org_id AND source_execution_step_id IN ("
                    "  SELECT es.id FROM execution_steps es "
                    "  WHERE es.org_id = :org_id AND es.execution_data->>'batch_ref' = :marker "
                    "  AND es.step_number = :step_number"
                    ")"
                ),
                {
                    "at": business_at,
                    "org_id": org_id,
                    "marker": marker,
                    "step_number": event.payload["step_index"] + 1,
                },
            )
            counts["inventory_items"] += result.rowcount

        for event in events:
            if event.event_type != "create_customs_lodgement":
                continue
            marker = _marker_of(event)
            business_at = _business_at(event.real_date)
            result = conn.execute(
                text(
                    "UPDATE compliance_records SET created_at = :at, updated_at = :at "
                    "WHERE org_id = :org_id AND details->>'import_ref' = :marker"
                ),
                {"at": business_at, "org_id": org_id, "marker": marker},
            )
            counts["compliance_records"] += result.rowcount

        for event in events:
            if event.event_type != "record_expiry_wastage":
                continue
            business_at = _business_at(event.real_date)
            key = f"whistlebird-expiry:{event.payload['marker']}"
            result = conn.execute(
                text(
                    "UPDATE inventory_wastage iw SET recorded_at = :at, created_at = :at "
                    "WHERE iw.org_id = :org_id AND iw.id IN ("
                    "  SELECT source_wastage_id FROM inventory_movements "
                    "  WHERE org_id = :org_id AND metadata->>'idempotency_key' = :key"
                    ")"
                ),
                {"at": business_at, "org_id": org_id, "key": key},
            )
            counts["expiry_wastage"] += result.rowcount
            conn.execute(
                text(
                    "UPDATE inventory_movements SET created_at = :at "
                    "WHERE org_id = :org_id AND metadata->>'idempotency_key' = :key"
                ),
                {"at": business_at, "org_id": org_id, "key": key},
            )

    engine.dispose()
    if np3_manifest_path:
        # After the Core transaction commits: a manifest record that was never replayed
        # raises here, and must not roll back the Core dates already corrected above.
        counts["np3_records"] = np3.correct_np3_timestamps(
            target_url, org_name, np3.load_np3_manifest(np3_manifest_path)
        )
    return counts


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--legacy-url",
        "--legacy-source",
        dest="legacy_source",
        default=legacy.DEFAULT_LEGACY_SNAPSHOT,
        help="Where the prior inventory data comes from: a path to a snapshot JSON (default: the committed "
        "docs/whistlebird-legacy-source.json) or a postgresql:// URL to read the live legacy database.",
    )
    parser.add_argument("--target-url", default=os.environ.get("BIZE_MIGRATION_DATABASE_URL"))
    parser.add_argument("--org-name", default=wm.RESET_ORG_NAME)
    parser.add_argument("--np3-manifest", type=Path, default=np3.DEFAULT_NP3_MANIFEST)
    parser.add_argument("--skip-np3", action="store_true", help="Correct Core history only.")
    args = parser.parse_args()
    if not args.target_url:
        parser.error("--target-url is required (or set BIZE_MIGRATION_DATABASE_URL)")
    if args.org_name != wm.RESET_ORG_NAME:
        parser.error(f"--org-name must be exactly {wm.RESET_ORG_NAME!r}")
    return args


def main() -> int:
    args = _arguments()
    result = correct_timestamps(
        args.legacy_source, args.target_url, args.org_name, None if args.skip_np3 else args.np3_manifest
    )
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
