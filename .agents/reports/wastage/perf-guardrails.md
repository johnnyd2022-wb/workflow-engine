# PERF: wastage
date: 2026-08-11

## Measure lists updated
`.agents/perf/budgets.json` → `measure.pages` had no entries for this slice's two page
routes (only `/api/core/inventory/wastage` was already measured, as `api`). Added:
- `/core/inventory/dispose`
- `/core/inventory/dispose/confirm`

`/core/inventory/dispose/confirm` has no query params in this measurement (the `pages`
list is bare route strings, no per-route param support like the `api` list's
`{route, method, body}` form) — it measures the "Missing inventory item id." error-state
render, not the populated-preview happy path. Still a legitimate, real code path (auth +
template + tenant-context middleware all execute), just not the richest one. Noted as a
known limitation rather than silently presented as full coverage.

## scripts/perf_triage.py
No N+1 or other static findings for wastage's files (`backend.py` wastage functions,
`wastage_repo.py`, `inventory_wastage_quantity.py`).

## Measured (test-DB, empty-ish baseline org, 2026-08-11)
| route | kind | backend_ms | queries | lcp_ms | budget/ceiling status |
|---|---|---|---|---|---|
| `/api/core/inventory/wastage` (list) | api | 5.5 | 3 | — | well under budget (150/1000ms, 15/60 queries) |
| `/core/inventory/dispose` | page | 4.4 | 2 | 56 | well under budget (50/500ms, 5/20 queries, 1000/5000ms LCP) |
| `/core/inventory/dispose/confirm` | page | 4.3 | 2 | 68 | well under budget (error-state render, see note above) |

All three: `over_budget: []`, `over_ceiling: []`.

## Test
```
pytest tests/e2e/test_perf_budgets.py -k "dispose or (wastage and api)"
3 passed
```

VERDICT: clean
