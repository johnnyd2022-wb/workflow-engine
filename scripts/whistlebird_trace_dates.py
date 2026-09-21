"""Give the Whistlebird Ltd replay tenant's remaining actions the date they really happened.

The replay drives the real API, so everything it creates is stamped "now", and
`whistlebird_replay_correct_timestamps.py` then sets the historical dates directly on the
rows. Three things that pass does not reach still show the day the tenant was rebuilt:

* **Production completion inside a lot.** Every produced lot carries
  `extra_data.execution_trace.completed_at` (what the batch sheet and traces read), and the
  lot's events snapshot it. This pass sets it to the date its production step completed.
* **`process_version_date` on `execution.created` events**, which records the process version
  the run used. This pass sets it to that version's (already dated) creation time.
* **Xero sales.** Syncing Xero after a rebuild draws sold stock down FIFO
  (`sales_fifo_consumption`), stamped at sync time. This pass dates each draw, and its
  allocation row, to the invoice date, so the audit list shows when the sale happened.
  A draw is never dated before its lot existed or before the lot's previous draw, so a
  lot's quantity history stays in order; those clamps are counted in the report.

This is internal tooling for the disposable Whistlebird Ltd replay tenant only. It is not,
and must not become, something the application does: in the live app every action is
stamped when it happens, and nothing here changes that. The org name is checked, the pass
is idempotent, and it can be re-run on its own after every Xero sync:

    uv run python scripts/whistlebird_trace_dates.py apply  --target-url postgresql://...
    uv run python scripts/whistlebird_trace_dates.py verify --target-url postgresql://...

`whistlebird_rebuild_api.py` runs it after the lot-details pass.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

sys.path.insert(0, str(Path(__file__).parent))
import whistlebird_migration as wm  # noqa: E402
import whistlebird_replay_correct_timestamps as correct  # noqa: E402

SALES_REASON = "sales_fifo_consumption"
_AFTER_LOT = timedelta(minutes=1)
_AFTER_PREVIOUS_DRAW = timedelta(seconds=1)


class TraceDatesError(RuntimeError):
    """The pass was asked to run somewhere it must not."""


def _require_test_tenant(org_name: str) -> None:
    if org_name != wm.WHISTLEBIRD_ORG_NAME:
        raise TraceDatesError(f"trace dates may only be written for {wm.WHISTLEBIRD_ORG_NAME!r}, not {org_name!r}")


def _org_id(conn: Connection, org_name: str) -> Any:
    org_id = conn.execute(text("SELECT id FROM organisations WHERE name = :name"), {"name": org_name}).scalar()
    if org_id is None:
        raise TraceDatesError(f"organisation {org_name!r} does not exist")
    return org_id


def _stamp(at: datetime) -> str:
    return at.astimezone(UTC).isoformat()


def _date_production_completions(conn: Connection, org_id: Any) -> int:
    """`execution_trace.completed_at` -> the completing step's date (else the lot's own)."""
    rows = conn.execute(
        text(
            "SELECT i.id, COALESCE(s.completed_at, i.created_at), i.extra_data->'execution_trace'->>'completed_at' "
            "FROM inventory_items i LEFT JOIN execution_steps s ON s.id = i.source_execution_step_id "
            "WHERE i.org_id = :org AND i.extra_data->'execution_trace'->>'completed_at' IS NOT NULL"
        ),
        {"org": org_id},
    ).all()
    extra_data_type = _extra_data_type(conn)
    changed = 0
    for item_id, at, current in rows:
        stamp = _stamp(at)
        if current == stamp:
            continue
        params = {"org": org_id, "id": item_id, "stamp": stamp}
        conn.execute(
            text(
                "UPDATE inventory_items SET extra_data = CAST(jsonb_set(CAST(extra_data AS jsonb), "
                "'{execution_trace,completed_at}', to_jsonb(CAST(:stamp AS text))) AS "
                + extra_data_type
                + ") WHERE org_id = :org AND id = :id"
            ),
            params,
        )
        # Every event snapshots the lot's extra_data, so they carry the old time too.
        conn.execute(
            text(
                "UPDATE entity_events SET payload = jsonb_set(payload, '{extra_data,execution_trace,completed_at}', "
                "to_jsonb(CAST(:stamp AS text))) WHERE org_id = :org AND entity_id = :id "
                "AND payload #> '{extra_data,execution_trace}' IS NOT NULL"
            ),
            params,
        )
        changed += 1
    return changed


def _extra_data_type(conn: Connection) -> str:
    """`json` or `jsonb`, whichever the column is, so the write round-trips its own type."""
    data_type = conn.execute(
        text(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = 'inventory_items' AND column_name = 'extra_data'"
        )
    ).scalar()
    return "jsonb" if data_type == "jsonb" else "json"


def _date_process_versions(conn: Connection, org_id: Any) -> set:
    """`process_version_date` on execution.created -> the run's process version's dated creation."""
    rows = conn.execute(
        text(
            "SELECT e.id, e.entity_id, e.payload->>'process_version_date', pv.created_at "
            "FROM entity_events e JOIN process_versions pv ON pv.org_id = e.org_id "
            "AND pv.process_id::text = e.payload->>'process_id' "
            "AND pv.version_number::text = e.payload->>'process_version_number' "
            "WHERE e.org_id = :org AND e.event_type = 'execution.created' "
            "AND e.payload ? 'process_version_date'"
        ),
        {"org": org_id},
    ).all()
    touched = set()
    for event_id, execution_id, current, at in rows:
        stamp = _stamp(at)
        if current == stamp:
            continue
        conn.execute(
            text(
                "UPDATE entity_events SET payload = jsonb_set(payload, '{process_version_date}', "
                "to_jsonb(CAST(:stamp AS text))) WHERE id = :id AND org_id = :org"
            ),
            {"stamp": stamp, "id": event_id, "org": org_id},
        )
        touched.add(execution_id)
    return touched


def _date_sales(conn: Connection, org_id: Any) -> tuple[set, dict[str, int]]:
    """FIFO sale draws -> invoice date, kept after the lot exists and after its previous draw."""
    rows = conn.execute(
        text(
            "SELECT e.id, e.entity_id, e.created_at, e.payload->>'reference', i.date, it.created_at "
            "FROM entity_events e "
            "JOIN inventory_items it ON it.id = e.entity_id AND it.org_id = e.org_id "
            "LEFT JOIN xero_invoices i ON i.org_id = e.org_id AND i.xero_invoice_id = split_part(e.payload->>'reference', ':', 2) "
            "WHERE e.org_id = :org AND e.event_type = 'inventory_item.quantity_adjusted' "
            "AND e.payload->>'reason' = :reason ORDER BY e.entity_id, e.seq"
        ),
        {"org": org_id, "reason": SALES_REASON},
    ).all()
    counts = {"sales_events": 0, "sales_events_clamped": 0, "sales_without_invoice": 0}
    by_lot: dict[Any, list] = defaultdict(list)
    for row in rows:
        by_lot[row[1]].append(row)
    touched: set = set()
    allocation_times: dict[tuple[str, Any], datetime] = {}
    for lot_id, draws in by_lot.items():
        previous: datetime | None = None
        for event_id, _lot, current, reference, invoice_date, lot_created in draws:
            if invoice_date is None:
                counts["sales_without_invoice"] += 1
                previous = max(previous, current) if previous else current
                continue
            wanted = wm._derived_timestamp(invoice_date)
            floor = lot_created + _AFTER_LOT
            if previous is not None:
                floor = max(floor, previous + _AFTER_PREVIOUS_DRAW)
            at = max(wanted, floor)
            counts["sales_events_clamped"] += int(at != wanted)
            previous = at
            key = (reference, lot_id)
            allocation_times[key] = min(at, allocation_times.get(key, at))
            if at != current:
                conn.execute(
                    text("UPDATE entity_events SET created_at = :at WHERE id = :id AND org_id = :org"),
                    {"at": at, "id": event_id, "org": org_id},
                )
                counts["sales_events"] += 1
            touched.add(lot_id)
    for (reference, lot_id), at in allocation_times.items():
        _prefix, invoice_id, line_key = reference.split(":", 2)
        conn.execute(
            text(
                "UPDATE crm_sales_fifo_allocations SET created_at = :at WHERE org_id = :org "
                "AND inventory_item_id = :lot AND xero_invoice_id = :invoice AND xero_line_key = :line"
            ),
            {"at": at, "org": org_id, "lot": lot_id, "invoice": invoice_id, "line": line_key},
        )
    for lot_id in touched:
        conn.execute(
            text(
                "UPDATE inventory_items SET updated_at = (SELECT max(created_at) FROM entity_events "
                "WHERE org_id = :org AND entity_type = 'inventory_item' AND entity_id = :id) "
                "WHERE org_id = :org AND id = :id"
            ),
            {"org": org_id, "id": lot_id},
        )
    return touched, counts


def _run_passes(conn: Connection, org_id: Any) -> tuple[dict[str, Any], set]:
    report: dict[str, Any] = {"production_completions": _date_production_completions(conn, org_id)}
    executions = _date_process_versions(conn, org_id)
    lots, sales = _date_sales(conn, org_id)
    report.update(sales)
    report["process_version_dates"] = len(executions)
    return report, executions | lots


def apply_trace_dates(target_url: str, org_name: str) -> dict[str, Any]:
    """One transaction; a rerun finds nothing left to change."""
    _require_test_tenant(org_name)
    engine = create_engine(target_url)
    try:
        with engine.begin() as conn:
            org_id = _org_id(conn, org_name)
            report, entities = _run_passes(conn, org_id)
            correct._sync_summary_dates(conn, org_id, entities)
    finally:
        engine.dispose()
    return report


def verify_trace_dates(target_url: str, org_name: str) -> dict[str, Any]:
    """Read-only: plans the whole pass, counts what it would still change, and rolls back.
    Every figure should be 0 (sales draws clamped to keep a lot's history in order are
    reported by `apply` and are not a mismatch)."""
    _require_test_tenant(org_name)
    engine = create_engine(target_url)
    try:
        with engine.connect() as conn:
            transaction = conn.begin()
            try:
                report, _entities = _run_passes(conn, _org_id(conn, org_name))
            finally:
                transaction.rollback()
    finally:
        engine.dispose()
    return {
        "lot_completions_to_date": {"expected": 0, "actual": report["production_completions"]},
        "sales_events_to_date": {"expected": 0, "actual": report["sales_events"]},
        "process_version_dates_to_fix": {"expected": 0, "actual": report["process_version_dates"]},
    }


def _arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("apply", "verify"))
    parser.add_argument("--target-url", default=os.environ.get("BIZE_MIGRATION_DATABASE_URL"))
    parser.add_argument("--org-name", default=wm.WHISTLEBIRD_ORG_NAME)
    args = parser.parse_args(argv)
    if not args.target_url:
        parser.error("--target-url is required (or set BIZE_MIGRATION_DATABASE_URL)")
    return args


def main(argv: list[str] | None = None) -> int:
    args = _arguments(argv)
    try:
        run = apply_trace_dates if args.command == "apply" else verify_trace_dates
        report = run(args.target_url, args.org_name)
    except TraceDatesError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
