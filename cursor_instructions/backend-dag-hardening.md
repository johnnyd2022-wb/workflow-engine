Cursor Prompt: Backend Review & Hardening

Review the provided DAG execution and inventory-population code with the following goals:

1. Transaction integrity

Reduce or eliminate db_session.commit() calls inside loops.

Ensure inventory consumption and output creation are atomic per execution step.

Prefer a single commit per logical phase or per execution step.

2. Failure handling semantics

Identify places where warnings currently allow execution to continue.

Explicitly decide which failures should:

Block step execution

Be captured as execution warnings

Persist structured warnings/errors into execution_step.execution_data where appropriate.

3. extra_data discipline

Clearly separate source execution data from derived data.

Treat previous_steps_data as derived/read-only and ensure it is never persisted unintentionally.

Document and enforce a consistent soft schema for extra_data.

4. DAG traversal performance

Flag recursive DAG walking inside list_inventory() as a scalability risk.

Propose a cleaner separation between:

Inventory listing

Traceability / provenance traversal

5. Quantity precision

Identify float usage and recommend safer handling (e.g. Decimal).

Ensure quantity formatting remains audit-safe and deterministic.

6. Maintain mental-model alignment

Ensure the backend continues to reinforce these concepts:

Variable inputs = inventory consumption

Variable outputs = inventory creation

Execution prompts = metadata captured at execution time
These must remain distinct and traceable through the DAG.

Make minimal but high-impact changes. Prefer clarity, determinism, and auditability over cleverness.