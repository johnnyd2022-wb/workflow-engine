Cursor Prompt: DAGTracer Refactor & Optimization
Objective

Refactor and optimize the DAGTracer system to ensure:

Fully accurate, auditable, and trusted inventory traceability.

Elimination of all unnecessary database queries (no N+1 queries).

Simplification of traversal logic while preserving API outputs.

No hard depth limits.

Removal of ambiguous fallback mechanisms (e.g., name-based matching).

Instructions
1. Traversal Engine

Keep the single traversal engine: traverse(start_nodes, direction, stop_conditions, filters).

Direction-agnostic; supports multi-root traversal.

No MAX_DAG_DEPTH hard limit; termination only via graph structure or stop conditions.

All execution steps and inventory items must be bulk-loaded at the start of traversal to eliminate N+1 queries.

Maintain per-request enrichment cache (_enrichment_cache) to avoid repeated enrichment queries.

2. Remove Ambiguity / Name-Based Fallback

Remove ALLOW_NAME_MATCH_FALLBACK entirely.

Do not allow string-based name matching anywhere in traversal.

All connections must rely on:

InventoryItem.id (UUID)

ExecutionStep.id / Execution.id

Traversal must always be deterministic and auditable based on execution IDs.

3. Eliminate N+1 Queries

Cursor should check for and refactor any N+1 queries. Examples:

Backward traversal per-node queries:

parent_item = session.query(InventoryItem).filter(...).first()


Refactor to bulk-load all potentially reachable items before recursion.

Use a dictionary lookup in-memory instead of querying per recursion.

Step-order connections:

Already refactored to bulk-load steps.

Verify no remaining N+1s.

Enrichment layer:

_enrich_items_bulk already bulk-loads ExecutionStep, Execution, Process.

Verify the cache is used and queries aren’t repeated.

Other potential N+1s:

Review any place where queries occur inside loops or recursive functions.

Move bulk queries outside loops wherever possible.

4. Stop Conditions & Filters

Traversal accepts stop_conditions and filters to terminate or prune nodes.

Examples:

stop_at_inventory_types("final_product") stops traversal at final products.

Must be composable and extendable without modifying traversal internals.

5. API & Result Handling

Use TraversalResult for all outputs.

Maintain legacy API dict shapes for:

trace_forward

trace_backward

find_impacted_by_expired_raw

Step-order edges remain visual only, added via add_step_order_connections.

Ensure connections are always valid (from_id, to_id, execution_id).

6. Find Impacted Items

find_impacted_by_expired_raw:

Trace forward from raw material.

Only include items produced after raw material expiry.

Do not use name-based matching.

Bulk-load items and steps before filtering.

7. Deliverables

Cursor should:

Refactor DAGTracer to remove ALLOW_NAME_MATCH_FALLBACK entirely.

Eliminate all N+1 queries, especially:

Backward traversal per-node queries.

Any remaining loops querying InventoryItem or ExecutionStep.

Maintain bulk-loading and caching for enrichment and connections.

Keep all traversal output APIs compatible.

Ensure traversal is deterministic and accurate, fully based on execution IDs.

Review _enrich_items_bulk and add_step_order_connections for efficiency.

Remove any reference to MAX_DAG_DEPTH.