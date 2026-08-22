# CI-GATE: compliant-platform (verify mode)
date: 2026-08-22
stage: run directly by the orchestrator (see perf-guardrails.md note on execution mode).

Not rebuilding the pipeline — `.gitlab-ci.yml` already has every job this feature needs
(pytest, semgrep, semgrep_observability, semgrep_learned_rules, gitleaks, uv_audit,
migration_reversibility, e2e). Verifying coverage per the skill's §4.

## 1. Test collection
`pytest --collect-only -q tests/ | grep -i compliant` — every unit test
(`tests/test_compliant_routes.py`, pre-existing `tests/test_compliant_catalog.py`,
`tests/test_compliant_frontend_assets.py`) and every new E2E file under
`tests/e2e/compliant-platform/` collects. Not orphaned/uncollected.

## 2. Semgrep custom rules
`semgrep --validate --config .semgrep/` → "0 configuration errors, 29 rules" — parses clean.

## 3. Migrations
No new revision added by this review. `alembic heads` → exactly one head
(`compliant_nz_alcohol_001`), unchanged.

## 4. Full local run
```
GATE lint: pass (ruff check + ruff format --check, app/features/compliant/ + changed tests — 1 import-order and 3 formatting issues found and fixed)
GATE unit: pass (155 passed — test_compliant_routes.py, test_compliant_catalog.py, test_compliant_frontend_assets.py, test_execution_modal_frontend_assets.py, test_process_templates.py, e2e/compliant-platform, e2e/process_templates)
GATE semgrep: pass (0 findings — exact CI command: `semgrep --config .semgrep/rules/ app/features/compliant/ --include="*.py" --include="*.js" --error`)
GATE gitleaks: pass (0 leaks in app/features/compliant/, tests/test_compliant_routes.py, tests/e2e/compliant-platform/)
GATE uv_audit: pass (0 known vulnerabilities, 84 packages — no dependency changes this review)
GATE migrations: pass (single head, compliant_nz_alcohol_001; no new revision)
GATE e2e: pass (50/50 tests/e2e/compliant-platform, plus the 2 new perf-budget parametrisations)
GATE perf: pass (0 ceiling breaches; see perf-guardrails.md)
```

Note on the community-ruleset finding mentioned in `security-audit.md` (F1,
`python.flask.security.injection.csv-writer-injection`): that rule is from the `p/flask`
pack security-audit runs for its own broader sweep, not from `.semgrep/rules/` — the
narrower custom set the CI `semgrep` job actually gates on. It still fired as a structural
match on the `writer.writerow(...)` call site even after the fix (can't see through the
`_csv_safe()` wrapper), which is expected and not CI-blocking. No `# nosemgrep` needed
since it isn't part of the enforced ruleset.

## 5. Pipeline
Not pushed yet — this report precedes the merge-request step, which pushes the branch and
watches the real GitLab pipeline (`glab ci status`). Local-green here is not a substitute
for that; it is the required precondition for opening the MR with confidence.

## Nothing weakened
No gate was loosened to get here — no `--error` removed, no coverage threshold lowered, no
`allow_failure: true` added, no test skipped, no `# nosemgrep` added.

VERDICT: clean
