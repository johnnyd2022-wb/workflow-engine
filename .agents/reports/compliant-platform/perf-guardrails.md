# PERF-GUARDRAILS: compliant-platform
date: 2026-08-22
stage: perf-guardrails (run directly by the orchestrator, not a launched herdr-tab stage —
this and the remaining stages ran in-process given repeated usage-limit interruptions on
launched sessions earlier in this chain; verification-chain.md §1 treats this as an
equally-valid execution mode, "only execution differs").

## Measured lists updated
`.agents/perf/budgets.json` had no entry for compliant-platform. Added, at the default
budget/ceiling (no override needed — see measurements below):
- `measure.pages`: `/compliant`
- `measure.api`: `/api/compliant/overview` (the dashboard's primary data load — same
  granularity precedent as `/api/crm/overview`, not every route in the blueprint)

## Measurements
```
uv run pytest tests/e2e/test_perf_budgets.py -q
29 passed, 2 warnings in 58.42s
```
```
uv run python3 scripts/perf_triage.py --json
ceiling_breaches: 0, budget_breaches: 1 (pre-existing, unrelated), unmeasured_hot_areas: []
```

| route | kind | backend_ms | queries | lcp_ms | budget | ceiling |
|---|---|---|---|---|---|---|
| `/compliant` | page | 4.1 | 2 | 72 | 50ms/5q/1000ms | 500ms/20q/5000ms |
| `/api/compliant/overview` | api | 5.0 | 4 | — | 150ms/15q | 1000ms/60q |

Both comfortably inside budget on an empty-org baseline (consistent with every other
route's calibration note in the budgets file). No ceiling breach, no override needed.

The one remaining `budget_breach` in the triage checklist (`/api/core/dashboard/summary`,
queries=39 > budget 38) is pre-existing, documented, ratcheting debt unrelated to this
review (`.agents/perf/budgets.json`'s own `_doc` explains the override) — not
compliant-platform's to fix.

## Semgrep N+1 / static findings
`static_findings: 0` in the triage run — no N+1 pattern flagged in
`app/features/compliant/`. Consistent with `service.py`'s own design note that expensive
per-org queries (`records()`, `customs_reconciliation()`) are computed once per request and
threaded through `evaluate()`/`data_coverage()` rather than re-run per section.

VERDICT: clean
