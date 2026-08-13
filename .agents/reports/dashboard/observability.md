# OBSERVABILITY: dashboard
date: 2026-08-12
verdict: clean (nothing to instrument)

## What this slice actually has
Three GET-only, read-only routes (`/core/dashboard`, `/api/core/dashboard/summary`,
`/api/core/metrics`) with no state-changing operations and no per-ID resource lookups —
unlike `activity-log`/`traceability`, nothing here resolves a `{id}` path segment where a
cross-org request could be indistinguishable from a not-found one, so there's no natural
`access_denied` event to add (that pattern exists elsewhere in the app —
`_log_activity_access_denied`, `backend.py:4926-4943` — because those routes take an
entity id in the URL; this slice's routes don't).

## Existing instrumentation, checked
One log line in the whole slice: `backend.py:4767`,
`logger.exception("Failed to assemble CRM summary for org_id=%s", org_id)`, guarding the
CRM-enabled branch's `except Exception` in `get_dashboard_summary` (AC5). This was
previously **completely untested** — the test-author stage's
`test_dashboard_summary_crm_failure_is_caught_and_logged_not_propagated` (this review, see
`.agents/reports/dashboard/test-author.md`) now asserts the log line fires via `caplog`,
closing the "logging is code, gets asserted in unit tests" gap the observability skill
calls out for `access_denied`-class lines. Its `%s`-placeholder style (rather than the
newer `logger.exception("event_name", org_id=str(org_id))` stable-event-name convention
used in `app/features/crm/services/xero_sync_service.py`) matches every other
`logger.exception` call in `backend.py` (checked: `Error creating process`, `Error
updating process`, `Error completing execution step`, etc. — dozens, same style) — a
file-wide convention predating this slice, not a dashboard-specific deviation. Not
touched: fixing one line while the other ~20 in the same file keep the old style would be
inconsistent spot-patching of a repo-wide pattern, out of this review's scope.

## Considered and rejected
- A log line for the `crm_enabled=false` disabled-shape path: this is expected steady
  state for any non-CRM tenant, not a failure or a denial — logging it on every request
  would be noise, not signal (skill rule: "Noise is a failure mode").
- A log line at the F1 cross-tenant counter leak (security-audit.md): that's a bug to fix,
  not a gap to instrument around; adding a log line there would paper over the leak
  instead of fixing it. Left to `fix-bug` per F1's own recommended route.

VERDICT: clean
