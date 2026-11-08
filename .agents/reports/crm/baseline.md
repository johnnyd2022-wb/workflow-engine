# BASELINE: crm
date: 2026-10-18
branch: factory/fd35062c/attempt-1 (cut from origin/main 42078612)
previous baseline: 2026-08-15 (in git history)

## Preflight
`python3 scripts/preflight.py --json`: blockers `venv`, `deps` (fresh worktree), repaired with
`uv sync --extra dev`. Test DB up. `verification_mode: herdr-tabs`, `grader_engine: codex`,
`live_server_tests: skip` (no dev server; not needed, the CRM browser tests run the app
in-process).

## git status
Clean at start. `scripts/feature_index_sweep.py` then rewrote one unrelated line of
`.agents/feature-index.md` (process-templates: never → 2026-08-22, from its existing
`review.md`); kept, since the sweep is the index's source of truth.

## Migration audit
No model or migration changes since the 2026-08-15 audit other than those !527 shipped with
its own migration review; this review changes no models or migrations. Not re-run.

## Test baseline (before any change)
```
env -u ENVIRONMENT uv run pytest tests/test_crm*.py tests/test_*xero*.py tests/test_*contact*.py -q
256 passed
env -u ENVIRONMENT uv run pytest tests/test_sales_matching.py tests/test_sales_traceability.py tests/test_config_xero_token_secret.py -q
39 passed
node --test tests/js/*.test.js        all green
```
Green: no pre-existing CRM failures. (The known `/crm/customers` `line1` page error is MR
!538's, still open and unmerged on this date; it is not in these suites.)
