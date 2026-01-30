Prompt for Cursor: Refactor DAG Traversal and Backend Inventory Tracing

Context:
Our backend currently performs forward and backward DAG traversals for inventory traceability, including raw materials, intermediates, and final products. The existing code is functional but:

It has deep nested loops and recursion scattered across multiple routes.

There’s a lot of duplicate logic for forward/backward tracing and connection building.

Hard-coded depth limits and inline queries reduce maintainability and scalability.

Extra_data enrichment (execution prompts, variable inputs/outputs) is repeated in multiple endpoints.

We want to refactor this into a single, reusable DAG traversal class and address priority improvements in order. Create this class in a new file - app/core/backend/dagtraversal.py

Priority Points to Address

Centralize DAG Traversal Logic

Implement a DAGTracer class that can:

Traverse forward from a node (inventory item) to all connected items.

Traverse backward to all source items.

Prevent cycles using visited sets.

Make it reusable for any inventory DAG traversal, not tied to a specific endpoint.

Optimize Queries

Minimize repeated database queries inside loops (e.g., querying ExecutionStep or InventoryItem repeatedly).

Use bulk queries wherever possible to fetch all relevant steps/items in one go.

Ensure all queries are filtered by org_id consistently.

Connection Mapping

Build direct connections (from_id → to_id → execution_id) during traversal.

Ensure connections are accurate for both forward and backward traces.

Include intermediates and finals, with optional quantity filtering.

Extra Data Enrichment

Centralize logic to enrich items with:

execution_prompts

variable_inputs

variable_output

process_name

Avoid repeating enrichment code across multiple endpoints.

Scalability & Maintainability

Ensure DAGTracer can handle large graphs efficiently.

Provide a clear API for endpoints: e.g., DAGTracer.trace_forward(item_id) and DAGTracer.trace_backward(item_id) returning both nodes and connections.

Document expected return structure for consistency across endpoints.

Testing & Safety

Include safety checks for:

Invalid UUIDs

Missing or null fields

Cycles in the DAG

Include optional logging for deep or complex DAGs.

Refactor Existing Routes

Replace the current forward/backward traversal code in /api/core/inventory/trace/<raw_material_id> and /api/core/inventory/trace-backward/<inventory_item_id> with the new DAGTracer.

Review the /api/core/inventory/check-needed endpoint and if related use the new class here as well. If not related we can sort that outside of this

Ensure the JSON response structure remains compatible.

Deliverables

DAGTracer class with:

trace_forward(item_id: UUID, include_quantity_filter: bool = True) → returns connected items + connections

trace_backward(item_id: UUID, include_quantity_filter: bool = True) → returns source items + connections

Refactored /api/core/inventory/trace and /api/core/inventory/trace-backward routes using DAGTracer. Also review if the /api/core/inventory/check-needed endpoint is applicable here

Unit tests demonstrating:

Forward and backward traversal correctness

Cycle detection

Connection mapping

Extra data enrichment

unit tests should be stored in tests/ as these run in CI jobs

Documentation of DAGTracer usage and response structure.