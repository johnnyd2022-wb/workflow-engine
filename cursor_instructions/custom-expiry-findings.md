✅ Phase 1 — Fix Database Query Performance (Do This First)
Step 1.1: Remove Python-side filtering in run_output_expiry_check

Locate:

items = session.query(InventoryItem)...all()
items = [i for i in items if ...]

Replace with SQL-filtered query:

from sqlalchemy import func

items = (
    session.query(InventoryItem)
    .filter(InventoryItem.org_id == org_id)
    .filter(InventoryItem.source_execution_step_id == es.id)
    .filter(func.lower(InventoryItem.name) == _normalize(out_name))
    .filter(func.trim(InventoryItem.unit) == out_unit)
    .all()
)
Step 1.2: Add Composite Index (Very Important)

Run migration to add index:

CREATE INDEX idx_inventory_expiry_lookup
ON inventory_item (
    org_id,
    source_execution_step_id,
    lower(name),
    trim(unit)
);
Step 1.3: Remove Post Query Filtering Block

Delete this block:

items = [
    i
    for i in items
    if _normalize(i.name or "") == _normalize(out_name)
]
✅ Phase 2 — Improve Timestamp Handling
Step 2.1 Replace UTC Construction

Search:

datetime.utcnow().replace(tzinfo=timezone.utc)

Replace everywhere with:

datetime.now(timezone.utc)
Step 2.2 Update Normalization Helper

Modify _normalize_dt:

Add branch:

if isinstance(val, (int, float)):
    return datetime.fromtimestamp(val, tz=timezone.utc)

This protects against frontend epoch payloads.

✅ Phase 3 — Frontend Schema Consistency Hardening
Step 3.1 Make Payload Shape Canonical

Ensure frontend always emits:

custom_expiry: {
    enabled: true,
    mode: "fixed_duration" | "set_at_execution",
    duration_value: number | null,
    duration_unit: string | null,
    warning_value: number | null,
    warning_unit: string | null,
    expiry_at: ISO8601 | null
}
Step 3.2 Remove Backend Mode Guessing Logic

Delete fallback inference like:

if not mode:
    if duration_value is not None ...

Replace with strict validation:

if mode not in {"fixed_duration", "set_at_execution"}:
    return None
✅ Phase 4 — Add Backend Invariant Validation (Security Critical)

Inside _get_custom_expiry_config, add:

After parsing config:

if config["mode"] == "fixed_duration":
    if not config["duration_value"] or config["duration_value"] <= 0:
        return None

if config["warning_value"] and config["warning_value"] < 0:
    config["warning_value"] = DEFAULT_WARNING_VALUE
✅ Phase 5 — Add Clock Skew Protection

Modify expiry comparison logic:

Find:

now = datetime.utcnow().replace(tzinfo=timezone.utc)

Replace with:

CLOCK_SKEW_BUFFER_HOURS = 0.5

now = datetime.now(timezone.utc) - timedelta(hours=CLOCK_SKEW_BUFFER_HOURS)
✅ Phase 6 — Audit Logging Monitoring

Inside audit exception block, add:

_log.warning(
    "Audit log failure",
    exc_info=True,
    extra={"event": "custom_output_expiry_audit_failure"}
)
✅ Phase 7 — Remove Redundant Frontend Validation Copies (Medium Priority)

You currently validate warning ≤ expiry in:

Step builder

Execution modal

Collection pipeline

Keep only:

✅ Live UI hint validation
❌ Hard enforcement duplicated in multiple JS locations

Leave backend as authoritative validator.

✅ Phase 8 — Optional (Strongly Recommended for Scale)

If system volume grows:

Add cached check results table:

system_risk_signal_cache
-------------------------
org_id
check_id
entity_id
severity
message
expires_at
last_evaluated_at

Then:

Background worker refreshes signals

UI reads cache instead of computing checks synchronously