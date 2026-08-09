# OBSERVABILITY: traceability
date: 2026-08-09
verdict: patched

## Gap found

None of the 5 routes in scope logged anything when a trace lookup was rejected. The three
that return 404 on a cross-org or nonexistent item (`trace_raw_material`,
`trace_inventory_backward`, `sourcemap_trace`'s current-state branch) turned the rejection
into a generic 404 with no server-side trace at all — matching the exact gap
`_log_process_access_denied` (process-design) and `InventoryRepository`'s `_deny()` helper
(inventory) already close for their own routes, just not extended to this slice's three
lookups.

## Fix

Added `_log_trace_access_denied(org_id, item_id)` in `app/core/backend/backend.py`
(alongside the existing `_log_process_access_denied`), emitting the same `access_denied`
event name the auth decorators and inventory repo use — `reason="inventory_item_not_found_or_cross_org"`,
`feature="traceability"`, `org_id`, `item_id`, `path`. Wired into all three 404 sites:

- `trace_raw_material` (raw material not found)
- `trace_inventory_backward` (inventory item not found)
- `sourcemap_trace`'s current-state (`as_of`-absent) branch (item not found)

**Deliberately not added to the temporal (`as_of`-present) branch.** After this review's F1
fix, that branch no longer 404s on a cross-org `root_id` — it returns 200 with `root.state:
null`, indistinguishable from a legitimate own-org item that simply has no event history yet
(AC17's documented "nameless" behavior for nodes with no pre-`as_of` events). Logging
`access_denied` there would fire on every ordinary "new item, no history" temporal trace and
bury the real signal in noise. If the temporal branch needs its own probe-detection later,
it needs a genuinely different signal (e.g. distinguishing "org has zero events for this
entity at all" from "org has this entity but no events before `as_of`"), which is future
work, not this review's scope.

## Regression coverage

`tests/test_traceability.py::TestTraceAccessDeniedLogging` (3 tests) — one per patched call
site, following the existing `test_cross_tenant_reference_rejection_emits_access_denied`
pattern in `tests/test_inventory.py` (`caplog.at_level(logging.WARNING)`, assert an
`access_denied` record exists). All pass; ran alongside the rest of
`tests/test_traceability.py` (16/16 green).

## Not touched

Structured request/response logging (`app.observability.access` middleware) already covers
every route in this slice automatically — confirmed in the live server logs captured during
e2e test runs earlier this review (e.g. `route: core.trace_raw_material`, `status`,
`duration_ms`, `org_id`, `request_id`, `correlation_id` all present per request). No gap
there; this report only closes the object-level-authorization-denial gap, which is a
different signal than "a request happened."
