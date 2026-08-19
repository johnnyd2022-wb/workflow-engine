# perf-guardrails — shell

Verdict: **within-budget**

## Scope
Page routes owned by the `shell` slice (spec AC1, AC2, AC4): `/core`, `/core/dashboard`,
`/core/settings`. `/core/integrations` (AC3) is excluded — it's a 302 redirect with no
render, not a measurable page. Static-asset serving routes (`/static/js`, `/static/css`,
`/static/inventory`, `/static/img`, `/ui/shared/<filename>`) are file-serving, not
page/API routes in this budgets schema's sense, and are out of scope per this stage's
brief.

## Change made
`/core` (the bare hub page, AC1) was not in `measure.pages` — added it to
`.agents/perf/budgets.json` using the `page` defaults (`backend_ms` 50/500,
`lcp_ms` 1000/5000, `queries` 5/20). No recalibration needed — the measured values land
well inside the existing defaults (see below), consistent with the 2026-07-18 baseline
doctrine (page shells ~4ms, LCP 56-108ms, queries 2-11).

## Steps run
1. `python3 scripts/preflight.py --json` — test DB up (`localhost:8401`), all 5 tools
   present, venv ok.
2. `uv run python scripts/perf_triage.py --write-index` (pre-check) — 0 ceiling, 0 budget
   breaches, static semgrep 0 findings.
3. `uv run pytest tests/e2e/test_perf_budgets.py -q` — **25 passed** (12 pages incl. new
   `/core`, 13 API routes).
4. `uv run python scripts/perf_triage.py --write-index` (post-measurement) — re-synced
   checklist against the fresh run; still 0 ceiling, 0 budget breaches, "nothing to
   triage".

## Shell route results (from `.agents/reports/perf/last-run.json`, run
`2026-08-15T09:29:23Z`)

| route | backend_ms | queries | lcp_ms | over budget | over ceiling |
|---|---|---|---|---|---|
| `/core` | 4.2 | 2 | 72 | — | — |
| `/core/dashboard` | 4.4 | 2 | 100 | — | — |
| `/core/settings` | 5.4 | 2 | 80 | — | — |

All three within `page` defaults (`backend_ms` budget 50/ceiling 500, `queries` budget
5/ceiling 20, `lcp_ms` budget 1000/ceiling 5000) by a wide margin — no advisory or
blocking breach on any shell page.

## Static findings
`scripts/perf_triage.py` static semgrep pass: 0 findings (shared-frontend score 0). No
N+1 patterns attributed to the shell area.

## Remediation
None required — no ceiling or budget breach on any shell route.

VERDICT: clean
