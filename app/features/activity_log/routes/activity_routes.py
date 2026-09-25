"""Tenant-scoped activity stream and human-readable event detail routes."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from flask import g, jsonify, request

from app.core.db import db_session
from app.core.security.permissions import requires_auth
from app.observability import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Entity Event Endpoints — Summary, Story, and Sourcemap
# ---------------------------------------------------------------------------


def _parse_entity_type(entity_type: str) -> str | None:
    """Validate entity_type is one we support."""
    valid = {"inventory_item", "execution", "process", "user", "org"}
    return entity_type if entity_type in valid else None


def _log_activity_access_denied(org_id: UUID, entity_type: str, entity_id: UUID) -> None:
    """Same rationale as _log_process_access_denied/_log_trace_access_denied: a story or
    summary lookup that resolves to nothing for the caller's org is a tenant-boundary probe
    just as much as a stale/mistyped id, and the route returns the same empty 200 either
    way (AC3/AC10: cross-org existence must not be distinguishable from non-existence), so
    the log doesn't try to distinguish them either. Added as defense-in-depth telemetry
    after F1 (security-audit.md) -- entity_summary_detail's missing org_id filter -- so a
    future probe against this class of gap leaves a trace even if the filter regresses.
    """
    logger.warning(
        "access_denied",
        reason="entity_not_found_or_cross_org",
        feature="activity-log",
        org_id=str(org_id),
        entity_type=entity_type,
        entity_id=str(entity_id),
        path=request.path,
    )


def _event_to_dict(ev) -> dict:
    return {
        "id": str(ev.id),
        "event_type": ev.event_type,
        "entity_type": ev.entity_type,
        "entity_id": str(ev.entity_id) if ev.entity_id else None,
        "at": ev.created_at.isoformat() if ev.created_at else None,
        "actor": ev.actor_label,
        "actor_type": ev.actor_type,
        "payload": ev.payload,
        "diff": ev.diff,
        "causation_id": str(ev.causation_id) if ev.causation_id else None,
    }


_FIELD_LABELS = {
    "name": "Name",
    "description": "Description",
    "quantity": "Quantity",
    "unit": "Unit",
    "inventory_type": "Type",
    "supplier": "Supplier",
    "supplier_batch_number": "Batch number",
    "barcode": "Barcode",
    "purchase_date": "Purchase date",
    "expiry_date": "Expiry date",
    "step_number": "Position",
    "inputs": "Inputs",
    "outputs": "Outputs",
    "execution_prompts": "Prompts",
    "category": "Category",
    "is_draft": "Draft",
}

_ITEM_FIELD_LABELS = {
    "name": "Name",
    "label": "Label",
    "quantity": "Quantity",
    "unit": "Unit",
    "inventory_type": "Inventory type",
    "expected_inventory_type": "Expected type",
    "type": "Type",
    "required": "Required",
    "is_variable": "Variable qty",
    "requires_execution_confirmation": "Confirmation required",
    "description": "Description",
}

# Fields that are auto-populated by the system and should not be reported when
# they only appear in the after snapshot (i.e. before is None/absent).
_ITEM_IMPLICIT_FIELDS = frozenset(
    {
        "inventory_type",
        "expected_inventory_type",
        "is_variable",
        "requires_execution_confirmation",
    }
)

_INVENTORY_TYPE_LABELS = {
    "raw_material": "Raw material",
    "work_in_progress": "Work in progress",
    "final_product": "Final product",
}

_ITEM_SKIP_FIELDS = frozenset({"id", "extra_data"})


def _fmt_field_value(val) -> str:
    if val is None or val == "":
        return "—"
    if isinstance(val, bool):
        return "Yes" if val else "No"
    if isinstance(val, list):
        if not val:
            return "(none)"
        if all(isinstance(i, dict) for i in val):
            parts = []
            for item in val:
                if "name" in item:
                    s = item["name"]
                    if item.get("quantity") is not None:
                        s += f" ({item['quantity']}"
                        if item.get("unit"):
                            s += f" {item['unit']}"
                        s += ")"
                    parts.append(s)
                elif "label" in item:
                    s = item["label"]
                    if item.get("type"):
                        s += f" ({item['type']})"
                    parts.append(s)
            if parts:
                return ", ".join(parts)
        return f"{len(val)} item{'s' if len(val) != 1 else ''}"
    if isinstance(val, str) and val in _INVENTORY_TYPE_LABELS:
        return _INVENTORY_TYPE_LABELS[val]
    return str(val)


def _fmt_sub_val(val, field: str = "") -> str:
    if val is None or val == "":
        return "(none)"
    if isinstance(val, bool):
        return "Yes" if val else "No"
    if isinstance(val, list | dict):
        return "(complex)"
    if field in ("inventory_type", "expected_inventory_type"):
        return _INVENTORY_TYPE_LABELS.get(str(val), str(val))
    return str(val)


def _item_key(item: dict) -> str | None:
    for k in ("id", "name", "label"):
        if k in item:
            return str(item[k])
    return None


def _item_display_name(item: dict) -> str:
    return item.get("name") or item.get("label") or "(item)"


def _smart_list_diff_rows(label: str, before: list, after: list) -> list[dict]:
    """Deep diff two lists of dicts, returning structured {label, before, after} rows."""
    rows: list[dict] = []
    before_by_key: dict = {}
    after_by_key: dict = {}
    for item in before:
        k = _item_key(item)
        if k:
            before_by_key[k] = item
    for item in after:
        k = _item_key(item)
        if k:
            after_by_key[k] = item

    if not before_by_key and not after_by_key:
        if before != after:
            rows.append({"label": label, "before": _fmt_field_value(before), "after": _fmt_field_value(after)})
        return rows

    seen: set = set()
    for item in before:
        k = _item_key(item)
        if not k or k in seen:
            continue
        seen.add(k)
        a_item = after_by_key.get(k)
        if a_item is None:
            rows.append({"label": label, "before": f"'{_item_display_name(item)}' removed", "after": None})
        else:
            all_fields = [f for f in set(item) | set(a_item) if f not in _ITEM_SKIP_FIELDS]
            for field in all_fields:
                b_val = item.get(field)
                a_val = a_item.get(field)
                if b_val == a_val:
                    continue
                # Skip fields that are auto-populated when they were simply absent before
                if field in _ITEM_IMPLICIT_FIELDS and b_val is None:
                    continue
                fl = _ITEM_FIELD_LABELS.get(field, field.replace("_", " ").capitalize())
                rows.append(
                    {
                        "label": f"{label} '{_item_display_name(item)}' – {fl}",
                        "before": _fmt_sub_val(b_val, field),
                        "after": _fmt_sub_val(a_val, field),
                    }
                )

    for item in after:
        k = _item_key(item)
        if not k or k in seen:
            continue
        seen.add(k)
        if k not in before_by_key:
            rows.append({"label": label, "before": None, "after": f"'{_item_display_name(item)}' added"})

    return rows


def _build_diff_rows(diff: dict) -> list[dict]:
    """Build structured diff rows: [{label, before, after}]. before/after may be None."""
    rows: list[dict] = []
    for field, change in (diff or {}).items():
        if not isinstance(change, dict):
            continue
        label = _FIELD_LABELS.get(field, field.replace("_", " ").capitalize())
        before = change.get("before")
        after = change.get("after")
        if isinstance(before, list) and isinstance(after, list) and all(isinstance(i, dict) for i in (before + after)):
            rows.extend(_smart_list_diff_rows(label, before, after))
        else:
            b_str = _fmt_field_value(before)
            a_str = _fmt_field_value(after)
            if b_str != a_str:
                rows.append(
                    {
                        "label": label,
                        "before": None if b_str == "—" else b_str,
                        "after": None if a_str == "—" else a_str,
                    }
                )
    return rows


def _step_added_diff_rows(step_data: dict) -> list[dict]:
    """Synthesize diff rows for a newly added step from its snapshot payload."""
    rows: list[dict] = []
    desc = step_data.get("description")
    if desc:
        rows.append({"label": "Description", "before": None, "after": desc})
    for inp in step_data.get("inputs") or []:
        if not isinstance(inp, dict):
            continue
        name = _item_display_name(inp)
        qty = inp.get("quantity")
        unit = inp.get("unit", "")
        detail = f"'{name}'"
        if qty is not None:
            detail += f" — {qty} {unit}".rstrip()
        rows.append({"label": "Input", "before": None, "after": detail})
    for out in step_data.get("outputs") or []:
        if not isinstance(out, dict):
            continue
        name = _item_display_name(out)
        qty = out.get("quantity")
        unit = out.get("unit", "")
        detail = f"'{name}'"
        if qty is not None:
            detail += f" — {qty} {unit}".rstrip()
        rows.append({"label": "Output", "before": None, "after": detail})
    for pr in step_data.get("execution_prompts") or []:
        if not isinstance(pr, dict):
            continue
        label = pr.get("label") or pr.get("name") or "(prompt)"
        rows.append({"label": "Prompt", "before": None, "after": label})
    return rows


def _event_diff_rows(ev) -> list[dict]:
    """Return per-change diff rows for an event, handling nested step diffs."""
    et = ev.event_type
    p = ev.payload or {}
    if et == "process.step_added":
        return _step_added_diff_rows(p.get("step") or {})
    if et == "process.step_updated":
        return _build_diff_rows((ev.diff or {}).get("step") or {})
    return _build_diff_rows(ev.diff or {})


def _human_summary(ev) -> str:
    et = ev.event_type
    p = ev.payload or {}
    d = ev.diff or {}

    if et == "inventory_item.created":
        qty = p.get("quantity", "")
        unit = p.get("unit", "")
        method = p.get("add_method", "manual").replace("_", " ")
        inv_type = _INVENTORY_TYPE_LABELS.get(
            p.get("inventory_type") or "", (p.get("inventory_type") or "").replace("_", " ")
        )
        parts = [f"Added {qty} {unit}".strip()]
        if inv_type:
            parts[0] += f" ({inv_type})"
        parts.append(f"via {method}")
        supplier = p.get("supplier")
        batch = p.get("supplier_batch_number")
        if supplier:
            parts.append(f"· supplier: {supplier}")
        if batch:
            parts.append(f"· batch: {batch}")
        return " ".join(parts)

    if et == "inventory_item.quantity_adjusted":
        before = p.get("quantity_before", "?")
        after = p.get("quantity_after", p.get("quantity", "?"))
        unit = p.get("unit", "")
        return f"Quantity adjusted {before} → {after} {unit}".strip()

    if et == "inventory_item.consumed":
        qty = p.get("quantity_consumed", "?")
        unit = p.get("unit", "")
        step = p.get("step_name", "")
        base = f"{qty} {unit} consumed".strip()
        if step:
            base += f" in '{step}'"
        process = p.get("process_name")
        if process:
            base += f" · {process}"
        return base

    if et == "inventory_item.produced":
        qty = p.get("quantity_produced", "?")
        unit = p.get("unit", "")
        step = p.get("step_name", "")
        base = f"{qty} {unit} produced".strip()
        if step:
            base += f" by '{step}'"
        process = p.get("process_name")
        if process:
            base += f" · {process}"
        return base

    if et == "inventory_item.wasted":
        qty = p.get("quantity_wasted", "?")
        unit = p.get("unit", "")
        reason = p.get("reason", "")
        base = f"{qty} {unit} wasted".strip()
        if reason:
            base += f" — {reason}"
        return base

    if et == "inventory_item.updated":
        if not d:
            return "Updated"
        field_labels = {
            "name": "name",
            "inventory_type": "type",
            "quantity": "quantity",
            "unit": "unit",
            "supplier": "supplier",
            "supplier_batch_number": "batch",
            "purchase_date": "purchase date",
            "expiry_date": "expiry date",
            "barcode": "barcode",
        }
        changed = [field_labels.get(k, k) for k in d]
        return "Updated " + ", ".join(changed)

    if et == "inventory_item.deleted":
        name = p.get("name", "")
        return f"Deleted{(' ' + name) if name else ''}"

    if et == "execution.created":
        steps = p.get("total_steps", "")
        ver = p.get("process_version_number", "")
        base = "Batch started"
        if steps:
            base += f" — {steps} steps"
        if ver:
            base += f" (process v{ver})"
        return base

    if et == "execution.step_completed":
        step = p.get("step_name", f"Step {p.get('step_number', '?')}")
        consumed = p.get("items_consumed") or []
        produced = p.get("items_produced") or []
        base = f"'{step}' completed"
        if consumed:
            base += f" — {len(consumed)} input{'s' if len(consumed) != 1 else ''} consumed"
        if produced:
            base += f", {len(produced)} output{'s' if len(produced) != 1 else ''} produced"
        return base

    if et == "execution.completed":
        steps = p.get("total_steps", "")
        base = "Batch completed"
        if steps:
            base += f" ({steps} steps)"
        return base

    if et == "execution.cancelled":
        reason = p.get("reason", "")
        base = "Batch cancelled"
        if reason:
            base += f" — {reason}"
        return base

    if et == "process.created":
        name = p.get("name", "")
        return f"Process{(' ' + repr(name)) if name else ''} created"

    if et == "process.updated":
        return "Process updated"

    if et == "process.step_added":
        step_data = p.get("step") or {}
        step_name = step_data.get("name", "step")
        pos = step_data.get("step_number", "")
        base = f"Step '{step_name}' added"
        if pos:
            base += f" at position {pos}"
        return base

    if et == "process.step_updated":
        step_name = (p.get("step") or {}).get("name", "step")
        return f"Step '{step_name}' updated"

    if et == "process.step_deleted":
        step = (p.get("deleted_step") or {}).get("name", "step")
        return f"Step '{step}' removed"

    if et == "process.deleted":
        name = p.get("name", "")
        return f"Process{(' ' + repr(name)) if name else ''} deleted"

    if et == "process.step_doc_uploaded":
        step = p.get("step_name", "step")
        title = p.get("doc_title", "document")
        return f"SOP file '{title}' uploaded to step '{step}'"

    if et == "process.step_doc_created":
        step = p.get("step_name", "step")
        title = p.get("doc_title", "document")
        return f"SOP instructions '{title}' written for step '{step}'"

    if et == "process.step_doc_updated":
        step = p.get("step_name", "step")
        title = p.get("doc_title", "document")
        return f"SOP instructions '{title}' updated for step '{step}'"

    if et == "process.step_doc_deleted":
        step = p.get("step_name", "step")
        title = p.get("doc_title", "document")
        return f"SOP document '{title}' removed from step '{step}'"

    if et in ("supplier.created", "supplier.updated", "supplier.deleted"):
        name = p.get("name", "")
        label = f" {name!r}" if name else ""
        if et == "supplier.created":
            source = " (from inventory)" if p.get("source") == "inventory" else ""
            return f"Supplier{label} added{source}"
        if et == "supplier.deleted":
            return f"Supplier{label} deleted"
        changed = ", ".join(key.replace("_", " ") for key in d) or "details"
        return f"Supplier{label} updated — {changed}"

    if et == "user.created":
        return f"Account created — {p.get('email', '')}"

    if et == "user.login":
        method = "with 2FA" if p.get("2fa_used") else "with password"
        return f"Logged in {method} from {p.get('ip', '?')}"

    if et == "user.login_failed":
        return f"Login failed from {p.get('ip', '?')} (attempt {p.get('failed_attempts', '?')})"

    if et == "user.2fa_enabled":
        return "Two-factor authentication enabled"

    if et == "user.2fa_disabled":
        return "Two-factor authentication disabled"

    if et == "user.role_changed":
        return f"Role changed from {p.get('old_role', '?')} to {p.get('new_role', '?')}"

    if et == "org.settings_updated":
        d = ev.diff or {}
        parts = []
        if "name" in d:
            parts.append(f"Name changed to '{d['name'].get('after', '?')}'")
        if "status" in d:
            parts.append(f"Status changed to {d['status'].get('after', '?')}")
        return "Organisation settings updated" + (f" — {', '.join(parts)}" if parts else "")

    return et.replace(".", " — ").replace("_", " ").capitalize()


@requires_auth
def entity_story(entity_type: str, entity_id: str):
    """Full event timeline for a single entity, ordered chronologically.

    Used when drilling into a card to see its complete audit history.
    For inventory items, legacy extra_data.inventory_audit_history entries are
    merged in so nothing is lost — deduplicated against entity_events by timestamp.
    """
    from app.core.db.models.entity_event import EntityEvent

    etype = _parse_entity_type(entity_type)
    if not etype:
        return jsonify({"error": "Invalid entity_type"}), 400

    try:
        eid = UUID(entity_id)
    except ValueError:
        return jsonify({"error": "Invalid entity_id"}), 400

    org_id = UUID(g.org_id)
    try:
        limit = min(int(request.args.get("limit", 200)), 500)
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "limit and offset must be integers"}), 400

    db = db_session()
    events = (
        db.query(EntityEvent)
        .filter(EntityEvent.org_id == org_id, EntityEvent.entity_id == eid)
        .order_by(EntityEvent.created_at.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    total = db.query(EntityEvent).filter(EntityEvent.org_id == org_id, EntityEvent.entity_id == eid).count()

    event_dicts = [
        {**_event_to_dict(ev), "summary": _human_summary(ev), "diff_rows": _event_diff_rows(ev)} for ev in events
    ]

    if etype == "inventory_item":
        event_dicts = _merge_inventory_legacy_audit(db, eid, org_id, event_dicts, events)

    if total == 0 and not event_dicts:
        _log_activity_access_denied(org_id, etype, eid)

    return jsonify(
        {
            "entity_id": str(eid),
            "entity_type": etype,
            "total": total,
            "offset": offset,
            "events": event_dicts,
        }
    ), 200


def _merge_inventory_legacy_audit(db, eid: UUID, org_id: UUID, event_dicts: list, events: list) -> list:
    """Merge extra_data.inventory_audit_history into the entity_events timeline.

    - Entries within 10 s of an existing entity_event are considered the same
      action: the display name from the legacy entry augments the actor field.
    - Entries with no matching entity_event are inserted as standalone timeline
      items (covers pre-event-sourcing items and barcode re-stocks).
    - user_id is always stripped.
    """
    from datetime import datetime

    from app.core.db.models.inventory_item import InventoryItem

    item = db.query(InventoryItem).filter(InventoryItem.id == eid, InventoryItem.org_id == org_id).first()
    if not item or not item.extra_data:
        return event_dicts

    legacy_entries = item.extra_data.get("inventory_audit_history") or []
    if not legacy_entries:
        return event_dicts

    # Build a lookup of entity_event timestamps (naive UTC) → index in event_dicts
    ev_timestamps = []
    for ev in events:
        if ev.created_at:
            ts = ev.created_at.replace(tzinfo=None) if ev.created_at.tzinfo else ev.created_at
            ev_timestamps.append(ts)
        else:
            ev_timestamps.append(None)

    def _parse_legacy_ts(ts_str):
        if not ts_str:
            return None
        try:
            return datetime.fromisoformat(ts_str.replace("Z", "+00:00")).replace(tzinfo=None)
        except (ValueError, AttributeError):
            return None

    def _actor_display(entry):
        name = (entry.get("operator_name") or "").strip()
        email = (entry.get("operator_email") or "").strip()
        if name and email and name != email:
            return f"{name} ({email})"
        return name or email or ""

    def _legacy_summary(entry):
        method = (entry.get("source_method") or "manual").replace("_", " ")
        parts = []
        qty = entry.get("quantity_added")
        if qty:
            parts.append(f"Added {qty}")
        else:
            parts.append("Item recorded")
        parts.append(f"via {method}")
        supplier = entry.get("supplier")
        batch = entry.get("supplier_batch_number")
        purchase = entry.get("purchase_date")
        expiry = entry.get("expiry_date")
        if supplier:
            parts.append(f"· supplier: {supplier}")
        if batch:
            parts.append(f"· batch: {batch}")
        if purchase:
            parts.append(f"· purchased: {purchase}")
        if expiry:
            parts.append(f"· expiry: {expiry}")
        return " ".join(parts)

    extra_events = []
    for entry in legacy_entries:
        if not isinstance(entry, dict):
            continue
        entry = {k: v for k, v in entry.items() if k != "user_id"}
        legacy_ts = _parse_legacy_ts(entry.get("timestamp_utc"))

        matched_idx = None
        if legacy_ts:
            for i, ev_ts in enumerate(ev_timestamps):
                if ev_ts and abs((legacy_ts - ev_ts).total_seconds()) < 10:
                    matched_idx = i
                    break

        if matched_idx is not None:
            # Augment the matching event's actor with the display name if available
            name = (entry.get("operator_name") or "").strip()
            email = (entry.get("operator_email") or "").strip()
            if name and email and name != email:
                current = event_dicts[matched_idx].get("actor") or ""
                if name not in current:
                    event_dicts[matched_idx] = dict(event_dicts[matched_idx])
                    event_dicts[matched_idx]["actor"] = f"{name} ({current})" if current else name
        else:
            extra_events.append(
                {
                    "id": f"legacy_{entry.get('timestamp_utc', '')}",
                    "event_type": "inventory_item.legacy_entry",
                    "entity_type": "inventory_item",
                    "entity_id": str(eid),
                    "at": entry.get("timestamp_utc"),
                    "actor": _actor_display(entry),
                    "actor_type": "user",
                    "summary": _legacy_summary(entry),
                    "diff_rows": [],
                    "payload": None,
                    "diff": None,
                    "causation_id": None,
                }
            )

    if extra_events:
        merged = event_dicts + extra_events
        merged.sort(key=lambda e: e.get("at") or "")
        return merged

    return event_dicts


@requires_auth
def entity_summary_detail(entity_type: str, entity_id: str):
    """Rich computed summary for a single entity card detail view.

    Queries entity_events directly (more detail than the pre-computed summary table).
    """
    from app.core.db.models.entity_event import EntityEvent
    from app.core.db.models.entity_event_summary import EntityEventSummary

    etype = _parse_entity_type(entity_type)
    if not etype:
        return jsonify({"error": "Invalid entity_type"}), 400

    try:
        eid = UUID(entity_id)
    except ValueError:
        return jsonify({"error": "Invalid entity_id"}), 400

    org_id = UUID(g.org_id)
    db = db_session()

    # Pull pre-computed summary
    summary_row = (
        db.query(EntityEventSummary)
        .filter(EntityEventSummary.entity_id == eid, EntityEventSummary.org_id == org_id)
        .first()
    )
    summary = summary_row.summary if summary_row else {}

    # Pull most recent 10 events for "recent_events" display
    recent = (
        db.query(EntityEvent)
        .filter(EntityEvent.org_id == org_id, EntityEvent.entity_id == eid)
        .order_by(EntityEvent.created_at.desc())
        .limit(10)
        .all()
    )

    if summary_row is None and not recent:
        _log_activity_access_denied(org_id, etype, eid)

    return jsonify(
        {
            "entity_id": str(eid),
            "entity_type": etype,
            "summary": summary,
            "recent_events": [
                {**_event_to_dict(ev), "summary": _human_summary(ev), "diff_rows": _event_diff_rows(ev)}
                for ev in reversed(recent)
            ],
        }
    ), 200


@requires_auth
def entity_activity_feed():
    """All entity events for the org, newest-first, with optional date/type filtering.

    Powers the sourcemap Activity tab and any org-wide audit stream.
    """
    from app.core.db.models.entity_event import EntityEvent

    org_id = UUID(g.org_id)
    try:
        limit = min(int(request.args.get("limit", 150)), 500)
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "limit and offset must be integers"}), 400
    from_date = request.args.get("from_date", "")
    to_date = request.args.get("to_date", "")
    entity_types_param = request.args.get("entity_types", "")

    db = db_session()
    q = db.query(EntityEvent).filter(EntityEvent.org_id == org_id)

    if entity_types_param:
        allowed = [t.strip() for t in entity_types_param.split(",") if t.strip()]
        if allowed:
            q = q.filter(EntityEvent.entity_type.in_(allowed))

    if from_date:
        try:
            fd = datetime.strptime(from_date, "%Y-%m-%d").replace(tzinfo=UTC)
            q = q.filter(EntityEvent.created_at >= fd)
        except ValueError:
            pass

    if to_date:
        try:
            td = datetime.strptime(to_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=UTC)
            q = q.filter(EntityEvent.created_at <= td)
        except ValueError:
            pass

    total = q.count()
    events = q.order_by(EntityEvent.created_at.desc()).offset(offset).limit(limit).all()

    return jsonify(
        {
            "total": total,
            "offset": offset,
            "events": [
                {**_event_to_dict(ev), "summary": _human_summary(ev), "diff_rows": _event_diff_rows(ev)}
                for ev in events
            ],
        }
    ), 200

def register_routes(bp):
    """Keep activity URLs and endpoint names on the Core blueprint."""
    bp.add_url_rule(
        "/api/core/entities/<entity_type>/<entity_id>/story", view_func=entity_story, methods=["GET"]
    )
    bp.add_url_rule(
        "/api/core/entities/<entity_type>/<entity_id>/summary", view_func=entity_summary_detail, methods=["GET"]
    )
    bp.add_url_rule("/api/core/entities/activity", view_func=entity_activity_feed, methods=["GET"])
