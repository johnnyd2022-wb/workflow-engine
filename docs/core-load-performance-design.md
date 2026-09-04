# `/core` performance, reliability, and security review

**Reviewed:** 2026-08-27
**Baseline:** merge request !181, merged as `40cc276` (`perf/core-tab-load-time`)

## Decision record

The next `/core` performance change should be a purpose-built, tenant-scoped overview
read model, followed by on-demand, paginated detail panels. Do not solve this with a broad
browser cache or by increasing Gunicorn workers alone. The current page loads full
inventory and full execution history while the user is looking at Overview; its response
size and Python/JSON work therefore grow with a customer's history.

The overview endpoint must be scoped by `org_id`, protected with `@requires_auth`, and
return only above-the-fold fields. It must never be shared between organisations. The
Inventory and Workflows tabs should fetch only after a user opens them, and list endpoints
should use cursor pagination with a server-enforced maximum page size.

## What !181 improves

!181 makes sound targeted improvements:

- production/test images now use Gunicorn with two gthread workers instead of Flask's
  development server;
- `/api/core/metrics` counts executions and inventory in SQL rather than materialising
  every row;
- one `DAGTracer` instance reuses its graph during the expired-materials check;
- the legacy `core.js` include was removed; and
- concurrent identical, unabortable GETs share an in-flight promise in `CoreAPI`.

The review found no new tenant-boundary or CSRF regression in those changes. The
request-scoped DAG cache is safe because the tracer has one `org_id` and one SQLAlchemy
session. The promise sharing only joins an in-progress browser request; it does not retain
data after the request settles.

## Confirmed remaining load problem

`/core` launches these requests when it becomes ready:

```text
/api/core/metrics
/api/core/processes
/api/core/inventory
/api/core/executions
```

See `loadCoreHubDashboardData` in `app/core/frontend/core/core2.html`. The inventory
request runs all compliance checks before enriching every item (`list_inventory`), while
the executions endpoint returns every execution step, its JSON inputs/outputs, evidence,
and event summary (`list_executions`). None of that is bounded by the overview UI.

There is also a duplicate heavyweight process request. The active-batches graph separately
calls `/api/core/processes?include_steps=true` shortly after the hub asks for
`/api/core/processes` (`app/core/frontend/js/core-active-batches-graph.js:751`). Different
URLs cannot be combined by !181's in-flight dedupe. The executions request is shared only
when the earlier request has not yet settled; otherwise it is fetched again. This explains
why a small organisation can still see multi-second load time after !181.

## Target request shape

Initial navigation should have a deliberately small critical path:

```text
GET /core                         -> HTML shell and static assets
GET /auth/me                      -> existing account chrome
GET /api/core/hub/overview        -> one org-scoped overview payload
```

`/api/core/hub/overview` should contain SQL counts, compact summary cards, and at most the
20 most recently updated active batches with only the process/step metadata needed by the
pipeline. It must not call `list_inventory`, `list_executions`, or `list_processes` and
trim their Python objects. Make aggregates/selects explicit and include `org_id` in every
query.

On an Inventory or Workflows tab click, fetch the relevant data then. Use opaque cursor
pagination (for example, `limit` clamped to 50) and a compact default representation;
fetch full evidence or an item story only after the user opens that record. Feed the
active-batches graph from the overview result, or publish the first hub result to it,
rather than issuing a second `include_steps=true` call.

Run `EXPLAIN (ANALYZE, BUFFERS)` against production-like anonymised volume before adding
indexes. Likely candidates, if the plans need them, are:

- `executions (org_id, status, created_at DESC)`;
- `inventory_items (org_id, created_at DESC)`; and
- `processes (org_id, created_at DESC)`.

The existing single-column `org_id` indexes are not substitutes for these sort/filter
patterns at commercial volume.

## Caching and capacity

The current in-flight GET dedupe is a concurrency guard, not a cache. If a short server
cache is justified after measurement, key it at minimum by `(org_id, response version,
relevant filters)` and advance that version on every inventory, process, and execution
mutation. Do not key only by URL or use `public` caching for authenticated JSON. A 15–30
second per-org overview cache is reasonable only with explicit invalidation and a visible
`generated_at` value.

Gunicorn's `2 workers x 4 threads` is a conservative starting point, not a capacity
result. Capacity testing must measure database connections, p95/p99 latency, worker
restarts, and queue time under representative organisations before increasing it. Keep
`preload_app = False` unless a safe post-fork engine disposal hook is introduced.

The app should fail deployment if its TLS certificate/key is missing. The Gunicorn config
currently falls back to HTTP, while application middleware redirects normal requests to
HTTPS and cookies are Secure; that is an availability failure, not a safe fallback.

## Security findings requiring owner action

These findings are outside !181's functional changes but matter before commercial
deployment:

1. `app/config/prod.ini` was tracked with a database password. **Application-side: done** —
   the tracked value is removed and production now fails fast at startup unless
   `POSTGRES_PASSWORD` is supplied from the deployment environment
   (`app/utils/config_loader.py`, `tests/test_config_production_secrets.py`).
   **Still owed, and needs the credential owner + deployment access:** rotate the
   superseded credential and remove its value from Git history using the team's incident
   procedure.
2. `app/tls/app_cert.key` is tracked. Treat it as compromised: replace the certificate/key
   pair, remove the private key from version control/history, and generate development/test
   certificates at setup or image-build time. Production TLS belongs in the deployment
   secret manager or TLS terminator.
3. The CSP permits both `'unsafe-inline'` and `'unsafe-eval'`. This predates !181 but
   weakens XSS containment. Move large inline `/core` scripts into versioned static modules,
   then use nonces/hashes before tightening the policy.

Credential/certificate rotation needs the credential owner and deployment access; do not
attempt it from an engineering worktree. Pair the code change with verification of HTTPS,
HSTS, Secure/HttpOnly cookies, and reverse-proxy headers.

## Acceptance and regression guardrails

Add a seeded production-shaped performance fixture and assert:

- initial `/core` has one overview JSON request and no full inventory/history request;
- inactive tab data is absent until its tab opens;
- initial overview has response-size, query-count, and backend-time budgets;
- overview/list responses remain org-isolated; and
- a mutation invalidates the next overview read for that org only.

Keep `tests/e2e/test_perf_budgets.py`, but add a network-waterfall test: backend median
cannot detect duplicate browser requests or oversized JSON. Record p50/p95 LCP, API
duration, response bytes, query count, and dataset size in `.agents/reports/perf/`.

## Review validation performed

- compared !181's local source branch with its parent and the merged commit;
- inspected the `/core` frontend loaders, API payload construction, tenant filter,
  Gunicorn configuration, and relevant indexes;
- ran `git diff --check` for !181;
- ran `node --check` for modified `core-api.js` and the active-batches graph; and
- ran `node --test tests/js/*.test.js`: 5 passed.

Browser and Python integration/performance tests were blocked in this sandbox: PostgreSQL
on port 8401 was unavailable, Docker socket access was denied, and the isolated Python
environment could not download a missing dependency. `glab` was also blocked because its
Snap confinement cannot start here; the local merged commit and
`origin/perf/core-tab-load-time` branch were used to review !181.

---

## As-built (2026-08-27, branch `mc/agent-20260827-085133-21407d`)

The design above was implemented in five commits on this branch.

### What shipped

1. **`GET /api/core/hub/overview`** (`backend.py:get_hub_overview`) — one org-scoped,
   `@requires_auth` payload: the `/api/core/metrics` numbers, inventory aggregates
   (non-zero lines, allocated, linked, expiry buckets, ≤6 traceability-gap rows, 24h
   movement totals), `journey` booleans, ≤20 most-recently-updated active-execution
   summaries, and per-process 7-day throughput. Every number is a SQL aggregate; nothing
   in the payload scales with an org's history. New repo helpers:
   `ExecutionRepository.list_active_execution_summaries` / `count_completed_by_process_since`,
   `InventoryRepository.hub_overview_aggregates` / `list_traceability_gap_items` /
   `movement_totals_since`, `ProcessRepository.list_process_names` / `count_processes`.
2. **Frontend first paint** (`core2.html`) split into `loadCore2Overview()` (the one call
   above) + `loadCore2InventoryTab()` / `loadCore2WorkflowsTab()`, which fire only when
   their tab is first shown (or on paint if the restored `?tab=` is that tab).
3. **Active-batches graph** (`core-active-batches-graph.js`) consumes the published
   `window.__core2HubOverview` (event `core2:hub-overview`) instead of its own
   `getProcesses(true)` + `getExecutions()`; it lazily fetches only the *selected*
   process's steps via `getProcess(id)`. A pre-hub fallback fetch (no `include_steps`)
   remains for standalone HTMX swaps.
4. **Opt-in keyset pagination** on `/api/core/executions` and `/api/core/inventory`:
   `?limit` (clamped to 50) + opaque `?cursor` (`base64url("<created_at_iso>|<id>")`,
   sort `created_at DESC, id DESC`). **No `?limit` ⇒ byte-for-byte the old full list** —
   none of the ~20 existing callers change. Paginated responses add `has_more` /
   `next_cursor`; a bad limit/cursor is a 400.
5. **Migration `core_hub_perf_indexes_001`** — composite indexes
   `executions(org_id, created_at DESC, id DESC)`,
   `executions(org_id, status, updated_at DESC)`,
   `inventory_items(org_id, created_at DESC, id DESC)`,
   `processes(org_id, created_at DESC)`. Index-only, reversible.

### Measured

Direct repo-call timing of the overview against the real `whistlebird_test` org
(252 executions, 243 inventory items), cold: **9 DB queries, ~73 ms wall**. Flat in query
count regardless of history — contrast `/api/core/system-findings` on the same org
(~100 queries per the `budgets.json` note). `EXPLAIN` on `whistlebird_test` confirms the
keyset list queries do an index-ordered scan with **no Sort node** after the migration.
`tests/e2e/test_core_load_waterfall.py` (real browser) confirms initial `/core` makes
exactly one `hub/overview` call and no `inventory` / `executions` /
`processes?include_steps=true`, and that tab data loads once, on open.

### Adversarial review (herdr Breaker = codex, 2 rounds)

Round 1 found 5 issues, all fixed in `8bc43fa`: a 60 ms timer race that let the
active-batches graph restore the old processes+executions fan-out when the overview was
slow (F1); a double serial `/api/core/system-findings` run on populated orgs (F2); 7-day
throughput merged across processes sharing a name (F3); unbounded `processes_min` (F4);
and a post-step-completion path (`loadInventoryV2`) that reintroduced the old triple
fetch and left the overview stale (F5). Round 2 found 4 follow-ups, fixed in the next
commit: the `processes_min` cap could hide an active batch's own process from the picker
(now the active-execution processes are always included first); `loadInventoryV2` still
force-fetched the full inventory on every mutation even from Overview (now only when the
Inventory tab is open/loaded); a failed *refresh* left stale `__core2HubOverview` for the
graph (now cleared at refresh start); and redundant `getMetrics()` calls after inventory
edit/delete/reconcile (removed — `loadCore2Overview()` already refreshes metrics).

### Deliberately deferred (call-outs for the MR reviewer)

- **`low_stock` is hard-coded 0** in the overview. There is no per-item reorder threshold
  in the schema, and the frontend's ratio check was already inert (it needs an
  `initial_quantity` the API has never sent). Wired as a named field so a real
  implementation has a home; not implemented here.
- **Hub Inventory/Workflows tabs still fetch their full lists** (only on first open, and
  post-mutation only if already open). Converting their grouped/category rendering to
  consume paginated pages is a UX change, not a perf tweak — left as a follow-up. The
  pagination *endpoint capability* is in place and tested.
- **`processes_min` is bounded at `HUB_PROCESSES_MIN_CAP`** — every distinct process
  behind the ≤20 active executions is included first (so the picker can never hide a live
  batch), then newest processes fill the remainder up to the cap.
- **`throughput_7d` is restricted to the `processes_min` set** — its only consumer is the
  active-batches graph's per-process 7-day count, which can only address a process that is
  in the picker. `completed_7d` (the scalar the Workflows card shows) is still summed over
  every process. This keeps the payload bounded on an org with a large recent
  recipe/SKU catalogue.
- **Paginated `/api/core/inventory` page sizes are not uniform**: the route drops
  zero-quantity rows *after* the DB page is fetched, so a page can return fewer than
  `limit` display rows while `has_more` is true. `next_cursor` correctly points at the
  last *fetched* row so the scan continues correctly. Acceptable for the opt-in v1.
- **Index necessity is unproven at scale.** Local/CI data is tiny; the reversibility
  check proves the indexes build/drop cleanly and `EXPLAIN` shows they're *used*, not
  that the planner *needs* them yet. Recalibrate with production-shaped volume.
- **`budgets.json` override for `/api/core/hub/overview` — calibrated** (2026-09-03,
  findings-sweep): three runs on the empty-org E2E fixture per the perf-guardrails
  SKILL.md procedure measured queries 11/11/11 and backend_ms run medians 11.9–13.0.
  The override now pins `queries.budget` at the observed 11 as a ratchet and sets
  `backend_ms.budget` to 60 (~4x worst median, matched to the sibling
  `/api/core/system-findings` override); the tight `queries.ceiling` of 25 is
  unchanged. No longer a stub.
- **Security findings in "requiring owner action" above:** the `prod.ini` application-side
  clause is now handled (see that section). Credential rotation + Git-history purge, and
  the tracked `app/tls/app_cert.key`, still need the credential owner and deployment
  access, not an engineering worktree.
