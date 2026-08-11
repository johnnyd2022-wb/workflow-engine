# CI-GATE: wastage
date: 2026-08-11

## Verified this review's additions are covered by existing gates (no new job needed)
- **`test` job** (`.gitlab-ci.yml`): `ENVIRONMENT=test uv run pytest tests/ -v`, no path
  filter — `tests/test_wastage.py`'s 6 new tests and the new
  `tests/e2e/test_inventory_dispose_pages.py` (7 tests) are picked up automatically by
  the existing glob. Chromium is already installed in this job for `tests/e2e/*.py`.
- **`semgrep` job**: `semgrep --config .semgrep/rules/ app/ --error` — scoped to the
  repo's own rules directory, not the broader `p/python`/`p/flask`/`p/owasp-top-ten`
  registry sets security-audit ran ad hoc. No new learned rule was added this session
  (0 findings on wastage's files), so nothing new to register.
- **`semgrep_learned_rules` job**: `scripts/rule_candidates.py verify` — reran locally,
  all 5 existing learned rules still fire on their bug and stay silent on their fix.
  Unaffected by this review (no rule added or changed).
- **perf budgets**: `tests/e2e/test_perf_budgets.py` reads `.agents/perf/budgets.json` at
  import time — the two new `measure.pages` entries this review added
  (`/core/inventory/dispose`, `/core/inventory/dispose/confirm`) are automatically
  parametrized into the existing perf test, no new job needed. Already verified passing
  (perf-guardrails report).

## Lint/format
`ruff check` and `ruff format --check` initially flagged the new files (import ordering,
one genuinely unused import, one pytest-fixture-reuse-via-import F811 false-positive) —
fixed and reverified clean:
```
ruff check app/core/backend/backend.py tests/test_wastage.py tests/e2e/test_inventory_dispose_pages.py
All checks passed!
ruff format --check <same files>
3 files already formatted
```

## Full suite
`pytest tests/ -q` (whole repo, `ENVIRONMENT` unset) launched to confirm no regression
outside wastage's own files; exceeded the 590s foreground timeout (this repo's full
suite, including e2e/perf, runs long) and continued in the background — result folded
into the aggregate review report once it completes.

## No new CI job registration needed
Every new test lands inside an already-gated glob or an already-gated data file
(`budgets.json`). Nothing here needs a new `.gitlab-ci.yml` stanza, pre-commit hook, or
protected-branch rule.

VERDICT: clean
