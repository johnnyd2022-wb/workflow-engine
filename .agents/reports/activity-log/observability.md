# OBSERVABILITY: activity-log
date: 2026-08-09
verdict: patched

## Added: `access_denied` logging on empty-result lookups

Same pattern as `_log_process_access_denied` (process-design) and `_log_trace_access_denied`
(traceability, added in yesterday's review): a story/summary lookup that resolves to nothing
for the caller's org is a tenant-boundary probe just as much as a stale/mistyped id, and the
route's response can't distinguish the two (AC3/AC10 — cross-org existence must not be
distinguishable from non-existence), so the log doesn't try to either.

New helper `_log_activity_access_denied(org_id, entity_type, entity_id)`
(`backend.py:4901-4917`), wired into:
- `entity_story`: fires when `total == 0` and the post-legacy-merge `event_dicts` is still
  empty (so a genuinely-new inventory item with only a not-yet-matched legacy audit entry
  does *not* false-positive).
- `entity_summary_detail`: fires when both `summary_row is None` and `recent_events` is
  empty — i.e. nothing at all resolves for this org, not merely "no computed summary yet"
  (which is routine, per AC10, and must not be treated as a probe).

Added as defense-in-depth telemetry specifically because of F1
(`.agents/reports/activity-log/security-audit.md`): `entity_summary_detail`'s missing
`org_id` filter was a live, confirmed cross-tenant leak with zero server-side trace before
this review. If the filter ever regresses, or if the vulnerability was exploited before this
fix, this is the signal that would show it.

`entity_activity_feed` was not instrumented this way — it is an org-wide feed, not a
specific-entity lookup, so there is no single "found or not" outcome to log against.

## Regression tests

`tests/test_activity_log.py::TestActivityLogAccessDeniedLogging` (3 tests, same shape as
`tests/test_traceability.py::TestTraceAccessDeniedLogging`):
- empty story lookup emits `access_denied` with `entity_not_found_or_cross_org`
- empty summary lookup emits `access_denied`
- a real, own-org lookup does **not** emit `access_denied` (guards against false-positive
  noise on ordinary traffic)

All three pass; full unit suite re-run clean (90/90), e2e suite re-run clean (12/12).

## Not instrumented further

- No new Sentry/error-tracking hooks needed — this slice raises no new exception classes;
  the two int()-parse fixes (F2) return clean 400s, already covered by structured
  `http_request` access logging the app factory wires globally (confirmed present in test
  output: every request in this suite already logs `status`, `duration_ms`, `route`,
  `org_id`, `user_id` via `app.observability.access`).
- No OpenTelemetry span changes — the reviewed routes are simple ORM queries with no
  external calls or background work; existing request-level tracing already covers them.

VERDICT: patched
