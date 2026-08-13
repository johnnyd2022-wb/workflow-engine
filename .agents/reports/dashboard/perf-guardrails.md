# PERF: dashboard
date: 2026-08-12
verdict: clean

## Measure-list gap closed
`/api/core/metrics` was not in `.agents/perf/budgets.json`'s `measure.api` list despite
being a live route in this slice (`/core/dashboard` page and `/api/core/dashboard/summary`
were already present). Added it, using the default `api` budget (150ms/1000ms ceiling,
15/60 query budget/ceiling) — no route-specific override needed, see measured numbers
below.

## scripts/perf_triage.py
```
routes: 153 considered, 24 measured; static: ok (0 findings); last run: 2026-08-12T10:12:08+00:00
breaches: 0 ceiling (blocking), 0 budget (advisory); unmeasured hot areas: none
✓ nothing to triage
```
`--check` exits 0.

## Measured (env -u ENVIRONMENT uv run pytest tests/e2e/test_perf_budgets.py -k "dashboard or metrics")
3/3 passed, no breaches.

| route | kind | backend_ms | queries | lcp_ms | over budget | over ceiling |
|---|---|---|---|---|---|---|
| `/api/core/dashboard/summary` | api | 49.4 | 38 | — | none | none |
| `/api/core/metrics` | api | 9.0 | 6 | — | none | none |
| `/core/dashboard` | page | 4.5 | 2 | 104 | none | none |

`/api/core/dashboard/summary`'s 38-query override (documented, ratcheted debt from
2026-07-18 calibration — "the number must only ever go down") sits at exactly 38, not
regressed by anything added in this review (the new tests exercise the route, they don't
change it). `/api/core/metrics` and `/core/dashboard` are comfortably inside the default
budgets, no override needed.

VERDICT: clean
