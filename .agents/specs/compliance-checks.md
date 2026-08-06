# SPEC: compliance-checks
status: reviewed
name: Compliance / system findings checks (expired materials, untracked items, output expiry, output ready date)
slug: compliance-checks
blueprint: core_bp — `app/core/backend/corechecks.py` registers routes on `core_bp`;
  page route in `app/core/backend/backend.py`
url_prefix: /api/core, /core

## Description
A pluggable check registry (`CoreChecksRunner`) that runs a fixed set of built-in
compliance/data-quality checks over an org's inventory, executions, and process steps,
and exposes the results three ways: a per-check API for the sourcemap/inventory pages, an
aggregate API (`/api/core/system-findings`) that drives the system findings banner and
the notifications page, and a decoration helper (`get_system_findings_by_item`) that
attaches findings to individual rows in the `/api/core/inventory` list response.

Per `.agents/feature-index.md`, `CoreChecksRunner._register_builtin_checks` /
`register_check` is the seam the unbuilt COMPLIANT tier plugs industry-specific checks
into — the check interface (`(org_id, session) -> CheckResult`) is a public contract, not
an implementation detail of the four built-in checks.

Four built-in checks:
1. **expired_materials** (`checks/expired_materials.py`) — raw materials with
   `expiry_date < today` and `quantity > 0`, plus downstream products made from them (via
   `dagtraversal.find_impacted_by_expired_raw`). Recall-relevant: intentionally
   unpaginated (`# nosemgrep: sqlalchemy-all-without-limit`).
2. **untracked_items** (`checks/untracked_items.py`) — inventory items with
   `extra_data.untracked == True` still needing reconciliation (qty > 0 OR
   `remaining_balance_to_reconcile > 0`), enriched with the process/step that produced
   them so the UI can offer a one-click "go execute this step" reconcile action.
3. **output_expiry** (`checks/output_expiry_check.py`) — outputs of completed execution
   steps whose `step.outputs[].extra_data.custom_expiry` config has expired or is nearing
   expiry (fixed-duration from completion, or an operator-set actual date/duration).
4. **output_ready_date** (`checks/output_ready_date_check.py`) — outputs not yet usable
   under a `ready_date` config (fixed-duration or operator-set), red before the "warn"
   window and amber inside it. Also exposes `is_inventory_item_ready_for_consumption`
   (execution-time consumption guard) and `get_operator_ready_instant_for_item`, used by
   `complete_step` elsewhere in `core_bp` — outside this check's own route surface but
   sharing its domain rules.

`system_status.py` derives a single `system_status` object (onboarding "activation" mode
vs. "health" mode with a healthy/degraded/critical state) from the check results, reused
identically by `/api/core/system-findings` and the dashboard's compliance summary
(`/api/core/dashboard/summary`, in `backend.py`) so the two surfaces cannot drift.

Duration/date math and the two locked invariants (warning ≤ expiry period; warning ≤
ready period; ready_date ≤ expiry_date when both are set) live in
`app/core/domain/{expiry_rules,ready_date_rules,expiry_ready_date_rules}.py` — the single
source of truth shared with execution-time validators elsewhere in `core_bp`.

## Users & permissions
- roles: any authenticated user of the org. No `@requires_role` gate on any route in this
  surface.
- tenant_scoped: yes. Every route resolves `org_id = UUID(g.org_id)` (populated by
  session-derived tenant-context middleware — never a client-supplied header or param)
  and passes it into `CoreChecksRunner` / the check functions, all of which filter every
  query by `org_id` (directly, or via an org-scoped repository / an `Execution.org_id`
  join for execution-step-derived data).
- `/core/notifications` (the page route) carries `@requires_auth` only; it renders a
  shell and fetches data client-side from the API routes above, which carry the same
  auth.

## Acceptance criteria

### Checks and registry
- AC1: `CoreChecksRunner._register_builtin_checks` registers exactly `expired_materials`,
  `untracked_items`, `output_expiry`, and `output_ready_date` (the last under
  `output_ready_date_check.CHECK_ID`, not a hardcoded string) — the seam the COMPLIANT
  tier plugs into.
- AC2: `run_check(check_id)` returns `None` for an unregistered id (and logs a warning),
  never raises.
- AC3: `run_all_checks()` never lets one check's exception abort the others — a raising
  check is caught, logged, and turned into a flagged `CheckResult` carrying the error
  message, so one broken check can't blank out every other finding.
- AC4: Every check's `CheckResult.data` is scoped to `org_id` only — no check may return
  rows, ids, or names belonging to another org, whether reached via a direct query, a
  repository call, or an execution/process join.

### expired_materials
- AC5: A raw material with `expiry_date < today` and `quantity > 0` is included in
  `expired_raw_materials`; the same raw material with `quantity == 0` is excluded and
  does not flag the check.
- AC6: `impacted_items` lists products produced by executions that consumed a flagged
  expired raw material (via DAG traversal), and `connections` is deduplicated by
  `(from_id, to_id, execution_id)`.
- AC7: An invalid (non-numeric) stored `quantity` on a candidate raw material raises
  `ValueError` rather than silently skipping or miscounting it.

### untracked_items
- AC8: An item is included when `extra_data.untracked == True` AND (`quantity > 0` OR
  `extra_data.remaining_balance_to_reconcile > 0`) — the same criteria the execution
  modal's "matching untracked" dropdown uses, so the two surfaces never disagree on what
  counts as untracked.
- AC9: Each result item carries `process_id`/`process_name`/`step_name` resolved from its
  `source_execution_step_id` (falling back to `source_execution_id` when the step was
  deleted) and `producing_step_id`/`producing_step_name` — the step whose *output*
  definition matches the item's name+unit, used for the "execute this step to reconcile"
  action, distinct from the step that merely *created* the untracked row.
- AC10: If the primary repository lookup (`InventoryRepository.get_untracked_items`)
  raises, a direct-query fallback still returns a correct (if less efficient) result
  rather than surfacing 500 or silently returning nothing — this is compliance data, not
  a hot path that's safe to degrade to empty.

### output_expiry
- AC11: An output is flagged `red` once `now > expiry_at` and `amber` once
  `now >= expiry_at - warning_duration`, honoring both `fixed_duration` (from step
  completion) and `set_at_execution` (operator-entered actual date/duration) modes.
- AC12: An item already fully expired outside the near-expiry window, or with `qty <= 0`,
  is excluded. Each `(execution_step, item)` pair is only ever emitted once
  (`seen_item_ids`), and the result is capped at `MAX_EXPIRY_ITEMS` (500).
- AC13: An out-of-range or unrecognized `duration_unit`/`warning_unit` falls back to
  `"days"` rather than raising or silently dropping the finding.

### output_ready_date
- AC14: `now < ready_dt` is "not ready" (red before the warn window, amber inside it);
  `now >= ready_dt` is ready and the item is excluded entirely — the boundary is
  documented as locked in `ready_date_rules.py` and must not change without explicit
  change control.
- AC15: The DB-level `jsonb_path_exists` filter (finding execution_step ids whose step
  has `ready_date.enabled == true` before loading anything else) must select the same
  candidate set a full Python scan of the org's steps would — this is a performance
  optimization, not a semantic filter, and any check must prove the two agree.
- AC16: `is_inventory_item_ready_for_consumption` returns `(False, message)` for an item
  not yet ready under either `ready_date_actual` (set_at_execution) or step-derived
  fixed-duration config, and `(True, None)` for every other case (no config, no source
  step, already ready) — used elsewhere as the execution-time consumption guard.

### Aggregate API and dashboard/list decoration
- AC17: `GET /api/core/system-findings` returns `{findings: [...], system_status: {...}}`
  where `findings` includes exactly the flagged checks with a non-null `message`, and
  `system_status` is `build_system_status_payload`'s output — `mode: "activation"` with
  onboarding steps while inventory/process/execution are incomplete, else
  `mode: "health"` with a `state` of `healthy`/`degraded`/`critical` derived from signals.
- AC18: `derive_health_state` is `critical` iff any signal has both `has_issue` and
  `in_active_use` true (an expired input that reached production, or untracked stock
  in hand); `degraded` if any `has_issue` signal exists without `in_active_use`; else
  `healthy`.
- AC19: `get_system_findings_by_item` returns a map keyed by inventory item id to a list
  of `{check_id, reason}`, used to decorate `GET /api/core/inventory` rows (red border +
  reasons) — adding a new built-in check requires an extractor in this function, not a
  change to `list_inventory`.
- AC20: `/api/core/dashboard/summary`'s compliance section is built from the same
  `CoreChecksRunner.run_all_checks()` results and `build_system_status_payload` call as
  `/api/core/system-findings` — the two surfaces cannot show different compliance state
  for the same org at the same instant.

### Page and auth
- AC21: `GET /core/notifications` requires auth and renders the SPA shell only; all
  finding data is fetched client-side.
- AC22: All five routes (`/core/notifications`, `/api/core/system-findings`,
  `/api/core/inventory/{expired-materials,untracked-items,output-expiry,output-ready-date}`)
  return 401 for an unauthenticated request, before touching any org data.

### Frontend
- AC23: The banner and notifications-page renderers (`system-findings-banner.js`,
  `system-findings-notifications.js`) never insert a server-supplied string (item name,
  process name, step name, notes, message) into the DOM without passing it through
  `escapeHtml` first, whether via `innerHTML` string-building or `textContent`.
- AC24: Snooze/hide state ("ignore for today", "dismiss") is per-check-id-and-item-key in
  `sessionStorage`, keyed off data returned by the API — never persisted server-side, so
  it does not survive a session and does not affect what another user of the same org
  sees.

## Non-goals / explicitly out of scope
- Writing/mutating compliance data: every check here is read-only over data owned by
  other slices (inventory, execution, wastage); disposal/reconciliation actions the UI
  offers (dispose of expired stock, reconcile untracked item) are handled by inventory's
  and reconciliation's own routes, not this slice.
- The COMPLIANT-tier checks themselves — this spec covers the registry contract they will
  plug into, not any check that doesn't exist yet.
