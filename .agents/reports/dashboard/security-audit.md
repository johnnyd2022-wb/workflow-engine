# SECURITY: dashboard
date: 2026-08-12
verdict: findings-open
invoked_as: chain stage (read-only grader) — report only, no patches applied
scanned: semgrep(0 findings, 2 non-blocking errors), gitleaks(0), uv-audit(0)
manual_checklist: 7/7 completed

## Scope
`app/core/backend/backend.py:4183-4912` (`_dashboard_*` helpers, `get_dashboard_summary`,
`get_metrics`), `app/core/frontend/dashboard/dashboard.html`, `app/core/frontend/js/dashboard.js`,
`app/core/frontend/js/core-api.js` (client of both endpoints), `app/core/utils/internal_counters.py`
(dependency of `get_metrics`), plus the three repositories `get_metrics` calls into
(`process_repo.py`, `execution_repo.py`, `inventory_repo.py`).

## Scanner pass
- **semgrep** (`p/python p/flask p/owasp-top-ten .semgrep/`): 0 findings across 5 targeted files
  (251 rules run). 2 non-blocking errors, both benign and logged for completeness:
  - a rule timeout (`dangerous-system-call-tainted-env-args`) against the full `backend.py` —
    unrelated to the dashboard slice, the file is just large; not scoped to lines 4183-4912.
  - a "syntax error" on `dashboard.html` — semgrep's generic HTML parser chokes on Jinja
    (`{% extends %}` etc.), not a real parse failure. Template was reviewed manually instead
    (see below); no `| safe`/`Markup()`, no server-side variable interpolation of any kind —
    it's a static shell hydrated entirely client-side.
- **gitleaks**: 0 leaks, 1050 commits scanned (repo-wide, as designed).
- **uv audit**: 0 vulnerabilities, 84 packages audited.

## Findings

- F1 [fix] `app/core/backend/backend.py:4907` (`GET /api/core/metrics`) — cross-tenant leak
  of process-wide operational counters.
  evidence: `get_counter_snapshot()` (`app/core/utils/internal_counters.py:18-20`) returns
  `dict(_counts)` from a single module-level `dict` shared by the whole worker process —
  there is no `org_id` key anywhere in it. `backend.py:4864-4912` (`get_metrics`) is
  `@requires_auth`-only, org-scoped for every other field via the three repositories
  (`process_repo.list_processes(org_id)`, `execution_repo.list_executions(org_id, ...)`,
  `inventory_repo.list_inventory_items(org_id)` — all verified to filter by `org_id`, see
  "Attempted but clean" below), but this one field bypasses that entirely: any authenticated
  user of *any* org gets the same process-wide counter snapshot as every other org sharing
  that worker. The response's own `note` field ("Counts are per web worker process; use an
  external sink to aggregate in multi-worker deployments") documents the *multi-worker*
  caveat but not the *cross-tenant* one — a caller has no way to know these numbers include
  other tenants' activity.
  severity: **low**. The only counter keys currently incremented
  (`grep -rn "inc_counter(" app/`) are internal failure/anomaly signals —
  `ready_date_parse_failures`, `execution_data_node_budget_exceeded`,
  `execution_data_strip_invariant_violations`, `inventory_hydration_failures`,
  `inventory_producing_step_failures`, `inventory_producing_step_name_fallback_failures`,
  `ready_date_compute_failures` — not PII, not business/revenue data, not row-level records.
  What leaks is a coarse signal of how often *other tenants'* requests are hitting internal
  error paths, which is still a tenant-isolation violation on a tenant-scoped API and
  contradicts the slice's own stated assumption (AC17: "org-scoped like every other route
  in this slice") — it just isn't a high-value target for an attacker today. Confirmed via
  `finding_history.py decide` this is a new, undecided finding (sig `c06d323edec4`), not a
  previously accepted risk.
  rule_added: none — pattern (module-level mutable dict serialized straight into an
  org-scoped JSON response with no org key) is narrow enough that a generic semgrep rule
  would either miss it or false-positive heavily on legitimate process-wide config/health
  fields; flagging for human judgment on the fix shape below instead of automating detection.
  recommended route (not taken here — read-only stage): tenant-isolation findings route to
  **fix-bug** per the security-audit skill's table, red-then-green (assert org B's
  `/api/core/metrics` counters don't move when only org A's requests trip a counter, then
  fix). Two shapes worth considering, a call for whoever picks this up rather than dictated
  here: (a) key counters by `org_id` and only return the caller's own bucket, or (b) if these
  are genuinely meant as ops/SRE signals rather than tenant-facing data, drop the `counts`
  field from this response entirely and expose it only via an internal/ops-only surface.

## Attempted but clean

- **`window_days` dead parameter (AC4)**: confirmed non-exploitable despite being dead API
  surface. `get_dashboard_summary` (`backend.py:4671-4677`) parses it with `int(window_days_raw)`
  inside a `try`/`except ValueError`, then bounds-checks to `[7, 180]` — and the parsed value
  is never threaded into any query (grepped every use of the `window_days` name in the
  function body; only appears in the parse/validate block and the echoed response field).
  No injection path (no string formatting, no raw SQL, no loop keyed off the value). Checked
  the one other thing worth checking on unbounded `int()` parsing of a request-args string —
  CVE-2020-10735-style quadratic-blowup DoS from a huge digit string — and it's moot here:
  this app requires Python ≥3.14 (`pyproject.toml`), which ships `sys.int_info.default_max_str_digits
  = 4300`, so an absurdly long digit string just raises `ValueError` (caught, 400) rather than
  burning CPU. Client (`core-api.js:333-336`) also coerces with `Number(windowDays) || 30`
  before it ever reaches the wire, though that's not load-bearing for the server-side check.
  Recommend the underlying product question (wire it up vs. remove it) go through a
  spec/product decision, per the spec's own note — not a security action.

- **Tenant isolation on every DB query in the audited helpers**: read all 15
  `_dashboard_*` helper functions (`backend.py:4183-4665`) plus both route bodies. Every
  query against `Execution`, `EntityEvent`, `InventoryItem` filters by `org_id ==
  UUID(g.org_id)` (or receives an already-filtered list from a repo that does). `g.org_id`
  is set exclusively by `tenant_context.py`'s `before_request` hook from the session's
  `user_id` → `user.org_id` → org lookup (never from a client-controlled header — the
  module docstring is explicit: "Only use authenticated user_id from session (no X-Org-Id
  header)"), and aborts 403 before any route body runs if the user/org can't be resolved.
  On top of the per-query filters, `app/core/db/tenant_filter.py` adds a global
  `do_orm_execute` + `with_loader_criteria` filter that scopes *every* ORM SELECT/UPDATE/
  DELETE against a `TenantScoped` model to the active `org_id` regardless of whether the
  call site remembered its own `.filter(org_id=...)` — defense-in-depth on top of what's
  already correct here, not compensating for a gap in this slice.
  `/api/core/metrics`'s three repository calls
  (`process_repo.list_processes`, `execution_repo.list_executions`,
  `inventory_repo.list_inventory_items`) were individually read and all filter by `org_id`
  correctly (`process_repo.py:127-129`, `execution_repo.py:178-190`,
  `inventory_repo.py:408-424`) — this closes the spec's AC17 gap (zero existing tests) as
  far as static verification can: the code is correct, it's just untested. Recommend
  `test-author` add the route-level org-isolation test the spec calls out (a dedicated
  `two_org_two_user`-fixture test for `/api/core/metrics`, mirroring
  `test_org_b_dashboard_summary_excludes_org_a_data` for `/api/core/dashboard/summary`) —
  that's a coverage gap, not a live vulnerability, given F1 aside.

- **`dashboard.js`'s one `innerHTML` sink (`renderSparkLine`, line 200)**: the `nosemgrep`
  comment's claim was verified rather than trusted, per the task's instruction. Traced every
  value that flows into the concatenated string:
  - `built.path` / `circles` (SVG `<path d="...">` and `<circle cx cy>`): built by
    `buildLinePath` (line 156) purely from `Number(pt.value || 0)` coerced through
    arithmetic and `.toFixed(2)` — cannot contain markup characters under any input,
    including `NaN`/`Infinity` edge cases (`.toFixed` on those still yields a plain string).
  - `safeSeries.start_label` / `end_label`: passed through `escapeHtml()` (line 51-58,
    a standard `&<>"'` entity-encode) before concatenation.
  - The series objects themselves come from `_dashboard_series_from_date_counts`
    (`backend.py:4418-4455`), which only ever emits `date.isoformat()` strings and ints —
    no user-controlled text reaches this path at all (labels are server-computed month/day
    abbreviations, not echoed from any request or DB text field).
  Confirmed clean: the `nosemgrep` justification is accurate, not just asserted.

- **CSRF**: both routes are GET-only, read no state-changing input beyond the bounds-checked
  `window_days` int — no CSRF exposure to assess.
- **Mass assignment / SSRF / uploads / secrets-in-code**: not applicable — this slice takes
  no JSON body, no URLs, no file uploads, and scanners found no embedded secrets.
- **Auth on every route**: `dashboard()` (`backend.py:642-645`), `get_dashboard_summary()`
  (`backend.py:4667-4669`), `get_metrics()` (`backend.py:4864-4866`) all carry `@requires_auth`.
  No bare routes in the audited slice.

## Not verified
- CRM-path fields (`sales`, `tasks` when `crm_enabled`) — `CRMService.get_overview`/
  `daily_sales_for_period`/`get_traceability_config` internals are explicitly out of scope
  per the spec ("out of this slice's scope to re-verify") and were not re-audited here.
- No live app server was running (preflight: `live_server_tests: skip`), so this audit is
  entirely static/code-read verification, not an HTTP-level probe. The one existing
  route-level cross-tenant test (`test_org_b_dashboard_summary_excludes_org_a_data`) was read
  but not re-run.
