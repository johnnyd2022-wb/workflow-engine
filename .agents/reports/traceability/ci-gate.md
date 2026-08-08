# CI-GATE: traceability
date: 2026-08-09
verdict: clean

## What CI already enforces, unmodified

`.gitlab-ci.yml`'s single `unit_tests` job (`only: [merge_requests, main]`,
`allow_failure: false`) runs `ENVIRONMENT=test uv run pytest tests/ -v` against a real
Postgres service container with the Flask server started (`ci/setup_server.sh`) and
Chromium installed (`uv run playwright install --with-deps chromium`, line 134). This is a
blanket `tests/` collection — no per-file allowlist to update — so everything this review
added is automatically in the gate with no CI config changes needed:

- `tests/test_traceability.py` (23 tests)
- `tests/e2e/traceability/` (5 files, 20 tests)
- The two new `.agents/perf/budgets.json` entries, measured by `tests/e2e/test_perf_budgets.py`
  (already collected by the same blanket `tests/` run — same job, no separate perf stage).

No test in this batch carries `@pytest.mark.quarantined` (the only marker
`pyproject.toml`'s `addopts = "-m 'not quarantined'"` excludes), so nothing added here is at
risk of silently not running.

`semgrep` (`.semgrep/rules/`) and `semgrep_observability` (`.semgrep/rules/observability.yml`)
CI jobs scan `app/` unconditionally — reran both rule sets locally against the two patched
files (`backend.py`, `temporal_dag_tracer.py`): 0 findings. `gitleaks detect` against the
full repo history: no leaks found (the new code has no secrets to leak, and this review made
no credential-adjacent changes).

## Full consolidated local run (mirrors what CI will do)

```
uv run pytest tests/test_traceability.py tests/test_dag_traversal.py tests/test_inventory.py tests/e2e/traceability/ -q
99 passed, 43 warnings in 78.53s
```

`ruff check` and `ruff format --check` on every file this review touched: clean (the CI
`ruff` job — line 74-81 — runs `ruff check app/ --fix` + `ruff format app/`, which this
review's diff already satisfies without needing CI's own auto-fix to do anything).

## Nothing new to wire in

- No new migration (this slice owns none — see the migration-audit note in `review.md`), so
  `alembic_upgrade_downgrade_upgrade`-style reversibility jobs (if any) have nothing new to
  check.
- No new dependency, so `uv_audit` has nothing new to scan.
- `scripts/agent_launch.py --check` and `scripts/finding_history.py --check` (the
  `validate_chain_config` job, `.gitlab-ci.yml:95-98`) — reran locally: both pass. This
  review's `finding_history.py record` calls (7 across security-audit, security-tenant-audit,
  and this stage's own follow-ups) didn't touch the routing table, so nothing to break there.

## What was found and closed as part of getting here

Not this stage's own findings (that's `security-audit`/`security-tenant-audit`'s job) —
recorded here only because ci-gate is the stage that confirms the gate actually holds what
came before it: all 6 findings from this review (F1-F4 from security-audit, G1 routed/G2
fixed from security-tenant-audit) are represented in the test suite this job runs, and the 2
non-blocking coverage-boundary notes from test-evaluator were closed rather than left open.
Nothing in this review's diff ships without a test that would catch its regression.
