# Performance priority checklist — GENERATED

Generated 2026-07-18T08:10:09+00:00 by `scripts/perf_triage.py --write-index`. Do not
hand-edit; rerun the script after a page/flow changes or after a perf-test run.
Budgets: `.agents/perf/budgets.json`; measurements: `tests/e2e/test_perf_budgets.py`;
raw last run: `.agents/reports/perf/last-run.json`. Owned by the **perf-guardrails** skill.

- static rules: **ok** (13 findings, shared-frontend score 1)
- routes measured: **14** of 151 considered
- last measured run: 2026-07-18T08:09:58+00:00
- breaches: **0 ceiling (blocking)**, 0 budget (advisory)

| # | priority | kind | where | evidence | action |
|---|---|---|---|---|---|
| 1 | 17 | static-finding | `[core] app/core/backend/reconciliation_service.py` | repository-get-in-for-loop:279(W), sqlalchemy-all-without-limit:147(I), sqlalchemy-query-in-for-loop:342(W) | fix the pattern or justify with a scoped `# nosemgrep` + reason |
| 2 | 14 | static-finding | `[core] app/core/backend/checks/untracked_items.py` | repository-get-in-for-loop:191(W), sqlalchemy-all-without-limit:138(I) | fix the pattern or justify with a scoped `# nosemgrep` + reason |
| 3 | 13 | static-finding | `[core] app/core/frontend/js/common.js` | setinterval-result-discarded:260(W) | fix the pattern or justify with a scoped `# nosemgrep` + reason |
| 4 | 13 | static-finding | `[core] app/core/utils/resetdb.py` | repository-get-in-for-loop:360(W) | fix the pattern or justify with a scoped `# nosemgrep` + reason |
| 5 | 11 | static-finding | `[core] app/core/backend/checks/expired_materials.py` | sqlalchemy-all-without-limit:31(I) | fix the pattern or justify with a scoped `# nosemgrep` + reason |
| 6 | 11 | static-finding | `[core] app/core/backend/checks/output_ready_date_check.py` | sqlalchemy-all-without-limit:317(I) | fix the pattern or justify with a scoped `# nosemgrep` + reason |
| 7 | 11 | static-finding | `[core] app/core/backend/dagtraversal.py` | sqlalchemy-all-without-limit:314(I) | fix the pattern or justify with a scoped `# nosemgrep` + reason |
| 8 | 11 | static-finding | `[core] app/core/frontend/js/core-api.js` | sequential-independent-awaits:364(I) | fix the pattern or justify with a scoped `# nosemgrep` + reason |
| 9 | 11 | static-finding | `[core] app/core/frontend/js/execution-modal.js` | sequential-independent-awaits:49(I) | fix the pattern or justify with a scoped `# nosemgrep` + reason |
| 10 | 11 | static-finding | `[shared-frontend] app/ui/shared/password-policy.js` | sequential-independent-awaits:27(I) | fix the pattern or justify with a scoped `# nosemgrep` + reason |
