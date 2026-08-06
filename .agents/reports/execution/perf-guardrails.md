# PERF-GUARDRAILS: execution
date: 2026-08-02
verdict: clean

## Scope
Execution's own routes already measured: `/core/flows`, `/core/executions/live`,
`/api/core/executions`. `complete_step` (POST, per-execution/per-step dynamic path) and
`/api/core/evidence/*` are not in `.agents/perf/budgets.json`'s measure lists.

## Static
```
uv run python scripts/perf_triage.py --json
routes: 153 considered, 18 measured
static findings: 0 (semgrep N+1 rules — matches security-audit's own semgrep pass)
unmeasured_hot_areas: []
```
`perf_triage.py`'s own heuristic (static N+1 findings weighted by severity, fused with
route surface) does not flag `complete_step` or the evidence routes as a hot gap
requiring a new measured entry.

## Measured
```
uv run pytest tests/e2e/test_perf_budgets.py -q
18 passed
```
Execution's already-measured routes, post-fix:

| route | backend_ms | queries | budget (backend_ms / queries) |
|---|---|---|---|
| `/api/core/executions` | 4.9 | 3 | 150 / 15 |
| `/core/executions/live` | 3.9 | 2 | 50 / 5 |
| `/core/flows` | 3.9 | 2 | 50 / 5 |

All well inside budget; no ceiling or budget breaches anywhere in the 18-route
measurement set. None of this review's fixes touched a hot loop or added a query inside
an existing request path (the `execution_warnings` fix changes what gets written, not
how many statements run; the two tenant-isolation joins add one `JOIN` each to
already-single-row lookups keyed by UUID; the evidence `step_id` validation reuses
`execution.execution_steps`, already loaded by the preceding `get_execution_with_steps`
call — no new query).

## Not added
`complete_step` and `/api/core/evidence/upload` were not added to the measure lists.
Both are POST routes needing a real `execution_id`/`step_id` (and a multipart file, for
evidence) to measure meaningfully — `test_perf_budgets.py`'s current dynamic-body
support (the dilution-calculator's `{route, method, body}` form) assumes a static body,
not IDs minted per test run. Given `perf_triage.py` doesn't flag either as a hot area
and `complete_step`'s heaviest cost (inventory row locks, unit conversion) is already
covered by `TestN1Guard`-style query-count assertions at the unit level
(`tests/test_dag_traversal.py`) rather than this suite, extending the harness to support
per-run dynamic setup is left as a follow-up rather than done inline here — it's
infrastructure work on `test_perf_budgets.py` itself, not a budget-file edit, and this
review's own findings don't point at a perf regression that would justify it now.

VERDICT: clean
