# SPEC: traceability
status: reviewed
name: Traceability (Sourcemap) — forward/backward inventory trace, temporal replay
slug: traceability
blueprint: core_bp — routes in `app/core/backend/backend.py`; page template at
  `app/core/frontend/sourcemap/sourcemap.html`
url_prefix: /api/core, /core

## Description

Lets a user pick any inventory item (raw material, WIP, or final product) and see its full
production lineage: forward (what did this raw material become) or backward (what went into
this item), rendered as a timeline/map/table on the `/core/sourcemap` page. A second mode —
temporal replay — reconstructs the same kind of graph as it existed at a past point in time,
using the event-sourcing log (`entity_events`, owned by the platform layer / `activity-log`
slice) rather than current mutable state.

Two independent traversal engines power this:
- **Current-state trace**: `app/core/backend/dagtraversal.py`'s `DAGTracer` /
  `trace_forward()` / `trace_backward()` module functions, walking `InventoryItem` /
  `Execution` / `ExecutionStep` rows as they exist now.
- **Temporal trace**: `app/core/backend/temporal_dag_tracer.py`'s `TemporalDAGTracer`,
  walking `execution.step_completed` events in `entity_events` up to a given `as_of`
  timestamp.

ASSUMPTION: No spec existed at `.agents/specs/traceability.md` before this review. This
spec is reconstructed from `.agents/feature-index.md`'s `traceability` block, the design
docs at `cursor_instructions/sourcemap-v2.md` and
`cursor_instructions/event-sourcing-temporal-sourcemap.md`, and the routes/frontend code as
they exist on `main` at review time (2026-08-08).

ASSUMPTION: `cursor_instructions/event-sourcing-temporal-sourcemap.md` is a design/build log
for a much larger event-sourcing initiative spanning many slices (inventory cards, process
versioning, activity feed, auth events). Only the sourcemap/trace surface it describes is in
scope for this spec — the rest belongs to `platform`, `activity-log`, `inventory`,
`process-design`, and `execution`, each reviewed (or not) on their own terms per the feature
index's slice boundaries.

## Users & permissions
- roles: any authenticated user of the org. No `@requires_role` gate on any route in this
  surface.
- tenant_scoped: yes for every route except one confirmed gap (AC9, below). `org_id =
  UUID(g.org_id)` is resolved from session-derived tenant-context middleware in every route
  handler.

## Routes

| Route | Method | Purpose |
|---|---|---|
| `/core/sourcemap` | GET | SPA page shell (`base_spa.html` extension) |
| `/api/core/inventory/trace/<raw_material_id>` | GET | Forward trace from a raw material |
| `/api/core/inventory/trace-backward/<inventory_item_id>` | GET | Backward trace from any item |
| `/api/core/sourcemap/objects` | GET | Paginated index of traceable entities for search/browse |
| `/api/core/sourcemap/trace` | POST | Current-state OR temporal trace, dispatched on `as_of` presence |

## Acceptance criteria

### Forward trace — `GET /api/core/inventory/trace/<raw_material_id>`
- AC1: A non-UUID `raw_material_id` returns 400 with an error body, never a 500 or a stack
  trace (`validate_item_uuid`).
- AC2: A UUID that does not resolve to an `InventoryItem` row scoped to the caller's
  `org_id` returns 404 `"Raw material not found"` — including a UUID that belongs to
  another org's item (cross-tenant existence must not be distinguishable from
  non-existence).
- AC3: The response includes the raw material itself (even if not returned by
  `trace_forward`'s connected-items set), plus `intermediates` (WIP), `finals` (final
  product), `all_items`, and `connections` — every connection's `from_id`/`to_id` must be a
  member of the returned item set (no dangling `execution_id` masquerading as an item id).
- AC4: Items with `quantity == 0` are still included — `include_quantity_filter=False` is
  passed explicitly; a full audit trail must show fully-consumed intermediates, not just
  items with stock on hand.
- AC5: Every returned item carries `step_data` (`completed_at`, `actual_inputs`,
  `actual_outputs`) when it has a `source_execution_step_id` resolvable within the caller's
  org, and `step_data: null` otherwise — never a step belonging to another org
  (`_hydrate_step_data` joins `ExecutionStep` through `Execution.org_id`).

### Backward trace — `GET /api/core/inventory/trace-backward/<inventory_item_id>`
- AC6: Same UUID validation and cross-tenant 404 behavior as AC1/AC2.
- AC7: The traced item itself is included in `all_items` (and in the response's
  `traced_item` key) even when `trace_backward` doesn't return it as a source — this was a
  historical bug (see `cursor_instructions/sourcemap-v2.md` §7a) fixed by building
  `traced_item_data` first and appending it to `all_result_items` before step enrichment and
  connection filtering both run over it.
- AC8: `raw_materials` and `intermediates` in the response exclude the traced item itself;
  `connections` only reference ids present in the response.

### On-demand trace dispatch — `POST /api/core/sourcemap/trace`
- AC9 **(fixed 2026-08-09, review-feature)**: When `as_of` is present in the request body,
  the route verifies `root_id` belongs to the caller's `org_id` before returning any state
  for it. Was a confirmed cross-tenant leak (F1, `.agents/reports/traceability/security-audit.md`):
  `TemporalDAGTracer._snapshot_at()` (`temporal_dag_tracer.py:121-134`) queried `EntityEvent`
  by `entity_id` alone, no `org_id` filter, so a caller supplying another org's entity UUID
  as `root_id` received that entity's most recent event payload snapshot (name, quantity,
  supplier, etc.) in the response's `root.state` field. Fixed by adding `EntityEvent.org_id
  == self.org_id` to that query. `edges` and `timeline` were already correctly org-scoped.
  Regression: `tests/e2e/traceability/test_tenant_isolation.py::test_ac9_temporal_trace_root_state_not_visible_cross_tenant`.
- AC10 **(fixed 2026-08-09, review-feature)**: When `as_of` is absent, the route performs a
  current-state trace and returns 200 with a real graph. Was dead/broken (F2): `backend.py`
  imported `trace_backward, trace_forward` from `app.features.workflow_engine.dagtraversal`,
  a module that does not exist anywhere in the repository, with a call signature that didn't
  match the real module either — every call raised `ModuleNotFoundError` inside a bare
  `except Exception`, always 500. Not user-visible at the time (the only frontend caller,
  `smRunTemporalTrace` in `sourcemap.js`, always supplies `as_of`) but a live authenticated
  route silently breaking its documented alternate mode. Fixed by routing to
  `app.core.backend.dagtraversal.trace_forward`/`trace_backward` (the real module, same
  pattern the two sibling GET routes already use). Regression:
  `tests/test_traceability.py::TestCurrentStateTraceBranch`,
  `tests/e2e/traceability/test_sourcemap_page.py::test_ac10_sourcemap_trace_dispatch_without_as_of_returns_current_state_graph`.
- AC11: `root_id` that is not a valid UUID returns 400, not 500.
- AC12: `depth` is clamped to a maximum of 10 hops regardless of what the client requests
  (`min(int(data.get("depth", 5)), 10)` in the route; `TemporalDAGTracer.__init__` clamps
  again to the same ceiling).
- AC13: An invalid `as_of` string returns 400 `"Invalid as_of datetime format"`, not 500.

### Temporal trace graph construction — `TemporalDAGTracer`
- AC14: `trace()` only considers `execution.step_completed` events with `created_at <=
  as_of` scoped to `self.org_id` when building edges — an event belonging to another org
  never contributes an edge to this org's graph.
- AC15: BFS from `root_id` expands up to `max_depth` hops or until no new nodes are
  reachable, whichever comes first; a graph with a cycle terminates because `connected` is a
  set and the loop stops when `new_conn - connected` is empty.
- AC16: `_build_timeline()` returns at most 200 events, ordered oldest-first, scoped to both
  `self.org_id` and the connected-node id set.
- AC17: Non-root nodes in the returned `nodes` list always carry `state: None` (never
  populated from an event) — this is current, intentional behavior per the "Known
  limitations" note in the design doc ("Nodes with no pre-date events appear nameless"), not
  a bug to fix in this review; only the root node's `state` is populated (via `_snapshot_at`,
  see AC9 for its tenant-isolation gap).

### Sourcemap objects index — `GET /api/core/sourcemap/objects`
- AC18: Every sub-query (`InventoryItem`, `Execution`, `Process`) filters by the caller's
  `org_id`.
- AC19: `type` query param, when set to one of `inventory_item`/`execution`/`process`,
  restricts the result to that type only; when absent, results are drawn from all three.
- AC20 **(fixed 2026-08-09, review-feature)**: `page`/`limit` are clamped (`limit` capped at
  200) and never raise on a non-numeric or missing value. Was F3
  (`.agents/reports/traceability/security-audit.md`): `int(request.args.get("page", 1))` and
  `int(request.args.get("limit", 50))` raised unhandled `ValueError` → 500 on a non-numeric
  value (e.g. `?page=abc`). Fixed with a try/except returning 400. The same class existed a
  second time at `POST /api/core/sourcemap/trace`'s `depth` parse (F4), fixed identically.
  Regression: `tests/test_traceability.py::TestSourcemapObjectsPageLimitParsing`,
  `TestSourcemapTraceDepthParsing`.

### Page route
- AC21: `GET /core/sourcemap` requires auth and renders the SPA shell only; all trace/object
  data is fetched client-side.
- AC22: All five routes above return 401 for an unauthenticated request, before touching any
  org data.

### Frontend (`sourcemap.js`, `sourcemap.css`, `sourcemap.html`)
- AC23: `smTraceItem` calls `smRunTemporalTrace` (POST `/api/core/sourcemap/trace` with
  `as_of`) when `temporalAsOf` is set, and the two direct GET trace endpoints otherwise —
  confirmed the only frontend caller of `POST /api/core/sourcemap/trace` always sets
  `as_of`, which is why AC10's dead branch has not been user-visible.
- AC24: Server-supplied strings (item name, supplier, actor, summary text) are never
  inserted via `innerHTML` without escaping.

## Non-goals / explicitly out of scope
- `entity_events` writing (`EventWriter`), the activity feed / entity story panels
  (`GET /api/core/entities/*`), and diff-humanization (`_human_summary`,
  `_event_diff_rows`) — these belong to the `activity-log` slice per the feature index, even
  though `sourcemap_trace`'s temporal branch calls `_human_summary` to annotate its own
  `story` field. Only the call site (inside this slice's route) is in scope; the function's
  own correctness is `activity-log`'s to review.
- Card enrichment (inventory/execution/process card audit badges, sparklines) — belongs to
  `inventory`, `execution`, `process-design`.
- Process versioning (`process_versions`, version history panel) — belongs to
  `process-design`.
- Everything under "Phase 7 UI Testing Guide" in
  `cursor_instructions/event-sourcing-temporal-sourcemap.md` that is not the sourcemap page
  itself.
