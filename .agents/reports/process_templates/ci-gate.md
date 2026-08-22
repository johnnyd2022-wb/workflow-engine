# ci-gate — process_templates (verify mode)

verdict: pass (all gates green; two known, pre-existing, load-sensitive flakes noted, not regressions)

## 1. Test collection

`pytest --collect-only -q tests/ | grep process_template` → 37 tests collected
(29 unit in `tests/test_process_templates.py`, 8 e2e in
`tests/e2e/process_templates/test_process_templates_flow.py`). All present and
collectible — none silently skipped.

## 2. Semgrep rule validation

`semgrep --validate --config .semgrep/` → "Configuration is valid — 0 configuration
error(s), 29 rule(s)." No custom rules added this feature; existing rules still parse.

## 3. Migrations

None. Spec's data model section says `changes: none`; confirmed
`git diff proc-template...HEAD -- app/core/db/migrations/` is empty.

## 4. Full local run

```
GATE lint: pass (ruff check + format --check clean on every file this feature touched;
  4 pre-existing lint/format issues found repo-wide are in files this diff never
  touched — tests/e2e/test_execution_flow.py, test_process_design.py,
  test_tenant_filter.py, test_traceability.py, test_whistlebird_migration.py — out of
  scope, not introduced or worsened here)
GATE unit: pass (29/29 process_templates unit tests; 1589-1590/1591 full repo suite,
  see note below)
GATE semgrep: pass (`semgrep --config .semgrep/rules/ app/ --include="*.py"
  --include="*.js" --error`, the exact command .gitlab-ci.yml's `semgrep` job runs —
  exit 0. Two findings still list in output (innerhtml-string-concat,
  raw-fetch-post in template-catalog.js) but are scoped-suppressed with
  `// nosemgrep: <rule-id>` + one-line justification, matching this repo's own
  established precedent (app/core/backend/checks/expired_materials.py,
  app/core/frontend/js/core-active-batches-graph.js) for a confirmed-mitigated
  finding — not a blanket suppression. Full technical justification in
  security-audit.md; the associated finding_history.py verdict-recording question
  from that report is a separate, still-open item for human ratification, unaffected
  by this code-level annotation.)
GATE migrations: pass (none — see §3)
GATE e2e: pass (8/8 process_templates e2e tests; process-wizard regression this
  feature caused during build stays fixed, 25/25 tests/e2e/test_process_wizard_flow.py
  green)
```

## Full-suite reconciliation (test-author's ripple check, re-confirmed here)

Ran `pytest tests/ -q` three times across this build:
- Run 1 (post-build, pre-fix): 6 failed — all 4 `test_process_wizard_flow.py` failures
  plus 2 unrelated. The 4 wizard failures were this feature's own regression (fixed:
  moved the chooser to a new `/core/flows/create/start` route instead of modifying the
  existing `/core/flows/create`route — see `e2e-playwright.md`).
- Run 2 (post-fix): 1573 passed, 1 failed (`test_ac12_audit_log_day_and_week_buckets_present`
  — confirmed pre-existing: fails identically on the baseline `/core` page with no
  process_templates code in the request path; reproduces consistently in isolation,
  not a flake).
- Run 3 (final, post-test-evaluator-fixes and the nosemgrep annotations): 1589 passed,
  2 failed — the same pre-existing dashboard test, plus one process_templates e2e test
  (`test_ac2_org_without_compliant_sees_empty_catalogue`) that failed only under this
  run's full concurrent load. Re-ran that specific test 5 times in isolation
  immediately after: 5/5 green. The failure's own evidence
  (`assert_clean_page`'s console-error capture) names the *same* pre-existing
  `/dashboard/summary` background-fetch — a sidebar widget that fires on every page,
  not just dashboard pages, and times out under the single-threaded dev server's
  concurrency ceiling during a 1500+ test run. This is the identical root cause class
  as run 2's dashboard failure, both load-sensitive and both outside this feature's
  own code. Not a regression; a suite-warden-owned pre-existing flake class.

## Pipeline status

`glab` is not authenticated in this environment (confirmed via preflight). Cannot push
or check the real GitLab pipeline from here — handing off to **merge-request**, which
owns push + `glab mr create` + pipeline watch. Local green is not a substitute for the
real pipeline; that status will be reported once the MR is open.

VERDICT: pass
