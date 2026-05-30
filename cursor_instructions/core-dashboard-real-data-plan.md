# Core Dashboard Real-Data Plan

## Objective

Redo `/core/dashboard` as an operations + sales + compliance command center using real tenant data from `/core` and `/crm`.

## Review Summary (`/core` + `/crm`)

1. `/core/dashboard` is currently static placeholder UI.
- `app/core/frontend/dashboard/dashboard.html` hardcodes compliance %, active workflows, alerts, and compliance bars.
- No backend API call is made to populate these values.

2. `/core` has useful building blocks but no unified dashboard aggregation.
- Existing APIs: `/api/core/metrics`, `/api/core/system-findings`, `/api/core/executions`, `/api/core/inventory/*`, `/api/core/inventory/wastage`.
- Gap: no single endpoint designed for dashboard-level, cross-domain summaries.

3. `/crm` already has strong sales/task aggregates.
- Existing API: `/api/crm/overview` includes MTD revenue, outstanding receivables, monthly trend, open tasks, task status totals.
- Existing API: `/api/crm/tasks` supports task-level reads; model includes `due_date`, `priority`, assignee.

4. Missing bridge between operations and sales.
- Product mappings + Xero line items exist, but `/core/dashboard` does not currently expose any “sales impact vs operational risk” view.

## Target Dashboard Layout

Three rows, each row tied to a business decision:

1. **Today’s Work** (operator focus)
2. **Compliance & Traceability Health** (risk focus)
3. **Operations ↔ Sales Performance** (management focus)

## Widget Plan (Real Data)

### 1) Tasks Due Today (Requested)
- **Why:** Immediate action queue.
- **Metric:** count of CRM tasks where `due_date == today` and `status in (pending, in_progress)`.
- **Secondary:** overdue count (`due_date < today`, still open), top 5 tasks list.
- **Source:** `crm_tasks` via CRM service/repo (or `/api/crm/tasks` if reused).
- **Action links:** `/crm/tasks`, deep-link to task.

### 2) Compliance Score (Requested)
- **Why:** Single risk signal for leadership.
- **Source checks:** `/api/core/system-findings` (expired materials, untracked items, output expiry, ready-date).
- **Scoring proposal (v1 deterministic):**
- Start at 100.
- Deduct weighted points per active finding bucket:
- `expired_materials`: -25 base, plus -2 per impacted item (cap bucket at -40).
- `untracked_items`: -3 per item needing reconciliation (cap -25).
- `output_expiry`: -4 per red + -1 per amber (cap -20).
- `output_ready_date`: -2 per red + -1 per amber (cap -15).
- Clamp to `[0, 100]`.
- **Display:** score + trend vs 7-day trailing average + “top contributors to score drop”.

### 3) Compliance Findings Breakdown
- **Why:** Explain the score and drive remediation.
- **Metric:** counts by finding type/severity; “in active use” risk flag from `system_status.signals`.
- **Source:** `/api/core/system-findings`.
- **Action links:** sourcemap, reconcile flow, dispose flow.

### 4) Active Batches & Throughput
- **Why:** Operational load + flow.
- **Metric:** active executions, completed today, failed/cancelled today.
- **Source:** executions table (`ExecutionStatus`, `started_at`, `completed_at`), preferably via new aggregate query.
- **Action links:** `/core/processes`, specific execution.

### 5) Inventory Risk Snapshot
- **Why:** Prevent stock/compliance surprises.
- **Metric tiles:**
- Expired raw materials with stock.
- Untracked inventory requiring reconciliation.
- Near-expiry outputs.
- Not-ready outputs.
- **Source:** existing core checks output from `/api/core/system-findings`.

### 6) Sales Pulse (MTD)
- **Why:** Revenue context on same page as operations.
- **Metric:** current month revenue, outstanding receivables, MoM %.
- **Source:** `/api/crm/overview`.
- **Action links:** `/crm`, invoices modal/list.

### 7) Operations vs Sales Alignment
- **Why:** Connect production and commercial execution.
- **Metric (v1):**
- top sold products (CRM) with mapping status (mapped/stale/unmapped).
- “At-risk revenue”: revenue tied to products whose mapped outputs currently have critical findings.
- **Source:** `top_products` from CRM overview + `product_mappings` + core findings by mapped output/item.

### 8) Wastage Trend (7/30 day)
- **Why:** Cost + process quality signal.
- **Metric:** wastage quantity/records over trailing windows, grouped by reason.
- **Source:** `inventory_wastage` (`/api/core/inventory/wastage` or direct aggregate query).

### 9) Recent Critical Events
- **Why:** Fast situational awareness.
- **Metric:** latest high-signal events (wastage recorded, execution failed, compliance-critical findings).
- **Source:** `entity_events` and system findings snapshot.

## API Strategy

Implement a dedicated aggregate endpoint for dashboard performance and consistency:

- `GET /api/core/dashboard/summary?window_days=30`

Response groups:
- `tasks`
- `compliance`
- `operations`
- `inventory_risk`
- `sales`
- `ops_sales_alignment`
- `wastage`
- `events`

Notes:
- Keep tenant scoping by `org_id`.
- Prefer server-side aggregates over client-side fan-out to many endpoints.
- Cache briefly per org (e.g. 30-60s) if needed.

## Delivery Phases

### Phase 1 (ship quickly)
- Replace placeholder cards with real data widgets:
- Tasks Due Today
- Compliance Score + Findings Breakdown
- Active Batches/Throughput
- Sales Pulse (MTD)
- Implement `/api/core/dashboard/summary` with minimal fields.

### Phase 2 (bridge ops + sales)
- Add Operations vs Sales Alignment widget.
- Add Wastage Trend.
- Add recent critical events feed.

### Phase 3 (refinement)
- Trend spark lines (7d/30d).
- Drilldown interactions and deep links.
- Score calibration based on real incident history.

## Implementation Notes

1. Keep `/core/dashboard` as server-rendered shell; hydrate widget data with one JSON request.
2. Reuse existing check logic (`CoreChecksRunner`) to avoid rule duplication.
3. Keep compliance score formula explicit and versioned (`score_version: "v1"`).
4. Add unit tests for:
- score calculation,
- task due/overdue bucketing,
- aggregate endpoint org isolation.

## First Build Slice (recommended)

1. Add backend endpoint `GET /api/core/dashboard/summary`.
2. Add frontend `dashboard.js` and bind to `dashboard.html`.
3. Implement widgets in this order:
- tasks due today,
- compliance score,
- findings breakdown,
- active batches,
- MTD revenue + outstanding.
4. Remove all placeholder text/numbers from current dashboard template.
