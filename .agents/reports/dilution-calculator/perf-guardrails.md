# PERF: dilution_calculator
date: 2026-08-21
role: chain stage (invoked from review-feature)
verdict: clean

## Scope
Both routes already registered in `.agents/perf/budgets.json` → `measure`: page
`/dilution-calculator`, API `{route: "/api/dilution-calculator/solve", method: POST,
body: ...}`. Nothing to add.

## Note: shared file hygiene
Initially ran `pytest tests/e2e/test_perf_budgets.py -k dilution` to measure just this
slice — `.agents/reports/perf/last-run.json` turned out to be a full-replace write, not
a merge, so the filtered run dropped the other 23 routes' data down to 2 entries. Caught
via `git status`/`git diff --stat` before it went anywhere, restored with `git checkout
--`, and re-ran the full `tests/e2e/test_perf_budgets.py` (unfiltered) instead — the
correct way to refresh one route's numbers in a shared tracking file.

## Measurements (fresh, 2026-08-21T08:31:32Z, full 25-route run)
| route | kind | backend_ms | queries | lcp_ms | over budget | over ceiling |
|---|---|---|---|---|---|---|
| `/dilution-calculator` | page | 4.8 | 2 | 72 | none | none |
| `/api/dilution-calculator/solve` | api | 5.0 | 2 | n/a | none | none |

Both well inside budget (page: 50ms/5 queries/1000ms LCP; api: 150ms/15 queries) and
nowhere near ceiling. The 2 queries on both routes are session/auth lookups from
`@requires_auth` (app-wide overhead) — this slice itself touches no ORM model or table
(confirmed independently by security-audit's tenant-isolation check).

## perf_triage.py
```
routes: 164 considered, 25 measured; static: ok (0 findings); last run: 2026-08-21T08:31:32+00:00
breaches: 0 ceiling (blocking), 1 budget (advisory); unmeasured hot areas: none

checklist (highest priority first):
   1. [50] budget-breach   /api/core/dashboard/summary
       queries=39 > budget 38
```
The one advisory breach is `/api/core/dashboard/summary`'s pre-existing, explicitly
ratcheted query-count debt (see `budgets.json`'s own doc note) — unrelated to
dilution-calculator, out of scope for this review, not remediated here.

VERDICT: clean
