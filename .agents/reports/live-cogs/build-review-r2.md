## Round-one verification

| # | Status | Evidence |
|---|---|---|
| 1 | Partially resolved | Configured reconciled/surplus flows are grouped and tested at [engine.py:689](/home/johnny/wt-live-cogs/app/features/costing/engine.py:689) and [test_costing_engine.py:874](/home/johnny/wt-live-cogs/tests/test_costing_engine.py:874), but unresolved outputs are grouped incorrectly; finding below. |
| 2 | Resolved | Explicit stack at [engine.py:248](/home/johnny/wt-live-cogs/app/features/costing/engine.py:248); deep-chain regression at [test_costing_engine.py:910](/home/johnny/wt-live-cogs/tests/test_costing_engine.py:910). |
| 3 | Resolved | Row-position reconciliation keys and live conflict refusal at [flows.py:53](/home/johnny/wt-live-cogs/app/features/costing/flows.py:53) and [flows.py:108](/home/johnny/wt-live-cogs/app/features/costing/flows.py:108); regression at [test_costing_engine.py:960](/home/johnny/wt-live-cogs/tests/test_costing_engine.py:960). |
| 4 | Partially resolved | Deployed migration has the composite FK, and mismatch regression exists at [test_costing_engine.py:1009](/home/johnny/wt-live-cogs/tests/test_costing_engine.py:1009), but the ORM target constraint and required-field checks remain incomplete; finding below. |
| 5 | Resolved | Estimate selection now accepts any direct actual cost at [engine.py:541](/home/johnny/wt-live-cogs/app/features/costing/engine.py:541); mixed-source regression at [test_costing_engine.py:990](/home/johnny/wt-live-cogs/tests/test_costing_engine.py:990). |
| 6 | Resolved | Repository validates the execution/step pair at [inventory_repo.py:175](/home/johnny/wt-live-cogs/app/core/db/repositories/inventory_repo.py:175); covered by the combined #4/#6 regression. |
| 7 | Partially resolved | Atomic PostgreSQL upsert at [service.py:216](/home/johnny/wt-live-cogs/app/features/costing/service.py:216), but no concurrent-first-write regression exists. |
| 8 | Not resolved by design; accepted | I agree with the refusal. Typed prices are irreplaceable user data, and v4 explicitly adopts the repository’s data-preserving downgrade convention. |
| 9 | Partially resolved | Backfill now bulk-loads org-filtered step numbers at [backfill.py:106](/home/johnny/wt-live-cogs/app/features/costing/backfill.py:106), but no query-count or cross-org legacy regression exists. |
| 10 | Partially resolved | Both model and migration now declare `(org_id, id)` at [models.py:151](/home/johnny/wt-live-cogs/app/features/costing/models.py:151), but there is no constraint regression. |

## Medium

1. Unresolved same-name outputs are incorrectly merged into one logical output  
   [engine.py:689](/home/johnny/wt-live-cogs/app/features/costing/engine.py:689), [engine.py:749](/home/johnny/wt-live-cogs/app/features/costing/engine.py:749)

   Null-identity flows are grouped by normalized destination name. Consider a $100 pool with unresolved outputs `"Blend" 1 L`, `"Blend" 100 kg`, and `"Other" 1 unit`. Because units are incompatible, the contract’s primary fallback should allocate all $100 to the single primary flow—`Blend 100 kg`. The engine instead selects the combined `"Blend"` group, then splits it by raw quantities, allocating about $0.99 and $99.01 across the incompatible Blend flows.

   Fix: assign a logical-output identity at completion, shared only by the reconciled and surplus flows originating from the same actual-output row. Do not infer that identity from name. Add an incompatible, null-identity regression alongside the configured-share test.

2. The 20,000-node guard counts steps, contrary to the contract’s lots-plus-executions budget  
   [engine.py:208](/home/johnny/wt-live-cogs/app/features/costing/engine.py:208), [engine.py:257](/home/johnny/wt-live-cogs/app/features/costing/engine.py:257)

   One execution containing 20,000 steps and one consumed lot is only two contract nodes—one execution and one lot—but `_nodes` counts 20,001 step/lot state-machine nodes and returns `unknown/too_large`. The existing limit regression proves only that a deliberately tiny implementation counter fires; it does not verify the contractual unit of accounting.

   Fix: charge the budget once per execution ID and once per lot ID while retaining step nodes internally, or amend the contract explicitly. Add a multi-step execution regression that stays below the lots-plus-executions limit.

3. Execution-backed flows can still omit their step, and ORM metadata lacks the referenced uniqueness  
   [models.py:55](/home/johnny/wt-live-cogs/app/features/costing/models.py:55), [models.py:62](/home/johnny/wt-live-cogs/app/features/costing/models.py:62), [execution_step.py:33](/home/johnny/wt-live-cogs/app/core/db/models/execution_step.py:33)

   PostgreSQL’s default composite-FK matching ignores the FK when `execution_step_id` is null. A `produced` flow with a valid `execution_id` but null `execution_step_id` therefore passes all current checks, then the engine reports its lot as `unallocated_output`. Separately, the migration creates `uq_execution_steps_org_execution_id`, but `ExecutionStep.__table__` does not declare it, leaving migration and ORM metadata inconsistent.

   Fix: require `execution_id`, `execution_step_id`, and `step_number` for `produced`, `reconciled_in`, and `consumed` rows; declare the target composite unique constraint on `ExecutionStep`; add regressions for missing execution fields and metadata/schema parity.

The database-backed suite could not execute because the configured test host `host.docker.internal` was not resolvable in this environment.

VERDICT: fail
