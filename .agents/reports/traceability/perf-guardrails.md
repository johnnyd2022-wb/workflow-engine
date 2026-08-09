# PERF: traceability
date: 2026-08-09
verdict: clean

## Added to `.agents/perf/budgets.json`

Neither this slice's page nor its simplest API route was in the measure lists before this
review. Added:

- `measure.pages`: `/core/sourcemap`
- `measure.api`: `/api/core/sourcemap/objects`

Measured (`.agents/reports/perf/last-run.json`, defaults apply — no override needed):

| route | kind | backend_ms | queries | lcp_ms |
|---|---|---|---|---|
| `/core/sourcemap` | page | 3.7 | 2 | 56 |
| `/api/core/sourcemap/objects` | api | 6.9 | 8 | — |

Both well inside budget (page: 50ms/5 queries/1000ms LCP; api: 150ms/15 queries).

## Routes not addable to the measure harness

`GET /api/core/inventory/trace/<raw_material_id>`, `GET
/api/core/inventory/trace-backward/<inventory_item_id>`, and `POST
/api/core/sourcemap/trace` all require a real, pre-seeded inventory item UUID as a path
segment or body field to be measured meaningfully. `test_perf_budgets.py`'s `measure.api`
format only supports a bare route string (GET, no params) or a static self-contained POST
body (`{route, method, body}` — see `/api/dilution-calculator/solve`'s example, whose body
needs no DB lookup). There is no dynamic-id substitution mechanism in the harness today, so
these three routes cannot be added without extending `test_perf_budgets.py` itself — out of
proportion for this review and the perf-guardrails skill's own maintenance to take on, not
something to improvise inline here.

These three routes' actual expense is the shared multi-hop traversal engine
(`app/core/backend/dagtraversal.py`'s `DAGTracer.traverse()`), which already has its own
dedicated regression: `tests/test_dag_traversal.py::TestN1Guard::test_linear_traversal_query_count_bounded`
asserts the traversal's query count stays bounded regardless of chain length (the actual N+1
risk for this code path). `TemporalDAGTracer.trace()` (`temporal_dag_tracer.py`) is a single
bounded-`limit(200)` timeline query plus one edge-building query and BFS over an in-memory
edge list — no per-node query loop, so no comparable N+1 surface exists there either.

## Observed, not a finding

`GET /api/core/sourcemap/objects` runs up to 3 independent `count()` + `query()` pairs (one
per entity type: inventory item, execution, process) rather than a single UNIONed query, so
its query count (8, including org/session overhead) is higher than a single-table list
endpoint of similar size would need. At 8 queries against a budget of 15 this is not a
finding — flagging only because a much larger seed dataset (thousands of rows per type)
would scale the *count* of round trips linearly with entity types (fixed at 3), not with row
count, so this stays flat under load; it is not a regression risk, just a structural
observation left for whoever next touches this route.
