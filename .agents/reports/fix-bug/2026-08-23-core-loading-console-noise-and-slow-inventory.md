# FIX: console noise (telemetry 503s + blocked Cloudflare beacon) and slow /core/ data population

date: 2026-08-23

## symptom

Reported directly by the user while loading `/core/` on `test.biz-e.app`:

1. Wants telemetry disabled in the test environment (currently noisy: `faro-web-tracing`
   and `posthog-array` repeatedly POST to `/telemetry` and get `503 Service Unavailable`,
   plus a MIME-type-blocked `GET /telemetry/posthog/static/lazy-recorder.js`).
2. A CSP violation console error: Cloudflare's `beacon.min.js` (from
   `static.cloudflareinsights.com`) is blocked by `script-src`.
3. Loading `/core/` with 200+ completed batches and 200+ inventory items is slow to
   populate with server-side data, even though the SPA shell (LCP) paints instantly.

## root_cause

**#1 — telemetry noise.** `app/config/test.ini:42` had `rum_enabled = true`. Although
`grafana_data_enabled`/`posthog_data_enabled` are `false` in the same file (which, per the
current code, already gates both the client-side SDK init in
`app/ui/shared/observability-rum.js` and the server-side `/telemetry` proxy in
`app_factory.py:_telemetry_response`), the actually-deployed `test.biz-e.app` instance
still exhibits the SDK initializing and hitting `/telemetry`, which strongly suggests it is
running an image built before the `grafana_data_enabled`/`posthog_data_enabled` gate was
added (commit `4d20a36`) or otherwise not reflecting this repo's current `test.ini`.
Either way, relying solely on those two gates leaves `test.biz-e.app` — a publicly
reachable environment whose local observability stack (Alloy/PostHog) isn't guaranteed to
be running (`preflight.py` currently reports `observability_stack: down`) — one stale
deploy or one flipped flag away from noisy 503s again. `rum_enabled` itself needed to be
off for `test`.

**#2 — CSP-blocked Cloudflare beacon.** Not a code bug. `static.cloudflareinsights.com`
is Cloudflare's own "Web Analytics" / Browser Insights auto-injected beacon, added at the
edge (this domain is Cloudflare-proxied — see the Origin Certificate at `app/tls/`), not
referenced anywhere in this repo's templates or JS. The CSP (`app_factory.py:400-412`)
correctly has no third-party script-src entries — this app's stated architecture is
same-origin telemetry only ("nothing talks to a third-party collector directly",
CLAUDE.md). The console error is CSP successfully doing its job, not a defect. See
`recommendation` below — this needs a Cloudflare dashboard change, not a code change.

**#3 — slow /core/ data population.** `list_inventory()` in
`app/core/backend/backend.py` builds `previous_steps_data` for every WIP/final-product
inventory item via a recursive `trace_step_chain()` closure (line ~2858) that issued
**two unbatched DB queries per DAG node, per item** — walking backward through the item's
full production chain on every single call to `GET /api/core/inventory`. For an org with
200+ completed batches (each producing several chained WIP/final inventory rows), this
scales as O(items × chain depth) queries. The codebase already has a properly
bulk-loading traversal engine for exactly this (`DAGTracer.traverse()` in
`app/core/backend/dagtraversal.py`, used by the `/trace` and `/trace-backward` endpoints)
— `list_inventory()`'s enrichment path just never adopted that pattern and kept its own
older, unbatched implementation. Confirmed via a synthetic 60-node chain: the unfixed code
took **2.9s** and hit the traversal's 50-depth safety cap; the query count for the fixture
scales linearly with chain depth (unbounded, well past 3000 queries for a 60-node chain).
This is the actual reason data population is slow while LCP (shell paint) stays fast — the
telemetry 503s are async/non-blocking and unrelated to this.

## repro_tests

- `tests/test_inventory.py::test_list_inventory_query_count_does_not_scale_with_chain_depth`
  — builds a synthetic 60-node linear DAG (`build_large_linear_chain`) and asserts
  `GET /api/core/inventory`'s query count stays under a small constant regardless of chain
  depth. Verified red before the fix (2.9s response, hit the depth-50 recursion cap);
  green after.
- `tests/test_observability_config.py::test_test_environment_disables_rum_entirely` —
  asserts `test.ini`'s `[observability] rum_enabled` is `False`. Verified red before the
  ini edit; green after.

## fix

- `app/core/backend/backend.py:2793-2934` — added a lazy, request-scoped cache
  (`_dag_trace_lookups()`) that bulk-loads every org-scoped `InventoryItem` and
  `ExecutionStep` once (only if at least one item needs tracing), then has
  `trace_step_chain()` do in-memory dict lookups instead of per-node queries. Same
  bulk-load-then-walk-in-memory shape as `DAGTracer.traverse()`; output shape
  (`previous_steps_data`) is unchanged, so no API/frontend contract change. The
  `ExecutionStep` bulk load is scoped via `Execution.org_id`, which is a *stricter*
  tenant check than the previous per-node query relied on (that query had no explicit
  org filter at all, trusting the FK invariant).
- `app/config/test.ini:42`, `app/config/test.ini.template:38` — `rum_enabled = true` →
  `false`.
- `app/core/backend/backend.py` — two `# nosemgrep: sqlalchemy-all-without-limit`
  annotations on the new bulk-load queries, same justification/pattern as the existing
  one in `dagtraversal.py`.

## not fixed in code (recommendation for the user)

**#2, Cloudflare beacon CSP violation**: disable Cloudflare's "Web Analytics" / Browser
Insights auto-injection for the `test.biz-e.app` (and presumably `*.whistlebird.co.nz`)
zone in the Cloudflare dashboard (Speed → Observatory / Analytics → Web Analytics, or
wherever the zone currently has it turned on). Do **not** add
`static.cloudflareinsights.com` to CSP `script-src` — that would let Cloudflare's beacon
actually run and start sending browsing data to a third party, which contradicts this
app's documented same-origin-only telemetry architecture. The CSP is already doing the
right thing by blocking it; the fix is turning off the injection at the source.

**Also worth doing** (not done here — outside this repo, ops action): redeploy
`test.biz-e.app` from current `main`/this branch. The stale-looking deployed behavior
(503s despite `grafana_data_enabled=false` already being committed) suggests the running
container predates recent observability-gating commits.

## chain

- ruff: pass (`app/core/backend/backend.py`, `app/config/`)
- semgrep (`.semgrep` config, scoped to `backend.py`): pass — 1 finding
  (`sqlalchemy-all-without-limit`) resolved with the same justified suppression pattern
  already used in `dagtraversal.py`
- full suite: `uv run pytest tests/ -v` → **1724 passed, 31 skipped**, no regressions
- test-evaluator (manual, not a separate agent run): both repro tests independently
  verified red-before/green-after by stashing each fix in isolation and re-running
- security/tenant review (manual): the fix's bulk-load queries are org-scoped; the
  `ExecutionStep` lookup is now *more* strictly org-scoped than the code it replaced
- migration-safety: n/a — no schema change
- e2e-playwright: **skipped** — no new user-facing flow; the existing inventory/DAG
  traversal test suites (`tests/test_inventory.py`, `tests/test_dag_traversal.py`) already
  cover this route and pass
- security-audit / security-tenant-audit (dedicated subagent runs): **skipped** — scope
  is a query-batching change with no new external surface or auth path; manual review
  above covers the relevant tenant-isolation question directly
- perf-guardrails: informal — synthetic 60-node chain went from 2.9s/unbounded-queries to
  well under the route's existing budget; did not re-run the full `perf-guardrails` E2E
  measurement suite (it measures against a near-empty baseline org, which wouldn't
  exercise this path meaningfully) or log into the live `test.biz-e.app` deployment,
  since it's the actually-affected environment and out of reach from this session
- observability: no new instrumentation added — the existing `dag.traverse` trace span
  pattern in `dagtraversal.py` wasn't extended to this inlined trace, since the fix
  deliberately kept `list_inventory()`'s existing shape rather than migrating it onto
  `DAGTracer` itself (see follow-up below)
- merge-request: not run — reporting back to the user in this session instead of opening
  an MR autonomously, since this was interactive, user-driven troubleshooting

## follow-up (not done, flagged for awareness)

`list_inventory()`'s trace closure duplicates logic that `DAGTracer` already implements
properly. A future cleanup could replace the inlined closure with a call into
`DAGTracer.traverse(direction="backward")` and adapt its `TraversalResult` into the
`previous_steps_data` shape — would remove the duplication entirely. Not done here to
keep this a minimal, low-risk bug fix rather than a refactor.

## verdict

fixed (both #1 and #3); #2 requires a Cloudflare dashboard change, not a code change —
reported with a specific recommendation, not applicable to fix via this repo.
