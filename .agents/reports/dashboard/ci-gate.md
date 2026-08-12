# CI-GATE: dashboard
date: 2026-08-12
verdict: clean

## What this review added, and CI coverage for each
- `tests/e2e/dashboard/` (new directory, 4 files, 33 test functions) — covered
  automatically: `unit_tests` job (`.gitlab-ci.yml`) runs `ENVIRONMENT=test uv run pytest
  tests/ -v`, a recursive collection of the whole `tests/` tree. No CI config change
  needed; the job already blocks the pipeline on any failure (`allow_failure: false`).
- `tests/test_dashboard_summary.py` (27 new tests appended) — same job, same coverage.
- `.agents/perf/budgets.json` (added `/api/core/metrics` to the measure list) —
  `tests/e2e/test_perf_budgets.py` reads this file at collection time and parametrizes
  over its `measure.api`/`measure.pages` lists, so the new route is automatically
  measured on the next `unit_tests` run without any CI job change.
- `.agents/history/findings.jsonl` (one `false-positive` record from the test-evaluator
  dispute) — `data_stores` job's `finding_history.py --check` validated clean (`✓ history
  store well-formed`).

## Gates re-verified
```
python3 scripts/finding_history.py --check   # ✓ history store well-formed
python3 scripts/skill_metrics.py --check     # ✓ ledgers well-formed
python3 scripts/agent_launch.py --check      # routing OK
```

## Known limitation, not a gate gap
`scripts/e2e_coverage.py` (flagged in `.agents/reports/dashboard/e2e-playwright.md`) has a
non-recursive glob and under-reports subdirectory E2E suites, including this review's new
`tests/e2e/dashboard/`. It is **not wired into `.gitlab-ci.yml`** — it's a dev-facing
coverage checklist, not a pipeline gate — so this limitation cannot block CI; it can only
mislead a human reading its output. Not fixed here (out of this stage's scope, and the
e2e-playwright report already flagged it for whoever picks up tooling debt next).

## Not applicable to this slice
- `ruff` CI job lints `app/` only, not `tests/` — pre-existing, repo-wide scope, not
  introduced or worsened by this review. Manually verified clean anyway:
  `uv run ruff check tests/e2e/dashboard tests/test_dashboard_summary.py` /
  `ruff format --check` — both clean (see e2e-playwright.md / test-author.md).
- No migration in this slice (no models of its own) — `migration-safety` stage was
  correctly skipped for this review.

VERDICT: clean
