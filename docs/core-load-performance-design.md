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

1. `app/config/prod.ini` is tracked and includes a database password. Treat it as exposed:
   rotate the real credential, remove the value from Git history using the team's incident
   procedure, and require a deployment secret/environment value at production startup.
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
