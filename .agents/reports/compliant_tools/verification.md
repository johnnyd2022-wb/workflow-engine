# Verification chain — compliant_tools

Preflight: `verification_mode=herdr-tabs`, `grader_engine=codex`, `live_server_tests=skip`
(dev server started by the orchestrator before E2E). Codex graders (spec-critic,
build-review, security-tenant-audit, test-evaluator) run as independent `codex exec`
processes; the Sonnet tool-driven stages were run directly by the orchestrator (semgrep,
gitleaks, uv audit, alembic reversibility, the full pytest + E2E suites, perf/N+1 scan,
ci-gate collection checks) with results reported here verbatim.

| Stage | Verdict | Report |
|---|---|---|
| spec-critic (×4) | sound (13→9→5→sound) | spec-critic.md |
| build | green | build.md |
| build-review (advisory) | 8 findings, all fixed | build-review.md |
| migration-safety | clean | this file, below |
| security-audit (scanner) | patched (1 semgrep, fixed) | security-audit.md |
| security-tenant-audit | no crit/high/med; 2 low (1 fixed, 1 accepted) | security-audit.md |
| e2e-playwright | patched (`hx-boost` fix) | this file, below |
| perf-guardrails | clean | this file, below |
| observability | clean | this file, below |
| test-author (test-map reconcile) | clean | this file, below |
| test-evaluator | see spec-critic.md tail | test-evaluator.md |
| ci-gate | patched (semgrep suppression) | this file, below |

## migration-safety — clean

`feature_subscriptions_001` (down_revision `system_findings_cache_001`), single alembic
head. `upgrade → downgrade → upgrade` verified against the test DB three times over the
session. `downgrade()`:
- checks `to_regclass('public.feature_subscriptions')` first — if absent, logs
  "table already absent" and returns (no crash on a re-run / partial state);
- else logs a WARNING with the exact row count and "irrecoverable except from a prior
  CSV export";
- drops the index then the table.
No existing table's column is renamed/dropped. `destructive: yes` in the spec; the
runbook (export/restore commands) is in the migration docstring and leads the MR.
AC18 test (`test_ac18_migration_downgrade_logs_row_count`) asserts the warning + count.

## e2e-playwright — patched

Dev server started by the orchestrator (`uv run workflow start`, port 8005).
- **compliant-platform** (74) + **process_templates** E2E: green after adding
  `_grant_compliant(org_id)` to both suites' conftests (their fixtures minted an org but
  never granted the new `compliant` subscription → 404 without it).
- **AC19** `tests/e2e/compliant-platform/test_tools_flow.py` (5): dilution +
  standard_drinks fill→submit→rendered-result, validation-error render, unsubscribed →
  404 + no nav item, old `/dilution-calculator` URL → 404. **One fix applied**: the
  Tools forms needed `hx-boost="false"` (base_spa sets `hx-boost="true"` on `<body>`, so
  htmx was hijacking the submit as a boosted GET) — same opt-out the old dilution page
  used.
- Obsolete `tests/e2e/test_dilution_calculator_flow.py` (tested the removed standalone
  page) deleted; its coverage is now AC19 + the migrated unit suite.
- Full E2E run (pre-fix baseline): 392 passed, 3 failed, 2 errored — every failure was a
  shared-test-DB collision (`relation "feature_subscriptions" does not exist`) from a
  concurrent `alembic downgrade` reversibility check dropping the table mid-run, plus
  `purge_org` then failing to clean it. All 5 re-run green with the table present; the
  context processor was additionally made fail-safe (below).

## perf-guardrails — clean

- `.agents/perf/budgets.json` `measure` lists updated: `/dilution-calculator` →
  `/compliant/tools`, `POST /api/dilution-calculator/solve` →
  `POST /api/compliant/tools/dilution/solve`.
- semgrep N+1 / query-in-loop rules on the gate + tools routes + context processor +
  repo: **no findings**. The subscription gate adds exactly one indexed
  `feature_subscriptions` lookup per compliant request (cached on `g` for the page
  render); the catalogue is loaded once at import. No new heavy path.
- The subscription-gated routes (`/compliant`, `/compliant/tools`,
  `/api/compliant/overview`) `pytest.skip` in the perf tier for the shared unsubscribed
  session user — the sanctioned behaviour for a non-measurable route (`test_perf_budgets`
  already skips on `status >= 400`); route correctness is the E2E tier's job.

## observability — clean

- `tools_routes.py` emits `compliant.tool_solved` (info, `tool=<key>`) and
  `compliant.tool_rejected` (warning, `tool`, `reason`) — the `<slug>.<verb_past>`
  convention. The gate emits `access_denied` / `reason=org_not_subscribed` /
  `feature=compliant`. The fail-safe context processor emits
  `compliant_subscription_check_failed` on a lookup error.
- `app/observability/context.py`: `dilution_calculator.*` blueprint→feature mappings
  removed; `compliant`, `compliant.compliant_api`, `compliant.compliant_pages`,
  `compliant.compliant_tools` → `"compliant"` added, so the relocated calculator and the
  whole Compliant area attribute correctly (was falling through to `platform`).
  `tests/test_observability_context.py` updated (compliant nested-app test).
- OTEL auto-instruments the Flask routes + DB; pure calculators need no manual spans.

## test-author — clean

`.agents/test-map.md` reconciled: the "Dilution calculator" section became
"Compliant — per-org subscription & tools" with rows 24–27 (dilution relocation,
entitlement primitive, subscription gate, tools suite). `last_synced` bumped.
`scripts/test_map_check.py` structural check: the only new "dangling" row is
`test_tools_flow.py` (an `tests/e2e/` path — the map already references e2e files this way,
e.g. `test_crm_flow.py`), consistent with the existing convention.

## ci-gate — patched

CI-exact commands run locally:
- `ruff check app/` — clean. `ruff format app/` — only pre-existing `main` drift in 4
  files not in this diff (CI's `ruff` job reformats without `--check`, doesn't fail).
- `semgrep --config .semgrep/rules/ app/ --include='*.py' --include='*.js' --error` —
  initially exit 1 on `no-stdlib-getlogger` in the migration; **fixed** with an inline
  `# nosemgrep: no-stdlib-getlogger` + rationale (a migration can't use app logging).
  Now exit 0.
- `gitleaks detect --log-opts=main..HEAD` — no leaks.
- `uv audit` — no vulnerabilities; no dependency changes.
- `skill_metrics.py --check` / `finding_history.py --check` / `agent_launch.py --check`
  (the `data_stores` job) — all pass; routing table unchanged (graders stay `access:
  read` in the table — test-evaluator was run locally with `workspace-write` only so it
  could execute pytest for mutation probes; `git diff` after confirms it edited nothing).
- New test files collect (119 tests across the 4 new py files); node JS tests run via the
  `test_execution_shared_utils_js.py` wrapper.
- Full pytest suite: **1799 passed, 5 skipped, 0 failures** (unit/integration).

## MR & pipeline

- MR: https://gitlab.com/whistlebird/workflow-engine/-/merge_requests/198 (`nz-alc-tools` → `main`, assignee johnnyd2022, not draft).
- Merge-request pipeline `2801634254` (`merge_request_event`): **passed** — `ruff`,
  `unit_tests`, `semgrep`, `semgrep_observability`, `semgrep_learned_rules`, `gitleaks`,
  `uv_audit`, `lockfile_consistency`, `data_stores`, `migration_reversibility` all green.
  (No Playwright job in the MR pipeline — e2e was verified locally: compliant-platform 74
  + process_templates + AC19 5, all green.)
- Push pipeline `2801634154`: `semgrep-sast` green.
- Announced in `#code-changes` (Slack).
