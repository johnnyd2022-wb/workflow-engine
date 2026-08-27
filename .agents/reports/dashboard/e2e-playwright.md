# E2E: dashboard
date: 2026-08-12
spec: .agents/specs/dashboard.md
invoked_as: chain stage (e2e-playwright) — gap-fill against spec ACs
flake_check: 3/3 clean runs, 29/29 passed each run

## Scope

Ran the existing dashboard-slice E2E coverage, then gap-filled every AC the spec's own
"Notes for the audit" section flagged as untested, prioritising AC15's per-field isolation
gap and AC16/AC17's total absence of coverage for `/api/core/metrics`.

## Pre-existing suites run

| Suite | Result |
|---|---|
| `tests/e2e/test_pages_render.py` | 24 passed (includes `/core/dashboard` clean-render) |
| `tests/e2e/test_smoke.py` | 3 passed (includes AC1's logged-out redirect) |
| `tests/e2e/test_tenant_isolation.py -k dashboard` | 1 passed (`test_org_b_dashboard_summary_excludes_org_a_data`) |

`live_server`-marked suites (2FA) were not run: no dev server is up (`uv run workflow
start`), and they auto-skip with a stated reason per the suite's own gate — not a failure,
per this run's preflight (`live_server_tests: skip`). This suite's own boot (`app_url`
fixture in `tests/e2e/conftest.py`) is independent of that dev server — it starts its own
in-process app — so none of the new tests below needed it either.

## New tests added

All new files live under `tests/e2e/dashboard/` (`conftest.py` + 4 test files, 23 test
functions / 29 collected cases with parametrization). Full suite: **29/29 passed, 3 runs
in a row, no flakes**.

| AC | Test(s) | File |
|---|---|---|
| AC1 | `test_ac1_dashboard_page_highlights_active_nav` | `test_dashboard_page.py` |
| AC2 | `test_ac2_dashboard_shows_inline_error_when_summary_fetch_fails` | `test_dashboard_page.py` |
| AC3 | `test_ac3_window_days_defaults_to_30_when_omitted`, `test_ac3_window_days_rejects_non_integer` (×3), `test_ac3_window_days_empty_string_falls_back_to_default`, `test_ac3_window_days_rejects_out_of_range` (×4), `test_ac3_window_days_accepts_boundary_values` (×2) | `test_dashboard_summary_api.py` |
| AC6 | `test_ac6_task_bucketing_reflected_in_summary_route` | `test_dashboard_summary_api.py` |
| AC7/AC8 | `test_ac7_ac8_compliance_summary_is_well_formed` | `test_dashboard_summary_api.py` |
| AC9 | `test_ac9_action_board_reflects_untracked_item_and_overdue_task` | `test_dashboard_summary_api.py` |
| AC10 | `test_ac10_operations_counts_reflect_new_pending_execution` | `test_dashboard_summary_api.py` |
| AC11 | `test_ac11_operator_actions_week_to_date_counts_user_action` | `test_dashboard_summary_api.py` |
| AC12 | `test_ac12_audit_log_day_and_week_buckets_present` | `test_dashboard_summary_api.py` |
| AC13 | `test_ac13_sales_enabled_with_null_baseline_for_fresh_org` | `test_dashboard_summary_api.py` |
| AC14 | `test_ac14_insight_series_present_for_all_six_series` | `test_dashboard_summary_api.py` |
| AC15 (priority gap) | `test_ac15_dashboard_summary_per_field_isolation` | `test_tenant_isolation.py` |
| AC16 | `test_ac16_metrics_returns_well_formed_shape_for_fresh_org`, `test_ac16_metrics_total_processes_reflects_created_process`, `test_ac16_metrics_inventory_breakdown_by_type`, `test_ac16_metrics_active_executions_counts_real_in_progress_execution` | `test_metrics_api.py` |
| AC16/AC17 (priority gap) | `test_ac16_ac17_metrics_cross_tenant_isolation` | `test_tenant_isolation.py` |
| (bonus, not a numbered AC) | `test_summary_requires_auth`, `test_metrics_requires_auth` | both API test files |

This closes the spec's stated "biggest coverage gap": both `/api/core/dashboard/summary`
and `/api/core/metrics` previously had **zero direct route-level tests** — the former had
only pure-helper unit tests and one marker-string cross-tenant check, the latter had
nothing at all. Every test above hits the real HTTP route through an authenticated
browser session, seeding data through the same APIs the app's own UI uses (inventory,
processes, executions, CRM tasks via `/api/crm/tasks`), not by calling the aggregation
helpers directly.

## AC15: the priority per-field isolation gap

The existing `test_org_b_dashboard_summary_excludes_org_a_data` only asserts a marker
string is absent from the raw response body — real signal, but a leak reaching the
response through a formatted field (a count, a percentage) wouldn't contain that literal
string and would pass undetected. `test_ac15_dashboard_summary_per_field_isolation` seeds
org A across every dimension the summary aggregates — an untracked inventory item, a
process + execution, and an overdue CRM task — then asserts each corresponding field in
org B's response individually: `operations.active_executions`, `operator_actions`,
`audit_log.{day,week}`, `tasks.*`, `action_board.items`/`critical_actions_total`,
`compliance.score`/`top_drivers`/`findings.untracked_items`, and `sales.*`. A sanity
half proves org A itself *does* see all of this data, so the check isn't just seven
fields that are always empty regardless of what leaks.

One correction made while building this: `operator_actions.week_to_date` and
`audit_log.{day,week}` are **not** zero for a freshly-logged-in org B — logging in itself
emits a `user.login` `EntityEvent` with `actor_type="user"` (`auth_routes.py:597-605`),
which is org B's own legitimate activity, not a leak. The test captures org B's baseline
immediately after login and compares against that baseline rather than assuming zero,
which is the correct check — a leak would move the count away from that baseline,
regardless of what the baseline itself is.

## AC16/AC17: the priority zero-coverage gap

`/api/core/metrics` had no test anywhere — not in `tests/test_dashboard_summary.py`, not
in `tests/test_multi_tenant_api.py`/`tests/test_multi_tenant_isolation.py`, not in any e2e
suite. Added:
- route-level correctness (`total_processes`, inventory breakdown by type, well-formed
  shape for a fresh org, auth-gating). Already fixed: present at
  `tests/e2e/dashboard/test_metrics_api.py` (verified 2026-08-25 by findings-sweep).
- the mandatory cross-tenant probe (`test_ac16_ac17_metrics_cross_tenant_isolation`),
  mirroring `test_org_b_dashboard_summary_excludes_org_a_data`'s pattern but per-field:
  org B's `total_processes`/`active_executions`/`completed_executions`/`inventory_items`
  must all read exactly zero after org A creates a process and an inventory item, plus the
  marker-string check and an org-A-sees-its-own-data sanity check. Already fixed: present
  at `tests/e2e/dashboard/test_tenant_isolation.py:138` (verified 2026-08-25 by
  findings-sweep).

**Cross-reference to the parallel security-audit stage**: that stage's report
(`.agents/reports/dashboard/security-audit.md`, finding F1) found that
`operational_counters.counts` in this same response is a process-wide, non-org-scoped
`dict` (`get_counter_snapshot()`) with no `org_id` key at all — a real, already-tracked
tenant-isolation gap in this exact endpoint, contradicting AC17's stated assumption.
`test_ac16_ac17_metrics_cross_tenant_isolation` deliberately does **not** assert equality
on that field between orgs (it would fail, since the leak is real) — this stage's job is
coverage, not remediation, and F1 is already reported with its own recommended fix route
(`fix-bug`, tenant-isolation class). Leaving a known-failing assertion in an otherwise
green, flake-checked suite would misrepresent the suite's health; the gap is called out
here instead so it isn't silently missed by whoever reads only this report.

## AC5 / AC4: explicitly not covered, and why

- **AC5** (`tasks`/`sales` disabled shape when `crm_enabled=false`): `local.ini` — the
  config this E2E boot actually loads (`ENVIRONMENT` unset → `local`) — has
  `crm_enabled = true`. The disabled branch is genuinely unreachable through this suite
  without monkeypatching config, which is unit-test territory (`tests/test_dashboard_summary.py`
  is a better home for it). Not faked with a route-level test that wouldn't actually prove
  the branch.
- **AC4** (dead `window_days` parameter — validated and echoed but never used to scope any
  query): the spec explicitly flags this as "worth a product/API-contract decision, not
  just a test." Writing a test that locks in `window_days=7` and `window_days=90`
  returning identical data would encode a likely bug as a guaranteed contract. Left
  untested here, per the spec's own instruction to flag rather than silently fix in either
  direction.

## Tooling note: `scripts/e2e_coverage.py` under-reports subdirectory suites

`e2e_coverage.py --check` still lists `/api/core/metrics` and `/api/crm/tasks` (POST) as
gaps after this change — not a real gap, a script limitation: it globs
`E2E_DIR.glob("test_*.py")` (`scripts/e2e_coverage.py:120`), which is **non-recursive** and
never sees `tests/e2e/dashboard/*.py`, `tests/e2e/activity_log/*.py`,
`tests/e2e/reconciliation/*.py`, or `tests/e2e/traceability/*.py` — every subdirectory
suite in the repo, not just this one. Confirmed by running it before/after this change:
the gap list for `/api/core/metrics` is unchanged despite five new passing tests hitting
that exact route. Not fixed here — out of this stage's write scope (`tests/e2e/` and this
report only) — flagged so the next person reading `--check`'s output doesn't take it as
ground truth for anything under a subdirectory.

## Verification

```
uv run pytest tests/e2e/dashboard -q   # 29 passed, ×3 consecutive runs
uv run ruff check tests/e2e/dashboard/          # clean
uv run ruff format --check tests/e2e/dashboard/ # clean
```

Handing off to `ci-gate` to make this a required check, per the skill's standard next
step.

VERDICT: findings-open
