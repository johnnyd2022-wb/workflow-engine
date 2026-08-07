# OBSERVABILITY: execution
date: 2026-08-02
verdict: patched

## App-level plumbing
Already present and unchanged: structlog JSON logging, request-ID binding, OTel
traces/metrics, RUM. No Sentry — not proposed. Confirmed the existing execution-slice
code was already heavily instrumented at INFO/DEBUG for state changes and errors
(`complete_step`, evidence upload, DAG traversal all log liberally) before this pass.

## Gap found and fixed: cross-tenant rejections not logged as `access_denied`
The skill's rule: "Log every rejected authorization or cross-tenant attempt at WARNING
(`<slug>.access_denied`)". `app/core/db/repositories/inventory_repo.py` and
`app/core/security/permissions.py` already do this (`logger.warning("access_denied",
reason=..., feature=..., ...)`), but the execution slice's own cross-tenant rejection
points didn't — a probe against another org's process or a forged `step_id` on an
evidence upload turned into an ordinary 404/400 with zero trace, leaving
prod-sentinel/triage nothing to find.

Instrumented two spots, matching the existing `access_denied` event name/shape exactly
(same event name a single log query already covers for auth + inventory):

- `_assert_flow_process_access` (`backend.py`) — every `/core/flows*` view route's
  object-level authorization guard. `reason=process_not_found_or_cross_org`.
  *(Update after rebasing onto main: the process-design review landed the identical fix
  independently, factored into a shared `_log_process_access_denied(org_id, process_id)`
  helper with two other call sites — this review's inline version was replaced by a call
  to that helper during conflict resolution, same event, same effect.)*
- `evidence_service.upload_evidence_from_temp`'s new `step_id` ownership check (added
  by this review per security-audit's F2) — `reason=step_id_not_in_execution_process`.
  This is exactly the class of tenant-boundary probe `_assert_source_refs_belong_to_org`
  already logs for inventory provenance FKs; evidence's equivalent FK gets the same
  trace now.

Not instrumented (judgment call, not oversight): `complete_step`'s "execution step not
found" 404 and evidence's "execution not found" 404 already log a `logger.warning(...)`
with relevant IDs (just not in the structured `access_denied` shape) — left as-is to
keep this pass scoped to the two points with zero existing trace, rather than
reformatting every pre-existing warning log in the slice.

## Tests
Per the skill's rule ("new event lines get asserted in unit tests where they matter,
especially access_denied"), added
`tests/test_executions.py::TestFlowProcessAccessObservability` (2 tests, using the
same `caplog`-based pattern as `test_inventory.py`'s existing access_denied test):
cross-org access emits the log with the right reason; same-org access does not.

**Infra note for future tests in this style**: `create_app()` →
`configure_logging()` unconditionally replaces the root logger's handler list. Calling
`create_app()` *inside* a test body silently discards pytest's `caplog` handler
(already attached during fixture setup), so `caplog.records` comes back empty with no
error — a trap that would otherwise make an access_denied test pass for the wrong
reason (or fail confusingly). Building the Flask app via a fixture (`flask_app`, added
to `test_executions.py`) instead of inline in the test body avoids it, since
`create_app()` then runs during setup, before caplog's handler is attached for that
test. Confirmed empirically with a throwaway diagnostic script before settling on the
fixture-based fix.

```
uv run pytest tests/test_executions.py -v -k FlowProcessAccessObservability
2 passed
```

VERDICT: patched
