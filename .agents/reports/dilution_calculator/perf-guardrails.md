# perf-guardrails — dilution_calculator

Date: 2026-07-26
Verdict: **within-budget**

## What changed

`dilution_calculator` adds one page (`GET /dilution-calculator`) and one API route
(`POST /api/dilution-calculator/solve`). Both are now in `.agents/perf/budgets.json`'s
`measure` lists, using the existing `defaults.page`/`defaults.api` budgets — no bespoke
override, per the spec's own read (the feature is stateless, no `org_id`-scoped table
touched).

### The POST-with-body gap

The task brief expected an existing pattern in the measure config for API routes that
need a request body. There wasn't one — `tests/e2e/test_perf_budgets.py` only ever sent
bare `page.request.get(route)`, and `measure.api` was a flat list of route strings. I
built the minimal extension rather than skip the route:

- `measure.api` entries can now be either a bare string (unchanged, GET, no body) or an
  object `{"route", "method", "body"}` for routes that need a payload to be measured
  meaningfully. Added:
  ```json
  {
    "route": "/api/dilution-calculator/solve",
    "method": "POST",
    "body": {
      "solve_for": "final_volume_ml",
      "starting_abv": 40,
      "starting_volume_ml": 1000,
      "final_abv": 20
    }
  }
  ```
- `tests/e2e/test_perf_budgets.py`: added `_api_entries()` to normalize both shapes,
  parametrized `test_api_perf_budget` over the normalized list, and for non-GET entries
  fetch CSRF headers via the existing `tests.e2e.conftest.csrf_headers(page)` helper
  (same helper every other mutating-API E2E test in this suite already uses) and send
  via `page.request.fetch(route, method=method, headers=headers, data=body)`.
- `scripts/perf_triage.py`: `build_triage()` built a `set()` over `measure.api`, which
  broke (`unhashable type: 'dict'`) the moment an object-form entry existed. Fixed to
  pull the route string out of either shape before building the measured-routes set.
  Caught this by actually running `perf_triage.py --write-index` per skill step 0/1,
  not just the pytest run — worth flagging since a narrower change (editing only the
  test file) would have shipped a broken triage script.

Kept the measure lists lean (one page, one API route added — no incidental additions).

## Measured (uv run pytest tests/e2e/test_perf_budgets.py -q, ENVIRONMENT unset)

16 passed, 0 ceiling breaches, 0 budget warnings.

| route | kind | backend_ms (median of 5) | queries (max) | lcp_ms (median of 3) |
|---|---|---|---|---|
| `GET /dilution-calculator` | page | 3.9 | 2 | 68 |
| `POST /api/dilution-calculator/solve` | api | 3.1 | 2 | n/a |

Against defaults:
- page: `backend_ms` budget 50 / ceiling 500 — 3.9ms, 92% headroom to budget.
- page: `queries` budget 5 / ceiling 20 — 2, well inside.
- page: `lcp_ms` budget 1000 / ceiling 5000 — 68ms.
- api: `backend_ms` budget 150 / ceiling 1000 — 3.1ms.
- api: `queries` budget 15 / ceiling 60 — 2, well inside.

Both routes clear the generic budgets by a wide margin, as expected for a
zero-DB-per-request feature. The 2 queries on each request are session/auth-middleware
reads (user/org lookups for `@requires_auth`), not anything the feature itself issues —
consistent with the spec's "touches no `org_id`-scoped table" claim. No override needed;
none added.

Reran `uv run python scripts/perf_triage.py --write-index` after measuring: **0 ceiling,
0 budget breaches, "nothing to triage"**. `.agents/reports/perf/priority-checklist.md`
regenerated clean (16 of 153 considered routes measured, static semgrep: ok, 0 findings).

## Files touched

- `.agents/perf/budgets.json` — added `/dilution-calculator` to `measure.pages`, added
  the POST object-form entry to `measure.api`, documented the new object form in `_doc`.
- `tests/e2e/test_perf_budgets.py` — `_api_entries()` normalizer, `test_api_perf_budget`
  now handles GET and POST(+body+CSRF) uniformly.
- `scripts/perf_triage.py` — `build_triage()` route-string extraction fix for the new
  object-form `measure.api` entries.
- `.agents/reports/perf/last-run.json`, `.agents/reports/perf/priority-checklist.md` —
  regenerated build products (per skill: never hand-edited).

## Verdict rationale

`within-budget`: both new routes measured cleanly against the unmodified generic
defaults, zero ceiling or budget breaches anywhere in the 16-route suite, triage
checklist confirms nothing outstanding. The only non-trivial work was extending the
harness itself (POST-with-body support) rather than the numbers — flagged above as a
real gap closed, not assumed pre-existing.

VERDICT: patched
