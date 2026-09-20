"""Apply curated dates to the Whistlebird Ltd API replay, including its audit trail.

Internal reset/import tooling only. The live API continues to record request time.
Run after a complete replay (or use whistlebird_rebuild_api.py, which runs this pass).
Every Core update is tenant scoped and committed together; missing replay rows abort it.
Dates with no recorded time use noon in Pacific/Auckland. Seconds within a day follow
the deterministic replay timeline, preserving the order of same-day events.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).parent))
import whistlebird_crm as crm  # noqa: E402
import whistlebird_disposals as disposals  # noqa: E402
import whistlebird_legacy as legacy  # noqa: E402
import whistlebird_migration as wm  # noqa: E402
import whistlebird_np3 as np3  # noqa: E402
from whistlebird_replay_timeline import ReplayEvent, build_timeline  # noqa: E402


def _business_at(real_date: date) -> datetime:
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


def _audit_days(events: list[ReplayEvent]) -> dict[str, date]:
    """Reconcile source dates with hard dependencies, working back from consumers.

    A later recorded purchase moves to the day before its earliest use. Other
    prerequisites move to the consumer's day, where replay order supplies seconds
    before the consumer. Source business dates in the manifests stay untouched.
    """
    by_id = {event.event_id: event for event in events}
    days = {event.event_id: event.real_date for event in events}
    for event in reversed(events):
        for dependency in event.depends_on:
            if dependency not in days:
                continue
            if days[dependency] > days[event.event_id]:
                earlier = timedelta(days=1) if by_id[dependency].event_type == "create_inventory_item" else timedelta()
                days[dependency] = days[event.event_id] - earlier
    return days


def _purchase_audit_days(events: list[ReplayEvent]) -> dict[str, date]:
    days = _audit_days(events)
    return {
        event.event_id: days[event.event_id]
        for event in events
        if event.event_type == "create_inventory_item" and days[event.event_id] != event.real_date
    }


def _event_times(events: list[ReplayEvent]) -> dict[str, datetime]:
    """Use a stable second within each effective audit day for replay order."""
    audit_days = _audit_days(events)
    day_positions: dict[date, int] = defaultdict(int)
    result = {}
    for event in events:
        audit_day = audit_days[event.event_id]
        position = day_positions[audit_day]
        if position >= 12 * 60 * 60:
            raise ValueError(f"too many replay events on {audit_day}")
        result[event.event_id] = _business_at(audit_day) + timedelta(seconds=position)
        day_positions[audit_day] += 1
    return result


def _execution_date_ranges(events: list[ReplayEvent]) -> dict[str, tuple[date, date]]:
    """Compatibility helper for callers that need the recorded execution date span."""
    grouped: dict[str, list[date]] = defaultdict(list)
    for event in events:
        if event.event_type in ("create_execution", "complete_step"):
            grouped[_marker_of(event)].append(event.real_date)
    return {marker: (min(days), max(days)) for marker, days in grouped.items()}


def _one(conn, sql: str, params: dict[str, Any], label: str):
    rows = conn.execute(text(sql), params).fetchall()
    if len(rows) != 1:
        raise RuntimeError(f"{label}: expected exactly one replay row, found {len(rows)}")
    return rows[0]


def _update_event(
    conn, org_id, event_type: str, entity_type: str, entity_id, at: datetime, execution_id=None, step_id=None
) -> int:
    """Date only the audit events caused by this replay operation."""
    conditions = ["org_id = :org", "event_type = :kind", "entity_type = :entity", "entity_id = :id"]
    params = {
        "org": org_id,
        "kind": event_type,
        "entity": entity_type,
        "id": entity_id,
        "at": at,
        "stamp": at.isoformat(),
    }
    if execution_id is not None:
        conditions.append("payload->>'execution_id' = :execution_id")
        params["execution_id"] = str(execution_id)
    if step_id is not None:
        conditions.append("payload->>'execution_step_id' = :step_id")
        params["step_id"] = str(step_id)
    update = "created_at = :at"
    if entity_type == "execution" and event_type in ("execution.step_completed", "execution.completed"):
        # These snapshots include the old completion time as well as the event time.
        update += ", payload = jsonb_set(payload, '{completed_at}', to_jsonb(CAST(:stamp AS text)), true)"
    result = conn.execute(text(f"UPDATE entity_events SET {update} WHERE {' AND '.join(conditions)}"), params)
    if result.rowcount != 1:
        raise RuntimeError(
            f"{event_type} audit for {entity_type}/{entity_id}: expected one row, found {result.rowcount}"
        )
    return result.rowcount


def _date_process_definitions(conn, org_id, events, times, counts):
    first_by_name: dict[str, date] = {}
    for event in events:
        if event.event_type == "create_execution":
            record = event.payload.get("batch") or event.payload.get("trial") or event.payload.get("green_gold")
            name = record.workflow_name
            audit_day = times[event.event_id].astimezone(wm.DERIVED_TIMEZONE).date()
            first_by_name[name] = min(first_by_name.get(name, audit_day), audit_day)

    process_dates = {}
    for name, first_day in sorted(first_by_name.items()):
        process_id = _one(
            conn,
            "SELECT id FROM processes WHERE org_id = :org AND name = :name",
            {"org": org_id, "name": name},
            f"process {name}",
        )[0]
        base = _business_at(first_day - timedelta(days=1))
        process_dates[process_id] = base
        versions = conn.execute(
            text(
                "SELECT id, version_number FROM process_versions "
                "WHERE org_id = :org AND process_id = :id ORDER BY version_number"
            ),
            {"org": org_id, "id": process_id},
        ).fetchall()
        if not versions:
            raise RuntimeError(f"process {name} has no versions")
        for version_id, number in versions:
            at = base + timedelta(seconds=number - 1)
            counts["process_versions"] += conn.execute(
                text("UPDATE process_versions SET created_at = :at WHERE org_id = :org AND id = :id"),
                {"at": at, "org": org_id, "id": version_id},
            ).rowcount
            counts["entity_events"] += conn.execute(
                text(
                    "UPDATE entity_events SET created_at = :at "
                    "WHERE org_id = :org AND entity_type = 'process' AND entity_id = :process "
                    "AND payload->>'process_version_id' = :version"
                ),
                {"at": at, "org": org_id, "process": process_id, "version": str(version_id)},
            ).rowcount
        counts["processes"] += conn.execute(
            text("UPDATE processes SET created_at = :base, updated_at = :last WHERE org_id = :org AND id = :id"),
            {"base": base, "last": base + timedelta(seconds=versions[-1][1] - 1), "org": org_id, "id": process_id},
        ).rowcount
        # A step exists when its step-added version exists. Older repaired definitions
        # retain their original version; no current-time audit date is left behind.
        counts["steps"] += conn.execute(
            text(
                "UPDATE steps s SET created_at = COALESCE(("
                "SELECT pv.created_at FROM entity_events ee "
                "JOIN process_versions pv ON pv.id::text = ee.payload->>'process_version_id' "
                "WHERE ee.org_id = :org AND ee.entity_id = :id "
                "AND ee.event_type = 'process.step_added' "
                "AND ee.payload->'step'->>'id' = s.id::text LIMIT 1), :base), "
                "updated_at = :last WHERE s.org_id = :org AND s.process_id = :id"
            ),
            {"org": org_id, "id": process_id, "base": base, "last": base + timedelta(seconds=versions[-1][1] - 1)},
        ).rowcount
    return process_dates


def _sync_summary_dates(conn, org_id, entity_ids: set):
    """Refresh the timestamp fields cached by EventWriter without changing its counts."""
    changed = 0
    for entity_id in entity_ids:
        row = conn.execute(
            text("SELECT summary, entity_type FROM entity_event_summaries WHERE org_id = :org AND entity_id = :id"),
            {"org": org_id, "id": entity_id},
        ).first()
        if row is None:
            continue
        summary, entity_type = dict(row[0]), row[1]
        events = conn.execute(
            text(
                "SELECT event_type, created_at, payload FROM entity_events "
                "WHERE org_id = :org AND entity_id = :id ORDER BY seq"
            ),
            {"org": org_id, "id": entity_id},
        ).fetchall()
        if not events:
            continue
        history = list(summary.get("quantity_history") or [])
        quantity_times = [
            at.isoformat()
            for kind, at, _payload in events
            if kind in ("inventory_item.created", "inventory_item.quantity_adjusted")
        ]
        if history:
            for entry, stamp in zip(history, quantity_times[-len(history) :], strict=False):
                entry["at"] = stamp
        for kind, at, payload in events:
            stamp = at.isoformat()
            if kind == f"{entity_type}.created":
                summary["created_at"] = stamp
                if entity_type == "execution" and payload.get("process_version_date"):
                    summary["process_version_date"] = payload["process_version_date"]
            if entity_type == "process":
                if kind == "process.created" or kind.startswith("process.step_") or kind == "process.updated":
                    summary["last_modified_at"] = stamp
                elif kind == "execution.created":
                    summary["last_run_at"] = stamp
            elif entity_type == "execution":
                if kind == "execution.step_completed":
                    summary["last_step_completed_at"] = stamp
                elif kind == "execution.completed":
                    summary["completed_at"] = stamp
            elif entity_type == "inventory_item":
                if kind == "inventory_item.consumed":
                    summary["last_consumed_at"] = stamp
        if entity_type == "inventory_item" and history:
            summary["quantity_history"] = history
        last_at = events[-1][1]
        conn.execute(
            text(
                "UPDATE entity_event_summaries SET summary = CAST(:summary AS jsonb), "
                "last_event_at = :at, updated_at = :at WHERE org_id = :org AND entity_id = :id"
            ),
            {"summary": json.dumps(summary), "at": last_at, "org": org_id, "id": entity_id},
        )
        changed += 1
    return changed


def _date_crm_config(conn, org_id, manifest: crm.CrmManifest, counts: dict[str, int]) -> None:
    """Date replayed mappings to the first matching finished product."""
    mapping_dates = []
    for offset, mapping in enumerate(manifest.mappings):
        product_at = _one(
            conn,
            "SELECT min(created_at) FROM inventory_items WHERE org_id = :org "
            "AND inventory_type = 'final_product' AND lower(name) = lower(:name)",
            {"org": org_id, "name": mapping.biz_e_product_name},
            f"finished product for {mapping.biz_e_product_name}",
        )[0]
        if product_at is None:
            raise RuntimeError(f"no finished product for CRM mapping {mapping.biz_e_product_name}")
        at = product_at + timedelta(seconds=offset + 1)
        mapping_id = _one(
            conn,
            "SELECT id FROM product_mappings WHERE org_id = :org "
            "AND lower(biz_e_product_name) = lower(:name) "
            "AND lower(xero_description_pattern) = lower(:pattern)",
            {"org": org_id, "name": mapping.biz_e_product_name, "pattern": mapping.xero_description_pattern},
            f"CRM mapping {mapping.key}",
        )[0]
        mapping_dates.append(at)
        counts["product_mappings"] += conn.execute(
            text("UPDATE product_mappings SET created_at = :at, updated_at = :at WHERE org_id = :org AND id = :id"),
            {"at": at, "org": org_id, "id": mapping_id},
        ).rowcount
        counts["entity_events"] += _update_event(
            conn,
            org_id,
            "crm_product_mapping.created",
            "crm_product_mapping",
            mapping_id,
            at,
        )
    if mapping_dates:
        config_at = min(mapping_dates) - timedelta(seconds=1)
        counts["crm_sales_traceability_config"] += conn.execute(
            text("UPDATE crm_sales_traceability_config SET created_at = :at, updated_at = :at WHERE org_id = :org"),
            {"at": config_at, "org": org_id},
        ).rowcount
        counts["entity_events"] += conn.execute(
            text(
                "UPDATE entity_events SET created_at = :at WHERE org_id = :org "
                "AND entity_type = 'crm_traceability_config' "
                "AND event_type = 'crm_traceability_config.updated'"
            ),
            {"at": config_at, "org": org_id},
        ).rowcount


def correct_timestamps(
    legacy_source: str | Path,
    target_url: str,
    org_name: str,
    np3_manifest_path: Path | None = np3.DEFAULT_NP3_MANIFEST,
    disposals_manifest_path: Path | None = disposals.DEFAULT_DISPOSALS_MANIFEST,
    production_manifest_path: Path = wm.DEFAULT_PRODUCTION_MANIFEST,
    crm_manifest_path: Path | None = crm.DEFAULT_CRM_MANIFEST,
    dry_run: bool = False,
) -> dict[str, int]:
    if org_name != wm.WHISTLEBIRD_ORG_NAME:
        raise ValueError(f"timestamp correction is only permitted for {wm.WHISTLEBIRD_ORG_NAME!r}")
    events = build_timeline(legacy_source, Path(production_manifest_path))
    times = _event_times(events)
    moved_purchase_events = _purchase_audit_days(events)
    moved_purchase_markers = {_marker_of(event) for event in events if event.event_id in moved_purchase_events}
    disposal_list = disposals.load_disposals_manifest(disposals_manifest_path) if disposals_manifest_path else ()
    crm_manifest = crm.load_crm_manifest(crm_manifest_path) if crm_manifest_path else None
    counts = dict.fromkeys(
        (
            "processes",
            "process_versions",
            "steps",
            "executions",
            "execution_steps",
            "inventory_items",
            "inventory_movements",
            "compliance_records",
            "entity_events",
            "entity_event_summaries",
            "wastage_records",
            "audit_logs",
            "product_mappings",
            "crm_sales_traceability_config",
            "compliance_profiles",
            "feature_subscriptions",
            "purchase_audits_moved",
        ),
        0,
    )
    engine = create_engine(target_url)
    try:
        with engine.connect() as conn, conn.begin() as transaction:
            org_id = _one(
                conn,
                "SELECT id FROM organisations WHERE name = :name",
                {"name": org_name},
                f"org {org_name}",
            )[0]
            process_dates = _date_process_definitions(conn, org_id, events, times, counts)
            profile_at = min(times.values()) - timedelta(days=1)
            counts["compliance_profiles"] += conn.execute(
                text(
                    "UPDATE compliance_profiles SET created_at = :at, updated_at = :at "
                    "WHERE org_id = :org AND industry_module = 'nz_alcohol'"
                ),
                {"at": profile_at, "org": org_id},
            ).rowcount
            counts["feature_subscriptions"] += conn.execute(
                text(
                    "UPDATE feature_subscriptions SET granted_at = :at WHERE org_id = :org "
                    "AND feature_key = 'compliant'"
                ),
                {"at": profile_at, "org": org_id},
            ).rowcount
            touched_entities = set(process_dates)
            item_latest: dict[Any, datetime] = {}
            execution_ids = {}
            for event in events:
                marker = _marker_of(event)
                at = times[event.event_id]
                if event.event_type == "create_inventory_item":
                    item_id = _one(
                        conn,
                        "SELECT id FROM inventory_items WHERE org_id = :org AND extra_data->>'import_ref' = :marker",
                        {"org": org_id, "marker": marker},
                        f"purchase {marker}",
                    )[0]
                    touched_entities.add(item_id)
                    item_latest[item_id] = max(item_latest.get(item_id, at), at)
                    counts["inventory_items"] += conn.execute(
                        text(
                            "UPDATE inventory_items SET created_at = :at, updated_at = :at, "
                            "extra_data = CASE WHEN extra_data ? 'inventory_audit_history' "
                            "THEN jsonb_set(extra_data, '{inventory_audit_history,0,timestamp_utc}', "
                            "to_jsonb(CAST(:iso AS text)), true) ELSE extra_data END "
                            "WHERE org_id = :org AND id = :id"
                        ),
                        {"at": at, "iso": at.strftime("%Y-%m-%dT%H:%M:%SZ"), "org": org_id, "id": item_id},
                    ).rowcount
                    counts["entity_events"] += _update_event(
                        conn,
                        org_id,
                        "inventory_item.created",
                        "inventory_item",
                        item_id,
                        at,
                    )
                    conn.execute(
                        text(
                            "UPDATE entity_events SET payload = jsonb_set("
                            "payload, '{extra_data,inventory_audit_history,0,timestamp_utc}', "
                            "to_jsonb(CAST(:stamp AS text)), true) "
                            "WHERE org_id = :org AND entity_type = 'inventory_item' AND entity_id = :id "
                            "AND payload->'extra_data' ? 'inventory_audit_history'"
                        ),
                        {"stamp": at.strftime("%Y-%m-%dT%H:%M:%SZ"), "org": org_id, "id": item_id},
                    )
                    counts["inventory_movements"] += conn.execute(
                        text(
                            "UPDATE inventory_movements SET created_at = :at "
                            "WHERE org_id = :org AND inventory_item_id = :id AND type = 'ADD'"
                        ),
                        {"at": at, "org": org_id, "id": item_id},
                    ).rowcount
                elif event.event_type == "create_execution":
                    execution_id, process_id, status, version_id, total_steps = _one(
                        conn,
                        "SELECT e.id, e.process_id, e.status, e.process_version_id, e.total_steps "
                        "FROM executions e WHERE e.org_id = :org AND e.id IN ("
                        "SELECT DISTINCT execution_id FROM execution_steps "
                        "WHERE org_id = :org AND execution_data->>'batch_ref' = :marker)",
                        {"org": org_id, "marker": marker},
                        f"execution {marker}",
                    )
                    if process_id not in process_dates:
                        raise RuntimeError(f"execution {marker} uses an unrecognized workflow")
                    execution_ids[marker] = (execution_id, process_id, status, version_id, total_steps)
                    touched_entities.update((execution_id, process_id))
                    counts["executions"] += conn.execute(
                        text(
                            "UPDATE executions SET created_at = :at, started_at = :at, "
                            "updated_at = :at, "
                            "completed_at = CASE WHEN status = 'COMPLETED' THEN completed_at ELSE NULL END "
                            "WHERE org_id = :org AND id = :id"
                        ),
                        {"at": at, "org": org_id, "id": execution_id},
                    ).rowcount
                    counts["execution_steps"] += conn.execute(
                        text(
                            "UPDATE execution_steps SET created_at = :at, updated_at = :at, "
                            "started_at = CASE WHEN status = 'COMPLETED' THEN started_at ELSE NULL END, "
                            "completed_at = CASE WHEN status = 'COMPLETED' THEN completed_at ELSE NULL END "
                            "WHERE org_id = :org AND execution_id = :id"
                        ),
                        {"at": at, "org": org_id, "id": execution_id},
                    ).rowcount
                    for entity_type, entity_id in (("execution", execution_id), ("process", process_id)):
                        counts["entity_events"] += _update_event(
                            conn,
                            org_id,
                            "execution.created",
                            entity_type,
                            entity_id,
                            at,
                            execution_id=execution_id,
                        )
                    if version_id:
                        version_at = conn.execute(
                            text("SELECT created_at FROM process_versions WHERE org_id = :org AND id = :id"),
                            {"org": org_id, "id": version_id},
                        ).scalar_one()
                        conn.execute(
                            text(
                                "UPDATE entity_events SET payload = jsonb_set(payload, "
                                "'{process_version_date}', to_jsonb(CAST(:stamp AS text)), true) "
                                "WHERE org_id = :org AND event_type = 'execution.created' "
                                "AND entity_type = 'execution' AND entity_id = :id"
                            ),
                            {"stamp": version_at.isoformat(), "org": org_id, "id": execution_id},
                        )
                elif event.event_type == "complete_step":
                    execution_id, process_id, _status, _version, total_steps = execution_ids[marker]
                    step_id = _one(
                        conn,
                        "SELECT id FROM execution_steps WHERE org_id = :org "
                        "AND execution_id = :execution AND step_number = :number "
                        "AND execution_data->>'batch_ref' = :marker",
                        {
                            "org": org_id,
                            "execution": execution_id,
                            "number": event.payload["step_index"] + 1,
                            "marker": marker,
                        },
                        f"step {event.event_id}",
                    )[0]
                    counts["execution_steps"] += conn.execute(
                        text(
                            "UPDATE execution_steps SET started_at = :at, completed_at = :at, "
                            "updated_at = :at WHERE org_id = :org AND id = :id"
                        ),
                        {"at": at, "org": org_id, "id": step_id},
                    ).rowcount
                    counts["executions"] += conn.execute(
                        text("UPDATE executions SET updated_at = :at WHERE org_id = :org AND id = :id"),
                        {"at": at, "org": org_id, "id": execution_id},
                    ).rowcount
                    counts["entity_events"] += _update_event(
                        conn,
                        org_id,
                        "execution.step_completed",
                        "execution",
                        execution_id,
                        at,
                        step_id=step_id,
                    )
                    produced = conn.execute(
                        text("SELECT id FROM inventory_items WHERE org_id = :org AND source_execution_step_id = :step"),
                        {"org": org_id, "step": step_id},
                    ).fetchall()
                    for (item_id,) in produced:
                        touched_entities.add(item_id)
                        item_latest[item_id] = max(item_latest.get(item_id, at), at)
                        counts["inventory_items"] += conn.execute(
                            text(
                                "UPDATE inventory_items SET created_at = :at, updated_at = :at "
                                "WHERE org_id = :org AND id = :id"
                            ),
                            {"at": at, "org": org_id, "id": item_id},
                        ).rowcount
                        counts["entity_events"] += _update_event(
                            conn,
                            org_id,
                            "inventory_item.created",
                            "inventory_item",
                            item_id,
                            at,
                        )
                        counts["inventory_movements"] += conn.execute(
                            text(
                                "UPDATE inventory_movements SET created_at = :at "
                                "WHERE org_id = :org AND inventory_item_id = :id "
                                "AND type = 'PRODUCTION'"
                            ),
                            {"at": at, "org": org_id, "id": item_id},
                        ).rowcount
                    for kind in ("inventory_item.consumed", "inventory_item.produced"):
                        affected = conn.execute(
                            text(
                                "UPDATE entity_events SET created_at = :at WHERE org_id = :org "
                                "AND event_type = :kind AND payload->>'execution_step_id' = :step "
                                "RETURNING entity_id"
                            ),
                            {"at": at, "org": org_id, "kind": kind, "step": str(step_id)},
                        ).fetchall()
                        counts["entity_events"] += len(affected)
                        touched_entities.update(row[0] for row in affected)
                        for (item_id,) in affected:
                            item_latest[item_id] = max(item_latest.get(item_id, at), at)
                    if str(_status).upper().endswith("COMPLETED") and event.payload["step_index"] + 1 == total_steps:
                        # Only the last completed step emits this pair.
                        for entity_type, entity_id in (("execution", execution_id), ("process", process_id)):
                            counts["entity_events"] += _update_event(
                                conn,
                                org_id,
                                "execution.completed",
                                entity_type,
                                entity_id,
                                at,
                                execution_id=execution_id,
                            )
                        conn.execute(
                            text(
                                "UPDATE executions SET completed_at = :at WHERE org_id = :org "
                                "AND id = :id AND status = 'COMPLETED'"
                            ),
                            {"at": at, "org": org_id, "id": execution_id},
                        )
                elif event.event_type == "create_customs_lodgement":
                    record_id = _one(
                        conn,
                        "SELECT id FROM compliance_records WHERE org_id = :org AND details->>'import_ref' = :marker",
                        {"org": org_id, "marker": marker},
                        f"customs {marker}",
                    )[0]
                    counts["compliance_records"] += conn.execute(
                        text(
                            "UPDATE compliance_records SET created_at = :at, updated_at = :at "
                            "WHERE org_id = :org AND id = :id"
                        ),
                        {"at": at, "org": org_id, "id": record_id},
                    ).rowcount
                    counts["audit_logs"] += conn.execute(
                        text(
                            "UPDATE audit_logs SET timestamp = :at WHERE org_id = :org "
                            "AND entity = 'compliance_record' AND entity_id = :id AND action = 'create'"
                        ),
                        {"at": at, "org": org_id, "id": record_id},
                    ).rowcount

            # An actual FIFO draw can reference an earlier receipt than the manifest's
            # explicit dependency edges. Resolve that from the linked audit events.
            for item_id in item_latest:
                first_use = conn.execute(
                    text(
                        "SELECT min(created_at) FROM entity_events WHERE org_id = :org "
                        "AND entity_type = 'inventory_item' AND entity_id = :id "
                        "AND event_type = 'inventory_item.consumed'"
                    ),
                    {"org": org_id, "id": item_id},
                ).scalar_one()
                if first_use is None:
                    continue
                item = conn.execute(
                    text(
                        "SELECT created_at, inventory_type, extra_data->>'import_ref' "
                        "FROM inventory_items WHERE org_id = :org AND id = :id"
                    ),
                    {"org": org_id, "id": item_id},
                ).one()
                if item[0] < first_use:
                    continue
                if item[1] != "raw_material" or not item[2]:
                    raise RuntimeError(f"produced inventory {item_id} was consumed before creation")
                corrected = first_use - timedelta(seconds=1)
                conn.execute(
                    text(
                        "UPDATE inventory_items SET created_at = :at, "
                        "extra_data = CASE WHEN extra_data ? 'inventory_audit_history' "
                        "THEN jsonb_set(extra_data, '{inventory_audit_history,0,timestamp_utc}', "
                        "to_jsonb(CAST(:stamp AS text)), true) ELSE extra_data END "
                        "WHERE org_id = :org AND id = :id"
                    ),
                    {"at": corrected, "stamp": corrected.strftime("%Y-%m-%dT%H:%M:%SZ"), "org": org_id, "id": item_id},
                )
                conn.execute(
                    text(
                        "UPDATE entity_events SET created_at = :at "
                        "WHERE org_id = :org AND entity_type = 'inventory_item' "
                        "AND entity_id = :id AND event_type = 'inventory_item.created'"
                    ),
                    {"at": corrected, "org": org_id, "id": item_id},
                )
                conn.execute(
                    text(
                        "UPDATE entity_events SET payload = jsonb_set(payload, "
                        "'{extra_data,inventory_audit_history,0,timestamp_utc}', "
                        "to_jsonb(CAST(:stamp AS text)), true) "
                        "WHERE org_id = :org AND entity_type = 'inventory_item' "
                        "AND entity_id = :id AND payload->'extra_data' ? 'inventory_audit_history'"
                    ),
                    {"stamp": corrected.strftime("%Y-%m-%dT%H:%M:%SZ"), "org": org_id, "id": item_id},
                )
                counts["inventory_movements"] += conn.execute(
                    text(
                        "UPDATE inventory_movements SET created_at = :at "
                        "WHERE org_id = :org AND inventory_item_id = :id AND type = 'ADD'"
                    ),
                    {"at": corrected, "org": org_id, "id": item_id},
                ).rowcount
                moved_purchase_markers.add(item[2])

            for disposal in disposal_list:
                item_id = _one(
                    conn,
                    "SELECT id FROM inventory_items WHERE org_id = :org AND extra_data->>'import_ref' = :marker",
                    {"org": org_id, "marker": disposal.lot},
                    f"disposal lot {disposal.lot}",
                )[0]
                at = _business_at(disposal.on)
                wastage_id = _one(
                    conn,
                    "SELECT id FROM inventory_wastage WHERE org_id = :org AND inventory_item_id = :id",
                    {"org": org_id, "id": item_id},
                    f"wastage for {disposal.lot}",
                )[0]
                counts["wastage_records"] += conn.execute(
                    text(
                        "UPDATE inventory_wastage SET recorded_at = :at, created_at = :at "
                        "WHERE org_id = :org AND id = :id"
                    ),
                    {"at": at, "org": org_id, "id": wastage_id},
                ).rowcount
                counts["inventory_movements"] += conn.execute(
                    text(
                        "UPDATE inventory_movements SET created_at = :at "
                        "WHERE org_id = :org AND source_wastage_id = :id"
                    ),
                    {"at": at, "org": org_id, "id": wastage_id},
                ).rowcount
                counts["entity_events"] += conn.execute(
                    text(
                        "UPDATE entity_events SET created_at = :at, "
                        "payload = jsonb_set(payload, '{recorded_at}', "
                        "to_jsonb(CAST(:stamp AS text)), true) WHERE org_id = :org "
                        "AND event_type = 'inventory_item.wasted' "
                        "AND payload->>'wastage_id' = :id"
                    ),
                    {"at": at, "stamp": at.isoformat(), "org": org_id, "id": str(wastage_id)},
                ).rowcount
                touched_entities.add(item_id)
                item_latest[item_id] = max(item_latest.get(item_id, at), at)

            # The mutable row reflects its latest historical stock action; its creation
            # date stays the purchase/production date. Later real sales events are
            # left at their actual request time and therefore remain the latest update.
            for item_id, latest in item_latest.items():
                event_latest = conn.execute(
                    text(
                        "SELECT max(created_at) FROM entity_events WHERE org_id = :org "
                        "AND entity_type = 'inventory_item' AND entity_id = :id"
                    ),
                    {"org": org_id, "id": item_id},
                ).scalar_one()
                latest = max(latest, event_latest) if event_latest else latest
                conn.execute(
                    text("UPDATE inventory_items SET updated_at = :at WHERE org_id = :org AND id = :id"),
                    {"at": latest, "org": org_id, "id": item_id},
                )
            if crm_manifest:
                _date_crm_config(conn, org_id, crm_manifest, counts)
            counts["entity_event_summaries"] = _sync_summary_dates(conn, org_id, touched_entities)
            counts["purchase_audits_moved"] = len(moved_purchase_markers)
            if dry_run:
                transaction.rollback()
    finally:
        engine.dispose()

    if np3_manifest_path and not dry_run:
        counts["np3_records"] = np3.correct_np3_timestamps(
            target_url, org_name, np3.load_np3_manifest(np3_manifest_path)
        )
    return counts


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy-url", "--legacy-source", dest="legacy_source", default=legacy.DEFAULT_LEGACY_SNAPSHOT)
    parser.add_argument("--target-url", default=os.environ.get("BIZE_MIGRATION_DATABASE_URL"))
    parser.add_argument("--org-name", default=wm.WHISTLEBIRD_ORG_NAME)
    parser.add_argument("--production-manifest", type=Path, default=wm.DEFAULT_PRODUCTION_MANIFEST)
    parser.add_argument("--crm-manifest", type=Path, default=crm.DEFAULT_CRM_MANIFEST)
    parser.add_argument("--skip-crm-config", action="store_true")
    parser.add_argument("--disposals-manifest", type=Path, default=disposals.DEFAULT_DISPOSALS_MANIFEST)
    parser.add_argument("--skip-disposals", action="store_true")
    parser.add_argument("--np3-manifest", type=Path, default=np3.DEFAULT_NP3_MANIFEST)
    parser.add_argument("--skip-np3", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Validate Core corrections then roll back all writes.")
    args = parser.parse_args()
    if not args.target_url:
        parser.error("--target-url is required (or set BIZE_MIGRATION_DATABASE_URL)")
    if args.org_name != wm.WHISTLEBIRD_ORG_NAME:
        parser.error(f"--org-name must be exactly {wm.WHISTLEBIRD_ORG_NAME!r}")
    return args


def main() -> int:
    args = _arguments()
    result = correct_timestamps(
        args.legacy_source,
        args.target_url,
        args.org_name,
        None if args.skip_np3 else args.np3_manifest,
        disposals_manifest_path=None if args.skip_disposals else args.disposals_manifest,
        production_manifest_path=args.production_manifest,
        crm_manifest_path=None if args.skip_crm_config else args.crm_manifest,
        dry_run=args.dry_run,
    )
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
