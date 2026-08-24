# OBSERVABILITY: demo-data
date: 2026-08-23
mode: instrument
verdict: instrumented

## What was missing
The route had zero structured logging on either the success or the rejection paths
before this review (`app/features/demo_data/routes/api_routes.py` only called
`logger.exception` inside the generic-failure branch). A destructive, org-wide
data-wipe-and-reseed action with no INFO trail on success and no WARNING trail on a
rejected caller violated both halves of the observability skill's convention:
"log every state-changing operation at INFO" and "log every rejected authorization or
cross-tenant attempt at WARNING (`access_denied`)".

## What was added
- `access_denied` WARNING (added as part of the F1 security patch, not a separate
  change) — `reason="not_demo_org_member"`, `path`, `method`, `user_id`, `org_id`.
  Matches the event name and field shape used elsewhere in the app
  (`app/core/security/permissions.py:61`, `tests/test_executions.py`'s
  `TestFlowProcessAccessObservability`).
- `demo_data_reset_completed` INFO on a successful reset — `org_id` (the demo org, not
  necessarily the caller's own — same org here since only demo-org members reach this
  line post-patch), `user_id` (the caller who triggered it).

Both event names follow this repo's `snake_case`, not-dotted convention
(`app/features/crm/services/xero_sync_service.py:160` is the skill's own example).

## Tests asserting the new log lines
Per the skill's rule ("logging is code: new event lines get asserted in unit tests
where they matter, especially access_denied"), both are asserted in
`tests/test_demo_data.py` via `caplog` (same pattern as
`tests/test_executions.py::TestFlowProcessAccessObservability`, including building
`flask_app` as a fixture — not inside the test body — so `create_app()`'s
`configure_logging()` call doesn't run after caplog's per-test handler attaches and
silently discard it):
- `test_outsider_org_member_gets_403_forbidden` — asserts an `access_denied` record.
- `test_demo_org_member_can_reset` — asserts a `demo_data_reset_completed` record.

## Gaps, stated honestly
- No trace/span instrumentation added — OTel tracing is app-wide middleware
  (`app/observability/tracing.py`), already handled for this route by virtue of being a
  Flask route; nothing feature-specific needed (reviewed 2026-08-25 by findings-sweep).
- The exception path (`RESET_FAILED`) already had `logger.exception` before this
  review; left as-is, just paired with F2's generic client-facing message.
- No RUM/browser-side event: this route has no dedicated UI of its own in this slice
  (the reset button, if one exists, lives in a settings/demo page outside
  `app/features/demo_data/`) — out of scope here.
