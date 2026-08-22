# OBSERVABILITY: compliant-platform
date: 2026-08-22
verdict: patched
stage: run directly by the orchestrator (see perf-guardrails.md note on execution mode).

## App-level plumbing
Already present and unchanged: structlog JSON logging, request-ID binding, OTel
traces/metrics, RUM. `@requires_auth`/`@requires_role` (app/core/security/permissions.py)
already log `access_denied` for unauthenticated/wrong-role requests app-wide — those paths
needed no feature-specific work.

## Gap found and fixed: feature-specific cross-tenant rejections not logged
Before this pass, `app/features/compliant/{routes/api_routes.py,service.py}` had zero
`logger.warning` calls — every feature-owned tenant-boundary rejection turned into a bare
HTTP status with no trace, leaving prod-sentinel/triage nothing to find for a probe against
this feature specifically (as opposed to a plain unauthenticated request, which the shared
decorators already cover). Matches the exact gap class the execution and traceability
reviews found and fixed in their own slices (`.agents/reports/execution/observability.md`,
`_log_process_access_denied`/`_log_trace_access_denied` in `backend.py`) — same
`access_denied` event name, so one log query already covers every slice.

Instrumented two spots in `app/features/compliant/routes/api_routes.py`:

- `get_report` — a report id that parses as a UUID but belongs to another org (or doesn't
  exist) returns the same 404 either way (spec requirement: must not distinguish the two).
  `reason=report_not_found_or_cross_org`, `org_id`, `report_id`.
- `create_record`'s `source_refs` check — a `source_ref` that parses as a UUID but doesn't
  resolve to a real row in *this org's* Execution/ExecutionEvidence/ExecutionStep/
  InventoryMovement tables (`invalid_core_source_references`, already tenant-scoped per the
  security-audit) now logs the rejection instead of silently 400ing.
  `reason=source_ref_not_in_org`, `org_id`, `invalid_source_refs`.

Not instrumented (judgment call, not oversight): the `/compliant/static/<filename>`
path-traversal/bad-extension 400s (`compliant_bp.py`) are input-shape validation, not a
tenant-boundary probe (no org-scoped data lookup involved), so they're out of the
`access_denied` pattern's scope; the 409s for "no enabled profile" (`create_record`,
`create_report`) are a precondition failure, not an authorization rejection, so they stay
as plain 409s per the same reasoning `execution` used for its own non-authz 404s.

## Tests
Same `caplog`-based pattern as `test_executions.py::TestFlowProcessAccessObservability` and
`test_inventory.py`'s existing access_denied tests — added to `tests/test_compliant_routes.py`:

- `test_cross_org_report_lookup_emits_access_denied` / `test_own_org_report_lookup_does_not_log_access_denied`
- `test_cross_org_source_ref_emits_access_denied`

```
uv run pytest tests/test_compliant_routes.py tests/e2e/compliant-platform -q
75 passed, 13 warnings in 133.15s (0:02:13)
```

VERDICT: patched
