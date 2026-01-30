Potential Risks / Gaps Before Production

Memory Usage on Large DAGs

Bulk-loading items and enrichment may be heavy on large graphs.

Could cause latency spikes or OOM if thousands of nodes are traversed.

Quantity Filtering Edge Cases

Currently skips invalid quantities silently (logged).

If downstream consumers expect strict validation, skipped nodes may lead to incomplete traces.

Step-Order Connections

add_step_order_connections relies on step numbers and inputs.

Duplicate step_number warnings logged; need to monitor in production to ensure data quality.

Backward Traversal Performance

Loads all potentially reachable items in memory.

For dense DAGs, could be slow; may need indexing or batch query optimization.

Logging Volume

Traversals that filter many nodes/edges may produce frequent warnings.

Could impact log aggregation costs or flood alerting if high-frequency traversals occur.

No Strict Cycle Detection

DAG assumed, but corrupted data with cycles could cause infinite loops (DFS/BFS stops only on visited set, seems safe, but worth stress test).

🔹 Recommended Next Steps Before Production

Testing

Unit tests for:

Forward/backward traversal

Multiple roots

Stop conditions

Zero/invalid quantity handling

Expired raw material scenarios

Step-order edge additions

Integration tests against realistic inventory DAGs (including edge cases, large graphs).

Monitoring & Logging

Add metrics for traversal counts, average duration, node/edge counts.

Evaluate if in-process rate-limiting for warnings is needed.

Performance Validation

Test memory and CPU usage with large DAGs.

Possibly consider generator-based enrichment if memory pressure observed.

Optional Features

Strict quantity mode (strict_quantity=True) if needed by consumers.

Full result memoization if repeated queries are common.

Consider ORM/schema UTC normalization if other services rely on consistent datetime storage.