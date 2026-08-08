# BASELINE: traceability
date: 2026-08-08

git status: clean at start (only `.agents/feature-index.md` self-update from
`feature_index_sweep.py` registering this review's in-flight worktree, plus the new
`.agents/specs/traceability.md` this review wrote).

## Existing coverage (pre-review)

No `tests/test_traceability.py` exists. The feature index's documented gap ("no test
touches sourcemap at all") is accurate for the `/api/core/sourcemap/*` routes specifically,
but the underlying forward-trace machinery this slice shares with `inventory` is not
untested — it's covered from two directions:

```
uv run pytest tests/test_dag_traversal.py tests/test_inventory.py -v
======================= 60 passed, 28 warnings in 21.62s =======================
```

- `tests/test_dag_traversal.py` (32 tests) — unit-level coverage of `DAGTracer` /
  `trace_forward` / `trace_backward` / `find_impacted_by_expired_raw` in
  `app/core/backend/dagtraversal.py`: cycle safety, tenant isolation on step-order
  connections, N+1 query bounds, deterministic output, zero-quantity inclusion rules.
- `tests/test_inventory.py` includes 2 tests hitting `GET /api/core/inventory/trace/<id>`
  specifically (`test_trace_enrichment_enriches_own_org_step_data`,
  `test_trace_enrichment_does_not_leak_another_orgs_step_data`) — real API-level
  cross-tenant leak regression coverage for that one route's step-data enrichment.

Zero coverage, at any level, for:
- `GET /api/core/inventory/trace-backward/<id>` (route-level; the underlying
  `trace_backward()` function has unit coverage, but the route itself — UUID validation,
  404 shape, `traced_item` inclusion fix from sourcemap-v2 §7a — does not)
- `GET /api/core/sourcemap/objects`
- `POST /api/core/sourcemap/trace` (both the current-state and temporal branches)
- `app/core/backend/temporal_dag_tracer.py` (`TemporalDAGTracer` — 0 references anywhere
  under `tests/`)
- `app/core/frontend/js/sourcemap.js` (2128 lines, no e2e coverage)

This absence of coverage is exactly where this review's two pre-existing findings were
sitting undetected (see security-audit report): a tenant-isolation gap in
`TemporalDAGTracer._snapshot_at` / the `sourcemap_trace` temporal branch, and a dead,
broken import (`app.features.workflow_engine.dagtraversal`, which does not exist anywhere
in the repo) in the same route's current-state branch — always 500s, currently unreachable
from the UI only because `sourcemap.js`'s one caller of this route always sets `as_of`.

## Verdict
Baseline tests green (60/60, no pre-existing failures to report). Proceeding to the
verification chain to close the coverage gap and patch the two findings above.
