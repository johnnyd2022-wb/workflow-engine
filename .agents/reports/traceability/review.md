# REVIEW: traceability
date: 2026-08-09
baseline: tests green (60/60 pre-existing tests in test_dag_traversal.py + test_inventory.py,
  the two files with pre-existing coverage touching this slice's shared traversal engine).
  No test at all existed for the slice's own routes/temporal tracer before this review
  (`.agents/reports/traceability/baseline.md`) — this is the traceability slice's first-ever
  review (feature-index showed `computed_status: never`).
verdict: patched

| stage | verdict | findings | report |
|-------|---------|----------|--------|
| migration audit | n/a | slice owns no models/migrations (entity_events/process_versions belong to platform) | this file, §Migration audit |
| security-audit | findings-open → patched | F1 (high, cross-tenant snapshot leak), F2 (dead/broken import, 500s), F3, F4 (unhandled int parsing) — all fixed | security-audit.md |
| e2e-playwright | findings-open → patched | 20 new tests, 0 prior coverage; documented AC10 as a follow-up, later added | e2e-playwright.md |
| unit coverage (orchestrator, in place of a separate test-author stage) | closed | temporal_dag_tracer.py 0% → 94%; 23 new tests in test_traceability.py | this file, §Coverage |
| security-tenant-audit | findings-open → 1 fixed, 1 routed | G1 (medium, write-side gap outside this slice, confirmed+routed) · G2 (low, fixed) | security-tenant-audit.md |
| test-evaluator | valid | 2 non-blocking coverage-boundary notes, both closed | test-evaluator.md |
| perf-guardrails | clean | 2 routes added to budgets.json, both well within budget; 3 routes documented as unmeasurable by the current harness (id-requiring) | perf-guardrails.md |
| observability | patched | 3 routes were missing `access_denied` logging on rejected lookups; added + tested | observability.md |
| ci-gate | clean | everything above is in the existing blanket `pytest tests/ -v` CI job; ruff/semgrep/gitleaks/agent_launch/finding_history all clean | ci-gate.md |

## Summary

This slice (`/core/sourcemap`, forward/backward trace, on-demand current+temporal trace, the
sourcemap objects index) had never been reviewed and had zero direct test coverage —
confirmed accurate by this review. Two independent read-only graders (security-audit on
Claude, security-tenant-audit on Codex) plus one live TDD-style regression pass found six
real defects, five patched in this review and one routed to its correct owner.

### Fixed in this review

1. **F1 (high) — cross-tenant entity-state leak.** `POST /api/core/sourcemap/trace`'s
   temporal (`as_of`) branch never checked `root_id` belonged to the caller's org before
   calling `TemporalDAGTracer.trace()`, and `_snapshot_at()`
   (`temporal_dag_tracer.py:121-134`) queried `EntityEvent` by `entity_id` alone. Any
   authenticated user who supplied another org's item UUID as `root_id` got that item's
   full latest-event snapshot (name, quantity, supplier, etc.) back in the response's
   `root.state`. Fixed with a one-line `org_id` filter addition. Regression:
   `tests/e2e/traceability/test_tenant_isolation.py::test_ac9_temporal_trace_root_state_not_visible_cross_tenant`
   (a real two-org browser session).
2. **F2 — dead, broken route branch.** The same route's `as_of`-absent branch imported
   `app.features.workflow_engine.dagtraversal`, a module that does not exist anywhere in the
   repository, and even if it did, called it with the wrong call signature and return shape.
   Every request into this branch raised inside a bare `except Exception` → 500. Not
   user-visible (the only frontend caller always sets `as_of`), but a live authenticated
   route silently breaking its documented alternate mode. Fixed by routing to the real,
   already-working `app.core.backend.dagtraversal.trace_forward`/`trace_backward`, matching
   the call pattern the two sibling GET routes already use. Regression:
   `tests/test_traceability.py::TestCurrentStateTraceBranch` +
   `tests/e2e/traceability/test_sourcemap_page.py::test_ac10_sourcemap_trace_dispatch_without_as_of_returns_current_state_graph`.
3. **F3/F4 — unhandled `ValueError` → 500** on non-numeric `page`/`limit`
   (`GET /api/core/sourcemap/objects`) and `depth` (`POST /api/core/sourcemap/trace`). Both
   wrapped in try/except returning 400. Regression:
   `tests/test_traceability.py::TestSourcemapObjectsPageLimitParsing`,
   `TestSourcemapTraceDepthParsing`.
4. **G2 (low) — missing defense-in-depth `org_id` filter** on a second `EntityEvent`
   re-query in the same temporal branch (`backend.py:5741`). Not independently exploitable
   via the current call path (the ids were already pre-scoped upstream), but free and
   consistent with the codebase's established re-scope-every-hop convention — fixed.
5. **Observability gap** — none of the three lookup-and-404 routes
   (`trace_raw_material`, `trace_inventory_backward`, `sourcemap_trace`'s current-state
   branch) logged anything on a rejected lookup, unlike the equivalent process/inventory
   patterns elsewhere in this file. Added `_log_trace_access_denied`, wired into all three,
   deliberately **not** added to the temporal branch (would false-positive on ordinary
   "new item, no history yet" traces post-F1-fix). Regression:
   `tests/test_traceability.py::TestTraceAccessDeniedLogging`.

### Found, not patched here — needs follow-up

**G1 (medium) — `ExecutionRepository.complete_step` accepts `actual_inputs`/`actual_outputs`
item references with no org-ownership validation**, which then flow unchecked into
`EntityEvent` payloads that `TemporalDAGTracer` (this slice) reads and trusts. Traced this to
its root cause independently (not just accepting the grader's framing) — see
`security-tenant-audit.md` §"New finding G1" for the full trail. The actual exposure through
this slice is low (a bare foreign UUID could appear as a node id with `state: None` always —
no name/quantity/other data attached, per the intentional non-root-state-is-always-None
design, AC17). The fix belongs in `app/core/db/repositories/execution_repo.py::complete_step`
— the `execution` slice's own file, already reviewed 2026-08-02, flagged in the feature index
as "the highest-risk function in the app... read all of it before changing any of it" (615
lines). Patching it as a drive-by here would be exactly the scope creep this review's own
spec warns against. **Recorded `confirmed` in the finding history**
(`app/core/db/repositories/execution_repo.py`, kind `unvalidated-cross-tenant-item-ref`) so a
future `execution`-slice review or a targeted `fix-bug` picks it up with the correct file
attached — this is the one open item from this review.

## Migration audit

No migration files or ORM models are owned by this slice. `entity_events`,
`entity_event_summaries`, and `process_versions` (which `TemporalDAGTracer` reads) belong to
the platform layer per `.agents/feature-index.md`; this slice only reads them. Nothing to
audit.

## Coverage

| module | before | after |
|---|---|---|
| `app/core/backend/temporal_dag_tracer.py` | 0% (no test referenced it anywhere) | 94% |
| `GET /api/core/inventory/trace/<id>` | covered (2 API tests, pre-existing) | unchanged — already solid |
| `GET /api/core/inventory/trace-backward/<id>` | route untested (function-level only) | covered (e2e + regression) |
| `GET /api/core/sourcemap/objects` | 0% | covered (tenant scoping × 3 entity types, input validation) |
| `POST /api/core/sourcemap/trace` (both branches) | 0% | covered (current-state, temporal, cross-tenant, input validation) |
| `/core/sourcemap` page (frontend) | 0 e2e tests | 20 e2e tests |

`.agents/test-map.md` row 28 added (`last_synced` bumped to 2026-08-09).

## Total new tests: 43

- `tests/test_traceability.py`: 23
- `tests/e2e/traceability/`: 20

All green in the final consolidated run (99 total across this slice's full relevant test
surface, including the 60 pre-existing tests in `test_dag_traversal.py`/`test_inventory.py`
that share the traversal engine).

## History store

7 `finding_history.py record` calls this run: F1, F2, F3/F4 (security-audit, all `fixed`),
G1 (`confirmed`, routed), G2 (`fixed`). No prior verdict on any of these existed to check
against (`decide` calls returned `new` for all — expected, this slice's first review).
