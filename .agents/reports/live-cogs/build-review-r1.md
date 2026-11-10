## High

1. Reconciliation surplus duplicates configured percentage shares — wrong allocations  
   [engine.py:576](/home/johnny/wt-live-cogs/app/features/costing/engine.py:576), [execution_routes.py:1253](/home/johnny/wt-live-cogs/app/core/backend/execution_routes.py:1253)

   A reconciled output with surplus creates two flows carrying the same `source_output_id`: one `reconciled_in` and one `produced`. `_split_weights` applies the definition’s percentage independently to both flows.

   Concrete scenario: a $100 pool has output A configured at 30%, producing 8 L: 4 L reconciled and 4 L surplus; output B is an unconfigured 2 L output. The engine sees percentages `30 + 30`, gives A $60 and B $40. Expected is A $30, divided $15/$15 between its two flows, and B $70.

   Fix: group flows by logical output definition before applying `cost_share`; assign the definition one weight, then apportion that weight among its reconciled/surplus flows by quantity. Unresolved outputs need a separate per-logical-output identity.

2. The 20,000-node guard cannot protect deep graphs; Python recursion fails first  
   [engine.py:282](/home/johnny/wt-live-cogs/app/features/costing/engine.py:282), [engine.py:316](/home/johnny/wt-live-cogs/app/features/costing/engine.py:316), [engine.py:426](/home/johnny/wt-live-cogs/app/features/costing/engine.py:426)

   Lot/execution traversal is recursive. A chain of roughly hundreds to 1,000 production or transfer dependencies raises `RecursionError` and returns 500, long before `_nodes` reaches 20,000. The contract requires graphs through 20,000 nodes to return normally and larger graphs to return `unknown` with `too_large`.

   Fix: use an explicit traversal stack/state machine, retaining visiting and memo states. Catching `RecursionError` would prevent the 500 but would still violate the supported 20,000-node limit.

3. Duplicate reconciliation keys silently discard real stock movements  
   [flows.py:53](/home/johnny/wt-live-cogs/app/features/costing/flows.py:53), [flows.py:79](/home/johnny/wt-live-cogs/app/features/costing/flows.py:79), [flows.py:171](/home/johnny/wt-live-cogs/app/features/costing/flows.py:171)

   Every insert uses `ON CONFLICT DO NOTHING`, and callers ignore `False`. Two actual-output rows in one completion that reconcile the same output definition/name into the same untracked lot receive the same key.

   Concrete scenario: two 3 L `"Gin"` output rows reconcile into the same 10 L untracked lot. Core reduces the lot by 6 L, but only the first 3 L `reconciled_in` flow is stored. Costing therefore allocates cost to 3 L instead of 6 L. Long unresolved output names can also collide after `source_key[:200]`.

   Fix: reject duplicate logical reconciliation targets before mutating inventory, or aggregate them and write one summed flow. A conflict during a live write must be distinguished from an idempotent replay and must not silently succeed.

4. `execution_step_id` is not tenant-composite and need not belong to `execution_id`  
   [models.py:49](/home/johnny/wt-live-cogs/app/features/costing/models.py:49), [models.py:76](/home/johnny/wt-live-cogs/app/features/costing/models.py:76), [costing_engine_001.py:35](/home/johnny/wt-live-cogs/app/core/db/migrations/versions/costing_engine_001.py:35)

   `execution_id` uses a composite tenant FK, but `execution_step_id` is a scalar FK. The database accepts a flow with org A’s lot and execution but org B’s step, or a different step in org A. Deleting the unrelated step cascades and deletes org A’s flow. The engine then cannot associate the flow with any loaded step and may report an output as unallocated.

   Fix: add the required `(org_id, id)` uniqueness to `execution_steps`, use `(org_id, execution_step_id)` as the FK, and enforce that the step belongs to the supplied execution—ideally with a composite `(org_id, execution_id, execution_step_id)` reference.

## Medium

5. Valid directly priced “mixed” lots cannot supply last-known estimates  
   [engine.py:399](/home/johnny/wt-live-cogs/app/features/costing/engine.py:399), [engine.py:413](/home/johnny/wt-live-cogs/app/features/costing/engine.py:413)

   Estimate candidates must be directly priced and `actual`. The additional source-name test incorrectly rejects actual lots whose direct inflows have more than one price source.

   Concrete scenario: a 5 kg direct lot has 2 kg manually priced at $20 and a 3 kg added flow marked free. Its cost is actual at $4/kg with source `mixed`. An unpriced later lot of the same material is reported `unknown`; expected is `estimated` at $4/kg.

   Fix: after `_is_direct`, accept any `actual` result with a non-null unit cost. Do not filter on presentation-level `source`.

6. Inconsistent execution provenance now causes 500s or corrupt flows  
   [inventory_repo.py:165](/home/johnny/wt-live-cogs/app/core/db/repositories/inventory_repo.py:165), [flows.py:111](/home/johnny/wt-live-cogs/app/features/costing/flows.py:111)

   Repository validation checks execution and step ownership independently but does not require both or verify that the step belongs to the execution.

   Concrete scenarios:

   - Creating inventory with a valid `source_execution_step_id` but no `source_execution_id` passes validation, then the new flow violates `ck_cost_flows_execution_kinds`, turning an accepted inventory input into a 500.
   - Supplying execution A and a step from execution B in the same org stores a flow under execution A but step B; the engine ignores it when processing A.

   Fix: validate the pair before inserting the inventory item. Derive the execution from the step or require matching IDs, and return 400 before any stock/event work.

7. Concurrent first settings writes can return a uniqueness 500  
   [service.py:204](/home/johnny/wt-live-cogs/app/features/costing/service.py:204)

   `SELECT ... FOR UPDATE` locks nothing when the org has no settings row. Two simultaneous first `PUT /settings` requests can both see no row and insert; one then fails `uq_costing_settings_org`.

   Expected: both valid PUTs complete, with a defined last-writer result. Fix with `INSERT ... ON CONFLICT (org_id) DO UPDATE`, or lock the organisation row before selecting/creating settings.

8. The migration is not reversibly downgradeable once anyone records a price  
   [costing_engine_001.py:129](/home/johnny/wt-live-cogs/app/core/db/migrations/versions/costing_engine_001.py:129)

   A single `lot_cost_entries` row makes downgrade raise `RuntimeError`. Thus an emergency rollback after feature use cannot execute, contrary to the contract’s additive-and-reversible requirement.

   Fix: remove the data-dependent refusal and drop only the newly introduced tables during downgrade, as specified. If preserving data is operationally required, export it separately rather than making the Alembic downgrade non-reversible.

## Low

9. Backfill has an avoidable N+1 query and one non-org-filtered lookup  
   [backfill.py:106](/home/johnny/wt-live-cogs/app/features/costing/backfill.py:106), [backfill.py:114](/home/johnny/wt-live-cogs/app/features/costing/backfill.py:114)

   Every produced lot issues a separate `ExecutionStep` lookup, and that lookup filters only by ID. A 10,000-lot history can issue roughly 10,000 extra queries. With malformed legacy cross-org provenance, it can read another organisation’s step number.

   Fix: collect relevant step IDs and load their `(id, step_number)` values once with `ExecutionStep.org_id == org_id`.

10. `costing_settings` omits the required `(org_id, id)` unique constraint  
    [models.py:137](/home/johnny/wt-live-cogs/app/features/costing/models.py:137), [costing_engine_001.py:118](/home/johnny/wt-live-cogs/app/core/db/migrations/versions/costing_engine_001.py:118)

    The table has uniqueness on `org_id` but not the contractually required `UniqueConstraint(org_id, id)` shared by all new tenant tables. Org uniqueness makes duplicate pairs impossible today, but the table cannot serve as a tenant-composite FK target consistently with the model contract.

    Fix: add the named `(org_id, id)` unique constraint to both migration and model, retaining the one-row-per-org constraint.

VERDICT: fail
