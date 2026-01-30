Cursor Prompt

You are refactoring the DAG traversal layer of this platform to move from ad-hoc forward/backward tracing functions to a single, scalable traversal engine that supports multiple use cases (traceability, recall simulation, site map visualization, compliance overlays).

This refactor must improve clarity of responsibility, extensibility, and long-term maintainability, without introducing unnecessary abstraction.

1. Core Architectural Goal (Highest Priority)

Replace existing directional traversal functions (e.g. forward trace, backward trace) with one unified traversal engine:

tracer.traverse(
    start_nodes=[...],
    direction="forward" | "backward",
    stop_conditions=[...],
    filters=[...],              # optional
)


This engine must be:

Direction-agnostic

Capable of multi-root traversal

Free of hardcoded depth limits

Reusable across all DAG-based use cases

This unlocks:

Recall / blast radius simulations

What-if scenarios

Site map visualization

Compliance overlays

Future graph queries without rewriting traversal logic

2. Remove MAX_DAG_DEPTH (Explicit Requirement)

Remove all hard limits on DAG depth (e.g. MAX_DAG_DEPTH).

Traversal depth must instead be constrained by:

Natural graph termination (no outgoing edges)

Explicit stop conditions (e.g. stop at sales, stop at inventory items)

SQLAlchemy query efficiency and batching

If any protection is needed, it must be:

Query-based (e.g. pagination, visited-node tracking)

Not an arbitrary numeric cap

3. Introduce Traversal Result Objects (Critical Design Fix)

Traversal must not return raw dicts, sets, or ad-hoc structures.

Instead, introduce a TraversalResult object that represents the meaning of a traversal, not just the mechanics.

Example (conceptual, not prescriptive):

class TraversalResult:
    root_nodes: set[UUID]
    direction: Literal["forward", "backward"]
    nodes: set[Node]
    edges: set[Edge]
    executions: set[Execution]
    metadata: TraversalMetadata


This object should:

Encapsulate traversal output

Own post-processing logic

Expose semantic helpers, e.g.:

impacted_inventory_items()

affected_sales()

as_site_map_graph()

as_recall_view()

Important:
Traversal logic lives in the tracer.
Interpretation and shaping live in the result object.

4. Refactor Existing Code to Use the New Engine

Update all existing code paths that currently:

Call forward/backward traversal functions

Perform post-processing in API routes or services

Duplicate graph logic across endpoints

They must now:

Call tracer.traverse(...)

Receive a TraversalResult

Use result methods instead of re-implementing logic

API layers should:

Assemble parameters

Choose presentation/view methods

Never re-traverse or reshape raw graph data

5. Stop Conditions (First-Class Concept)

Introduce stop conditions as composable traversal rules, not inline checks.

Examples:

Stop at inventory items

Stop at sales

Stop when execution is consumed

Stop when compliance boundary is reached

These should be:

Passed into traverse(...)

Testable independently

Reusable across use cases (site map, recall, compliance)

6. Preserve and Centralize Invariants

The traversal engine must enforce:

No infinite loops (visited node tracking)

Direction-correct edge traversal

Consistent node identity handling

Deterministic results for the same inputs

These invariants must live inside the tracer, not callers.

7. Design Intent (Do Not Over-Abstract)

Do NOT:

Introduce separate ForwardTracer / BackwardTracer classes

Build a generic graph DSL

Add speculative features not needed for current DAG use cases

DO:

Keep one tracer

Keep traversal configuration explicit

Make intent readable to non-graph experts

8. Validation Checklist (Cursor Must Ensure)

After refactor:

There is only one traversal engine

No hardcoded depth limits exist

Traversal returns TraversalResult objects

API code is thinner and clearer

Adding a new traversal use case does not require new traversal logic

9. Deliverables

Refactored traversal engine (traverse)

TraversalResult (or equivalent) abstraction

Updated call sites using the new approach

Removal of MAX_DAG_DEPTH

No regression in existing behavior

This refactor prioritizes correctness, clarity, and scalability over premature optimization.

If any trade-offs are required, prefer:

clarity of responsibility > minor performance gains

3. Bulk Loading to Fix Query Explosion (High Priority)

Problem in current _forward():

steps = (
    self.session.query(ExecutionStep)
    .join(Execution, ExecutionStep.execution_id == Execution.id)
    .filter(Execution.org_id == self.org_id)
    .all()
)


This fetches all execution steps on every recursion, causing O(N²) complexity.

Fix:

Bulk-load all relevant ExecutionSteps once at the start

Build indices in memory:

steps_by_input_item_id: dict[UUID, list[ExecutionStep]]
steps_by_input_name: dict[str, list[ExecutionStep]]


_forward() becomes pure in-memory traversal

4. Depth Limit Handling

Remove hard MAX_DAG_DEPTH = 50 from traversal

If a soft safety valve is desired:

Rename to MAX_DAG_DEPTH_SOFT

Make configurable per org or per call

Log once per traversal, not per node

Stop traversal gracefully if exceeded

5. Eliminate Name-Based Matching

Current code is doing:

if inp.get("name"):
    inv = self.session.query(InventoryItem)... 
    if inv and inp["name"].lower() == inv.name.lower():


This is risky: silent ambiguity, string dependency, regulator risk

Fix:

Treat as a migration fallback only

Add feature flag ALLOW_NAME_MATCH_FALLBACK = False

Log whenever used

Plan to migrate all data to inventory_item_id

6. Backward Filtering Optimization (Medium Priority)

Current _trace_backward_ids_only during forward traversal is computationally heavy

Replace:

for cid in connected_ids:
    sources = self._trace_backward_ids_only(cid)
    if root in sources:
        filtered_ids.add(cid)


With:

Only traverse forward from root

Eliminate backward filtering entirely

DAG is directional and rooted — ancestry verification is unnecessary

7. Fix N+1 Queries in _add_step_order_connections

Current implementation queries per step in a nested loop

Fix: bulk load all step IDs once, index in memory, and reference objects directly

8. Maintain Correct Semantics in find_impacted_by_expired_raw

Logic is correct and clean

Minor improvements:

Rename is_made_with_expired → made_after_raw_expired

Consider returning execution_id explicitly

9. Remove Graph Fixups from API Layer

API currently compensates for UI expectations (visual-only edges)

Fix:

Keep DAGTracer output strictly factual

Move “visual-only inferred edges” into graph presentation layer

Enables recall simulation, compliance overlays, and what-if scenarios

10. Cache Enrichment Layer

_enrich_items_bulk is deterministic but called multiple times

Add per-request cache:

self._enrichment_cache[item_id] = enriched_dict


Improves Site Map traversal performance

11. Refactor All Existing Usage

Update all code paths to call tracer.traverse(...) and use TraversalResult

Remove ad-hoc traversal logic and direct DB queries scattered in services or API

Ensure deterministic, pure traversal with no repeated queries

12. Validation Checklist

After refactor:

Only one traversal engine exists

MAX_DAG_DEPTH is removed or configurable as a soft limit

Bulk queries are at the start; recursion is pure in-memory

Name-based fallback is off by default

Backward filtering is eliminated

N+1 queries removed

DAGTracer output is factual

API / UI presentation handled separately

Enrichment layer is cached per request

TraversalResult exposes semantic helpers for downstream use cases

This ensures the DAG traversal is performant, correct, and future-proof while keeping regulatory and recall workflows safe.