Inventory DAG Traversal – Improvement Tasks
1. Recursion / Memory Safety

Issue: _forward and _backward are recursive and may hit recursion limits on very large DAGs.

Action:

Refactor traversal to be iterative using a stack or queue.

Ensure behavior is identical (nodes and edges collected correctly).

2. Edge Accuracy After Node Filtering

Issue: edges_final filters edges after node filtering. Using include_quantity_filter=True may drop nodes, leaving orphaned edges or inaccurate connections.

Action:

Add logging or warnings when edges are removed due to filtered nodes.

Review as_trace_forward_response and as_trace_backward_response to ensure step connections remain valid and do not create "shortcut" edges.

3. find_impacted_by_expired_raw Efficiency

Issue: Currently re-queries InventoryItem and ExecutionStep even after traversal.

Action:

Refactor to use nodes already collected in TraversalResult where possible.

Minimize additional DB queries for impacted items.

4. Date Normalization

Issue: _normalize_date only handles ISO strings, date/datetime. Non-ISO formats may fail silently.

Action:

Consider using dateutil.parser.parse for robust parsing of multiple date formats.

Ensure all comparisons (production_date > expiry_date) are correct.

5. Quantity Filtering & Decimal Handling

Issue: Invalid/malformed quantities are silently skipped.

Action:

Log items that fail Decimal() conversion.

Optional: validate data at import to reduce runtime skips.

6. Step-Order Connections

Issue: add_step_order_connections relies on step_number; missing steps may break visual ordering.

Action:

Add logging for missing or duplicate step_numbers.

Ensure all items produced by the same execution step are connected in order where relevant.

7. Logging & Observability

Issue: _log exists but is unused.

Action:

Log key traversal stats:

Number of nodes visited

Number of edges collected

Number of nodes filtered out

Optionally log start and end nodes for each traversal.

8. Type Annotations & Clarity

Action:

Replace Any in _item_to_dict and _enrich_items_bulk with InventoryItem | dict.

Specify session: Session (SQLAlchemy) instead of Any.