# Performance priority checklist — GENERATED

Generated 2026-07-18T07:44:01+00:00 by `scripts/perf_triage.py --write-index`. Do not
hand-edit; rerun the script after a page/flow changes or after a perf-test run.
Budgets: `.agents/perf/budgets.json`; measurements: `tests/e2e/test_perf_budgets.py`;
raw last run: `.agents/reports/perf/last-run.json`. Owned by the **perf-guardrails** skill.

- static rules: **ok** (25 findings, shared-frontend score 1)
- routes measured: **14** of 151 considered
- last measured run: 2026-07-18T07:43:55+00:00
- breaches: **0 ceiling (blocking)**, 0 budget (advisory)

| # | priority | kind | where | evidence | action |
|---|---|---|---|---|---|
| 1 | 41 | static-finding | `[core] app/core/backend/backend.py` | orm-relationship-access-in-loop:1253(W), orm-relationship-access-in-loop:1794(W), orm-relationship-access-in-loop:1794(W), orm-relationship-access-in-loop:4099(W), orm-relationship-access-in-loop:4101(W), repository-get-in-for-loop:2139(W), repository-get-in-for-loop:3227(W), sqlalchemy-all-without-limit:513(I), sqlalchemy-query-in-for-loop:2814(W), sqlalchemy-query-in-for-loop:2826(W), sqlalchemy-query-in-for-loop:514(W) | fix the pattern or justify with a scoped `# nosemgrep` + reason |
| 2 | 16 | static-finding | `[core] app/core/backend/reconciliation_service.py` | repository-get-in-for-loop:279(W), sqlalchemy-query-in-for-loop:342(W) | fix the pattern or justify with a scoped `# nosemgrep` + reason |
| 3 | 15 | static-finding | `[core] app/core/backend/dagtraversal.py` | sqlalchemy-all-without-limit:578(I), sqlalchemy-all-without-limit:635(I), sqlalchemy-all-without-limit:637(I), sqlalchemy-all-without-limit:640(I), sqlalchemy-all-without-limit:723(I) | fix the pattern or justify with a scoped `# nosemgrep` + reason |
| 4 | 13 | static-finding | `[core] app/core/backend/checks/untracked_items.py` | repository-get-in-for-loop:191(W) | fix the pattern or justify with a scoped `# nosemgrep` + reason |
| 5 | 13 | static-finding | `[core] app/core/frontend/js/common.js` | setinterval-result-discarded:260(W) | fix the pattern or justify with a scoped `# nosemgrep` + reason |
| 6 | 13 | static-finding | `[core] app/core/utils/resetdb.py` | repository-get-in-for-loop:360(W) | fix the pattern or justify with a scoped `# nosemgrep` + reason |
| 7 | 11 | static-finding | `[core] app/core/backend/checks/output_ready_date_check.py` | sqlalchemy-all-without-limit:317(I) | fix the pattern or justify with a scoped `# nosemgrep` + reason |
| 8 | 11 | static-finding | `[core] app/core/frontend/js/core-api.js` | sequential-independent-awaits:364(I) | fix the pattern or justify with a scoped `# nosemgrep` + reason |
| 9 | 11 | static-finding | `[core] app/core/frontend/js/execution-modal.js` | sequential-independent-awaits:49(I) | fix the pattern or justify with a scoped `# nosemgrep` + reason |
| 10 | 11 | static-finding | `[shared-frontend] app/ui/shared/password-policy.js` | sequential-independent-awaits:27(I) | fix the pattern or justify with a scoped `# nosemgrep` + reason |
