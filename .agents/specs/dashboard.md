# SPEC: dashboard
status: reviewed
name: Operations Dashboard (summary aggregation, metrics, command-centre UI)
slug: dashboard
blueprint: core_bp — app/core/backend/backend.py (dashboard, get_dashboard_summary, get_metrics)
url_prefix: /core, /api/core

## Description
A composition slice that aggregates six other slices (execution, inventory, wastage,
compliance-checks, activity-log, and — behind `crm_enabled` — crm) into a single
operator-facing landing page. Three surfaces:

- `GET /core/dashboard` — server-rendered shell (`dashboard/dashboard.html`), hydrated
  client-side by one JSON call.
- `GET /api/core/dashboard/summary` — the aggregate endpoint: tasks, compliance score,
  action board, operator/audit activity, operations (today + week-to-date), sales (CRM,
  optional), and six sparkline time series.
- `GET /api/core/metrics` — a separate, older summary endpoint (process/execution/
  inventory counts + per-process operational counters), consumed by the `/core` hub page
  (`core.js`) and the reconciliation flow, not by `dashboard.js` itself.

## Provenance
No spec existed (feature-index: `reviewed: never`). Reconstructed by reading
`app/core/backend/backend.py:4183-4912` (dashboard helpers + both routes),
`app/core/frontend/js/dashboard.js`, `app/core/frontend/dashboard/dashboard.html`,
`tests/test_dashboard_summary.py`, and `tests/e2e/{test_smoke,test_tenant_isolation,
test_pages_render}.py`. `cursor_instructions/core-dashboard-real-data-plan.md` is a design
doc, not a spec — it describes intent (Phase 1–3) and the code implements Phase 1 plus
parts of Phase 2 (operator-actions/audit-log activity feed) but not the sales/ops
alignment or wastage-trend widgets it proposed; ACs below describe what's actually built,
not the plan.

## Users & permissions
- roles: any authenticated user of the org (`@requires_auth` only, no role gate) —
  consistent with the rest of `backend.py` (0 usages of `@requires_org_scope` in the
  file; not a dashboard-specific gap).
- tenant_scoped: yes. Every query in `get_dashboard_summary`/`get_metrics` filters by
  `org_id = UUID(g.org_id)`. CRM data (when `crm_enabled`) goes through `CRMService`,
  which is out of this slice's scope to re-verify but is called with the same `org_id`.
- ASSUMPTION: no route in this slice is reachable by an external/customer principal —
  irrelevant until the enterprise-tier customer login lands (see identity slice notes).

## Acceptance criteria

### Page
- AC1: `GET /core/dashboard` requires auth (redirects/401s when logged out — confirmed
  by `test_logged_out_user_cannot_reach_dashboard`) and renders the shell template with
  `active_page="dashboard"`.
- AC2 (ASSUMPTION): the page performs no server-side data fetch of its own — all data
  comes from the client-side call to `/api/core/dashboard/summary`; a failed fetch shows
  an inline error state (`data-dashboard-error`) rather than a blank/broken page.

### `/api/core/dashboard/summary`
- AC3: accepts `window_days` (default `30`), validates it is an integer in `[7, 180]`;
  a non-integer → 400 `{"error": "window_days must be an integer"}`, out-of-range → 400
  `{"error": "window_days must be between 7 and 180"}`.
- AC4 (ASSUMPTION — flagged as a likely bug, not a confirmed contract): `window_days` is
  validated and echoed back in the response (`"window_days": window_days`) but is never
  used to scope any query — every time window in the response is a hardcoded
  day/week/month boundary (`_dashboard_week_boundaries`, `today.replace(day=1)`). A
  caller passing `window_days=90` gets identical data to `window_days=7`. Written as an
  AC rather than silently accepted because the parameter's presence implies a contract
  it doesn't honor — the audit should decide whether to wire it up or remove it as
  dead/misleading API surface.
- AC5: `tasks` — when `crm_enabled` is false (or the CRM lookup raises), returns the
  disabled shape (`enabled: false`, zero counts, empty `top_tasks`) and the whole
  endpoint still returns 200 (CRM failure is caught and logged, not propagated — see
  the `except Exception: logger.exception(...)` around the CRM block).
- AC6: `tasks` — when CRM is enabled, buckets a caller's open (`pending`/`in_progress`)
  CRM tasks into `due_today_count` (due == today), `overdue_count` (due < today),
  `due_this_week_count` (within the Monday-start current week), and a `top_tasks` list
  of at most 5, sorted by (has-due-date, due date, priority rank high→medium→low→other,
  title) — covered by `test_dashboard_task_bucketing_due_today_and_overdue`.
- AC7: `compliance.score` — computed from four `CoreChecksRunner` check results via a
  versioned (`score_version: "v1"`) deterministic penalty formula: starts at 100, docked
  by capped per-bucket penalties (expired materials, untracked items, output expiry,
  output ready-date — exact weights/caps in
  `_dashboard_build_compliance_summary`), clamped to `[0, 100]`; `top_drivers` lists up
  to 3 nonzero-penalty buckets, worst first — covered by
  `test_dashboard_compliance_score_formula_v1`.
- AC8: `compliance.state` mirrors `system_status.state` from
  `build_system_status_payload` (falls back to `"unknown"` if absent);
  `findings.active_use_risk_count` counts health-mode signals that are both
  `has_issue` and `in_active_use`.
- AC9: `action_board` — builds up to 6 candidate items (expired raw materials,
  untracked items, expired outputs, outputs awaiting ready-date, overdue CRM tasks),
  drops zero-count candidates, sorts by severity rank then count descending;
  `critical_actions_total` sums counts of all non-`informational` items shown (not just
  the 6 returned) — covered by `test_dashboard_action_board_excludes_stalled_batches`.
- AC10: `operations`/`operations_today` — active execution count (PENDING+IN_PROGRESS),
  completed/failed-or-cancelled counts scoped to today and to the current week, week-
  over-week completion percentage (`null` when last week had zero completions, never a
  divide-by-zero), and `stalled_active_over_48h` (active executions started >48h ago).
  Org-isolated — covered by `test_dashboard_operations_summary_org_isolated`.
- AC11: `operator_actions.week_to_date` counts `EntityEvent` rows this week with
  `actor_type == "user"` (i.e. excludes system-generated events).
- AC12: `audit_log` returns both a `day` and `week` bucket (last 10 events each, most
  recent first, humanized via `_human_summary`), each `org_id`-filtered.
- AC13: `sales` — disabled shape (`enabled: false`) when `crm_enabled` is false; when
  enabled, MTD revenue, outstanding receivables, MoM %, and baseline attainment (target/
  variance/attainment-pct) computed only when the org has configured
  `revenue_baseline_target_mtd`, else all three are `null`; a non-numeric baseline value
  is treated as absent rather than erroring.
- AC14: `insight_series` — six cumulative daily time series (operator actions, open
  action items, active batches started, batch completions, tasks due, revenue) each
  spanning from the current week's Monday (or the earliest open-action date, for that
  one series) through today; series are always present with sane empty-state points
  even with zero underlying data (`_dashboard_series_from_date_counts` degrades to a
  single zero point via `safeTrendSeries` on the frontend, not a missing key).
- AC15: cross-tenant — org B's summary must never include org A's data (tasks, events,
  executions, revenue). Confirmed for the endpoint as a whole by
  `test_org_b_dashboard_summary_excludes_org_a_data`
  (`tests/e2e/test_tenant_isolation.py`), which checks a single marker string is absent
  — GAP: no per-field isolation test (e.g. a dedicated check that org B's
  `operations.active_executions` count doesn't include org A's rows the way
  `test_dashboard_operations_summary_org_isolated` already proves for the underlying
  helper).

### `/api/core/metrics`
- AC16 (ASSUMPTION — reconstructed purely from code, zero existing test coverage at spec
  time; fixed during this review, see below): returns `total_processes`,
  `active_executions` (IN_PROGRESS only — note this differs from `/dashboard/summary`'s
  `active_executions`, which is PENDING+IN_PROGRESS; the two endpoints define "active"
  differently), `completed_executions`, and inventory item counts by type.
  ~~`operational_counters` (an explicitly per-worker-process counter snapshot)~~ — removed
  by this review (security-audit.md finding F1): it was a process-wide `dict` with no
  `org_id` key, leaking every tenant's internal failure-counter activity to every other
  tenant sharing the worker, and had no frontend consumer. `test_metrics_api.py` now
  asserts its absence as a regression guard.
- AC17 (ASSUMPTION): org-scoped like every other route in this slice, via the same
  `org_id = UUID(g.org_id)` pattern — never independently tested for cross-tenant
  leakage. GAP: zero tests reference `/api/core/metrics` at all (not in
  `test_dashboard_summary.py`, not in `test_multi_tenant_api.py`, not in
  `test_multi_tenant_isolation.py`, not in any e2e suite) despite being live,
  auth-gated, tenant-scoped production API.

## Data model
- tables: none of its own. Reads `Execution`, `EntityEvent`, `InventoryItem`, `Process`,
  plus `CoreChecksRunner`'s check outputs and (when `crm_enabled`) CRM tables via
  `CRMService`.
- changes: none proposed by this review.
- destructive: no.

## External surfaces
- None directly. Indirectly depends on the CRM→Xero integration's data being fresh
  (stale/failed Xero sync degrades `sales`/`tasks` silently, per AC5) — out of scope to
  re-verify Xero sync itself here.

## Out of scope
- `CoreChecksRunner` / individual check implementations — `compliance-checks` slice.
- `CRMService.get_overview` / `daily_sales_for_period` / task data correctness — `crm`
  slice.
- `core-active-batches-graph.js` — despite feature-index listing it under this slice's
  frontend, it is bound to `#core2...` elements and loaded via `base_spa.html` for the
  `/core` hub page (`core2.html`), not `/core/dashboard`; it never calls
  `/api/core/dashboard/summary`. Likely an index labeling drift, not fixed here (see
  `docs-truth`).
- `EntityEvent`/`_human_summary` correctness — `activity-log` slice (this slice only
  consumes it).

## Notes for the audit
- The two routes have **zero direct route-level tests**: `test_dashboard_summary.py`
  only unit-tests four pure helper functions (`_dashboard_summarize_tasks`,
  `_dashboard_build_compliance_summary`, `_dashboard_build_action_board`,
  `_dashboard_operations_summary`), never calls `get_dashboard_summary` or `get_metrics`
  as HTTP endpoints. The only route-level coverage is one e2e cross-tenant probe
  (AC15) and a page-renders-when-logged-in / doesn't-render-when-logged-out pair. Given
  six helper functions feed the endpoint response and are entirely untested at the
  integration level (`_dashboard_event_log_period`, `_dashboard_series_from_date_counts`,
  `_dashboard_event_counts_by_day`, `_dashboard_execution_counts_by_day`,
  `_dashboard_open_action_item_dates`, `_dashboard_operations_weekly_summary`), this is
  the slice's biggest coverage gap.
- AC4 (the dead `window_days` parameter) is worth a product/API-contract decision, not
  just a test — flag to the user rather than silently "fixing" it either direction.
- AC16/AC17 (`/api/core/metrics`) has no tests at all despite being a live, auth-gated,
  tenant-scoped API — highest-priority gap for `test-author` alongside the route-level
  gap above.
- Frontend (`dashboard.js`) already uses `textContent`/`escapeHtml` consistently for all
  dynamic values, including the one `innerHTML` sink (`renderSparkLine`, explicitly
  audited with a `nosemgrep` comment) — no obvious XSS surface on first read, but
  worth the security-audit stage confirming rather than taking the comment's word for it.
