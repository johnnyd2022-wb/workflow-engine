# Performance priority checklist — GENERATED

Generated 2026-08-27T08:27:34+00:00 by `scripts/perf_triage.py --write-index`. Do not
hand-edit; rerun the script after a page/flow changes or after a perf-test run.
Budgets: `.agents/perf/budgets.json`; measurements: `tests/e2e/test_perf_budgets.py`;
raw last run: `.agents/reports/perf/last-run.json`. Owned by the **perf-guardrails** skill.

- static rules: **ok** (0 findings, shared-frontend score 0)
- routes measured: **30** of 170 considered
- last measured run: 2026-08-27T08:27:28+00:00
- breaches: **0 ceiling (blocking)**, 1 budget (advisory)

| # | priority | kind | where | evidence | action |
|---|---|---|---|---|---|
| 1 | 50 | budget-breach | `/api/core/dashboard/summary` | queries=39 > budget 38 | investigate; likely candidates are this area's static findings below |
