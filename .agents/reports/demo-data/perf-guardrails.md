# PERF: demo-data
date: 2026-08-23
verdict: within-budget (not measured — deliberately excluded, see below)

## Decision: not added to `.agents/perf/budgets.json` measure lists
`demo-data` has one route, `POST /api/core/reset-demo-db`, and no page. Per the skill's
"keep the measure lists lean: core pages and their data endpoints, not every route"
rule, this route is deliberately excluded:

- It is a dev/test-only destructive admin action (wipes and reseeds a fixed org's data),
  not on any user's steady-state critical path — nothing else in the app calls it as
  part of normal operation, and it 403s outright outside `test`/`local`
  (`app/features/demo_data/routes/api_routes.py:26-29`).
- It is expected and intended to be relatively heavy (creates a process, 5 steps, an
  execution, 4+ raw materials, and per-step WIP/output inventory rows in one request) —
  a tight query-count ceiling here would not be measuring a regression, it would be
  measuring the fixture's own fixed shape, which the skill's "never raise a ceiling to
  get green" rule cuts the other way on: don't set one that has no signal to catch.
- `scripts/perf_triage.py --json` (run 2026-08-23) surfaces zero static findings for
  `app/features/demo_data/` — no N+1 patterns flagged.

## Existing measurement run
No regression risk to other measured routes: this review's only production code change
(`app/features/demo_data/routes/api_routes.py`) adds one extra `unscoped()`-wrapped
`get_user_by_email` lookup inside `/api/core/reset-demo-db` itself (not on any other
route's path), consistent with the decision above to leave it unmeasured.

## Handoff
If `reset_demo_db` is ever wired into a customer-facing flow (rather than staying an
internal/demo-only reset button), revisit this decision and calibrate a budget from a
real run per the skill's step 4.
