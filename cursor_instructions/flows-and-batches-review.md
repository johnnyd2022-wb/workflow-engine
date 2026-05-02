🔴 CRITICAL FINDINGS
1. ⚠️ Residual hidden N+1 risk via _split_execution_data + step_outputs dependency chain
What’s improved
ExecutionStep hydration is now batched ✔
joinedload(ExecutionStep.step) ✔
ready-date per-item query removed ✔
Remaining risk

Inside:

step_outputs = getattr(es.step, "outputs", None) or []

You are now relying on ORM-loaded relationship completeness.

Why this is still critical

Even with joinedload, you now have a dependency chain:

ExecutionStep → step → outputs

If outputs is:

lazy-loaded relationship
or secondary join not included in options

👉 you silently reintroduce per-row lazy load

Impact

Under realistic inventory sizes:

200 items → potentially 200 additional SELECTs (silent regression)
Fix

You must explicitly guarantee full eager graph:

.options(
    joinedload(ExecutionStep.step)
    .joinedload(Step.outputs)
)

If outputs is JSON, this is fine — but if ORM relationship, this is still a latent N+1.

2. ⚠️ CRITICAL — Transaction safety still not fully resolved

You acknowledged this was deferred, but current system still has:

multiple manual exception branches
partial logic execution before rollback points
hydration + side-effect logic inside same function
Why this still matters

Even with batching fixed, this pattern is still dangerous:

execution_step = repo.complete_step(..., commit=False)
db_session.flush()
...
if execution_errors:
    db_session.rollback()
Problem class

This is still a partial commit window architecture, meaning:

flush occurs before validation completes
rollback does not guarantee undo of external side effects (inventory creation, etc.)
logic is not truly atomic
Production risk
double-write scenarios under concurrency
phantom inventory items
inconsistent audit trail between execution + inventory
Correct model (still required)

You want:

with db_session.begin():
    repo.complete_step(...)
    validate(...)
    create_inventory(...)

Anything else is still logically unsafe under failure injection.

3. ⚠️ HIGH — Trust boundary comment is still partially incorrect in security model terms

You wrote:

spoofing risk is about who may write execution_data, not about splitting for read APIs

This is directionally correct but incomplete
Real issue class

Even if completed_by_email is set server-side in normal flow:

You still allow:

execution_data persistence from multiple code paths
replay or rehydration into audit layer
trace reconstruction assumes integrity of stored JSON
Key gap

Nothing enforces:

“execution_data is server-owned after persistence”

So the risk is not just write path, it's:

future service changes
backfills
admin tools
migrations
Recommendation (important)

Add invariant at persistence boundary:

schema validation OR
overwrite protection OR
field whitelist at DB layer write

Otherwise audit integrity is “best effort”, not enforced.

🟠 HIGH FINDINGS
4. ⚠️ Performance: batch query still has hidden inefficiency
.join(Execution, ExecutionStep.execution_id == Execution.id)
Issue

You are now doing:

batch IN query
plus join to Execution for org scoping

But ExecutionStep already has org context via ExecutionStep.execution_id → Execution

Risk

This join can:

block index-only scan paths
degrade planner choice depending on DB (Postgres especially)
Better pattern

Prefer one of:

pre-filter ExecutionStep IDs via subquery on Execution
or denormalise org_id into ExecutionStep (common SaaS optimisation)
5. ⚠️ MEDIUM — Exception handling still masks structural errors

You improved logging:

logger.debug(..., exc_info=True)

Good improvement, but:

Issue

You still swallow exceptions in:

producing_step fallback (still pass)
outer inventory loops (partial visibility only)
Risk
silent data drift
missing production alerts
hard-to-reproduce UI inconsistencies
Recommendation

At minimum:

emit structured metrics (inventory_hydration_failure_count)
or escalate unexpected exceptions to warning level
6. ⚠️ MEDIUM — execution_step_by_id memory scaling risk
execution_step_by_id = {es.id: es for es in loaded_steps}
Issue

Fine for typical loads, but:

inventory endpoint = potentially large fanout
step graph may include heavy relationships (step.outputs, execution_data)
Risk

Memory bloat in:

large tenants
batch exports
admin views
Mitigation

If this endpoint grows further:

consider paginated hydration
or selective column load (load_only)
🟡 LOW / STRUCTURAL NOTES
7. Better: execution_step reuse is correct and clean

This is a strong improvement:

src_step = execution_step_by_id.get(...)

✔ removes per-row DB access
✔ improves cache locality
✔ reduces DB pressure significantly

This is now aligned with proper data-assembly architecture.

8. Small inconsistency risk: ready-date fallback contract widened

You added:

dict | str | None
Benefit

More flexible ingestion

Risk
silent misparsing if invalid string formats creep in
inconsistent timezone interpretation across inputs
Recommendation

If this field is externally writable:

enforce ISO-8601 only
reject ambiguous formats early

---

## Resolution notes (implementation tracking)

| # | Finding | Action |
|---|---------|--------|
| **1** | `ExecutionStep → step → outputs` lazy N+1 | **No ORM chain:** `steps.outputs` is **JSONB** on `Step`, not a relationship. Loading `Step` loads `outputs` with the row. Documented in code next to batch query. No `joinedload(Step.outputs)` needed. |
| **2** | Transaction safety / `flush` + manual `rollback` | **Deferred** — tracked in `cursor_instructions/complete-step-transaction-refactor-plan.md`. Requires dedicated refactor + integration tests. |
| **3** | Trust boundary / server-owned `execution_data` | **`_strip_incoming_execution_trace_keys`** removes all `_EXECUTION_DATA_TRACE_KEYS` from the client payload before `complete_step`; server then sets identity and later warnings/errors. |
| **4** | Batch query `JOIN Execution` | Replaced with **`execution_id IN (SELECT executions.id WHERE org_id = …)`** — avoids join in outer query; keeps org isolation. |
| **5** | Swallowed exceptions | **`list_inventory`:** hydrate + ready-date + producing-step failures log at **`warning`** with `exc_info` (was `debug` / silent). Metrics (`inventory_hydration_failure_count`) still optional for a later observability pass. |
| **6** | `execution_step_by_id` memory | **Documented only** in batch-query comment; pagination / `load_only` remains a future endpoint-scale change. |
| **7** | (positive) | Acknowledged — kept as-is. |
| **8** | `ready_date_actual` string formats | **Debug log** when a non-empty string fails to parse (truncated), so silent bad strings are visible in logs; persistence contract remains ISO-oriented via `_normalize_dt`. |