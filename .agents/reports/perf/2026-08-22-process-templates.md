# perf-guardrails — process_templates

verdict: within-budget

## What was measured

Added the two routes this feature introduces worth tracking (per the skill's "core
pages and their data endpoints, not every route" guidance) to
`.agents/perf/budgets.json`'s measure lists:

- page: `/core/flows/create/template-catalog`
- api: `/api/core/process-templates`

(The chooser at `/core/flows/create/start` is a near-static render, same category as
the wizard's own step pages, none of which are individually tracked — left out to keep
the list lean.)

Ran `uv run pytest tests/e2e/test_perf_budgets.py -q` (27 measured routes total) and
`scripts/perf_triage.py --write-index`.

## Results

| route | kind | backend_ms | queries | lcp_ms | verdict |
|---|---|---|---|---|---|
| `/core/flows/create/template-catalog` | page | 4.8 | 2 | 68 | within default budget (50ms/1000ms LCP/5 queries) |
| `/api/core/process-templates` | api | 8.2 | 4 | — | within default budget (150ms/15 queries) |

Both comfortably inside the shared defaults — no custom calibration needed (defaults
are ~4x the observed medians already, per the skill's calibration doctrine).

## Breaches

0 ceiling (blocking). 1 budget (advisory) — pre-existing, unrelated:
`/api/core/dashboard/summary` at 39 queries vs its pinned 38-query ratchet. This
feature's diff never touches dashboard/summary code; not investigated further here
(already the top item on the standing priority checklist before this run).

VERDICT: within-budget
