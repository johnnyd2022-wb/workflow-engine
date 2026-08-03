# PERF: process-design
date: 2026-08-02

## Triage
`uv run python3 scripts/perf_triage.py`: 153 routes considered, 18 measured, 0 ceiling
breaches (blocking), 0 budget breaches (advisory), no unmeasured hot areas flagged.
Static semgrep N+1 pass: 0 findings. **Verdict: nothing to triage.**

## Measured routes (already in `.agents/perf/budgets.json` — no additions needed)
`GET /api/core/processes`, `GET /core/processes`, `GET /core/flows` were already in the
measure lists; ran `uv run pytest tests/e2e/test_perf_budgets.py -q` for fresh numbers
(18/18 passed):

| route | kind | backend_ms | queries | lcp_ms | budget status |
|---|---|---|---|---|---|
| `/api/core/processes` | api | 5.3 | 4 | — | well under (budget 150ms/15q) |
| `/core/flows` | page | 3.8 | 2 | 64 | well under (budget 50ms/5q/1000ms) |
| `/core/processes` | page | 3.8 | 2 | 56 | well under (budget 50ms/5q/1000ms) |

`GET /api/core/processes` batch-fetches executions/event-summaries/steps once for the
whole list (backend.py:1216-1247, N+1-avoidance already in place per the code read
during spec reconstruction) — the 4-query, 5.3ms figure confirms that design holds at
this data volume.

## Not measured (by existing app-wide convention, not a gap)
Mutating endpoints — `POST/PUT/DELETE` on processes, steps, reorder, and all of
process-docs — are not in `measure.api`, consistent with the rest of the app (the only
POST entry anywhere in the budgets file is `/api/dilution-calculator/solve`, a
compute-heavy endpoint that specifically warranted it). Not adding process/step
mutation routes here — would be inventing a new pattern this review's scope doesn't
call for, and the triage script found no hot-path signal pointing at them.

## Verdict
Clean. No remediation needed for this slice.
