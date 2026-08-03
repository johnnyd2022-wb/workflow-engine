# OBSERVABILITY: process-design
date: 2026-08-02
mode: instrument

## Gap found
Every org-scoped lookup miss in this slice (process not found, cross-org process
access, step not belonging to a process, process-doc not found/cross-org) resolved
straight to a generic 404/400 with **no log emitted anywhere**. A genuine tenant-
boundary probe (someone iterating process/step/doc UUIDs across orgs) would be
completely invisible — indistinguishable from a stale bookmark, and prod-sentinel
would have nothing to find.

This app already has an established convention for exactly this
(`app/core/security/permissions.py:23-33` for role denials,
`app/core/db/repositories/inventory_repo.py:123-138` for cross-tenant reference
probes): a `logger.warning("access_denied", reason=..., ...)` call, structured fields,
emitted right before the generic-message response goes out. process-design had none
of it.

## Instrumented
Added the same `access_denied` event (structured: `reason`, `feature="process-design"`,
`org_id`, plus `process_id`/`step_id`/`doc_id` as applicable) at every org-scope-miss
point in this slice:

- `app/core/backend/backend.py`: new `_log_process_access_denied()` helper, called from
  `_assert_flow_process_access` (wizard pages) and `_get_process_or_404` (API CRUD) —
  covers get/update/delete process, add/update/delete step, and the wizard's `?id=`
  resolution.
- `app/core/backend/backend.py` `reorder_steps`: process-not-found and
  step-not-in-process (the `locked_ids` IDOR guard) paths.
- `app/core/backend/process_docs/process_docs_validation.py` `validate_process_and_step`:
  process-not-found and step-not-in-process paths (covers upload + inline SOP writes).
- `app/core/backend/process_docs/process_docs_service.py` `get_file_for_download`:
  doc-not-found-or-cross-org path.

## Deliberately not instrumented
- `process_docs_service.delete_document`'s not-found path: this one is a designed
  idempotent-delete (returns `200 {"deleted": true}` whether the doc never existed,
  already deleted, or belongs to another org — found by this review's e2e pass, see
  security-audit/e2e reports). Logging "access_denied" on a call that returns success
  would misrepresent the log as a denial when the response isn't one; the review's own
  note on this asymmetry stands on its own rather than being folded into this pass.
- Plain validation failures (missing `name`, invalid `category`, malformed UUID,
  invalid `position`) — these are bad input, not tenant-boundary probes; logging them
  as `access_denied` would dilute the signal the event name promises.

## Verification
`uv run ruff check` on all three touched files: clean. Full process-design test suite
(`tests/test_process_design.py` + 3 e2e files, 128 tests) re-run after instrumenting:
128 passed, no regressions.

## Verdict
Instrumented. No live server request was made to visually confirm the log line
renders (would require tailing structlog JSON output during a real cross-org request);
the four call sites were verified by direct code read and the existing test suite
passing confirms none of the response bodies/status codes changed.
