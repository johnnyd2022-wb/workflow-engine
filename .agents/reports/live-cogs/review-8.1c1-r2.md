## Remaining HIGH/MEDIUM findings

1. **HIGH — account reclassification/retirement still races with recording.**  
   [purchase_sources.py:130](/home/johnny/wt-live-cogs-alloc/app/features/costing/purchase_sources.py:130), [purchase_sources.py:152](/home/johnny/wt-live-cogs-alloc/app/features/costing/purchase_sources.py:152)

   Failing scenario: `record` locks document→line and begins creating an allocation. Concurrent `retire_account_lines()` or `reclassify_account_lines()` reads the unlocked line and sees no allocation. Its final update waits for `record`, then supersedes/recodes the line without orphaning or setting review. The result is an active allocation on a superseded or recoded line.

   Fix: make both account paths acquire affected documents and lines using the same deterministic document→line order before inspecting allocations or changing treatment/supersession. Add concurrent record-vs-retire and record-vs-reclassify tests.

2. **HIGH — document restore revives allocations orphaned for unrelated reasons.**  
   [actions.py:670](/home/johnny/wt-live-cogs-alloc/app/features/costing/actions.py:670), [actions.py:719](/home/johnny/wt-live-cogs-alloc/app/features/costing/actions.py:719), [purchase_sources.py:400](/home/johnny/wt-live-cogs-alloc/app/features/costing/purchase_sources.py:400)

   Failing scenario: record a valued line, change it to foreign-currency `needs_rate` so the allocation becomes `orphaned/amount_changed`, void the document, then restore it while it still needs a rate. Voiding overwrites the reason to `deleted_in_xero`; restoration activates every orphan and clears review before the incoming line is applied. Since old and new amounts are both null, amount-change handling returns early. The stale allocation finishes active and is priced as actual on a needs-rate purchase.

   Fix: preserve why each allocation was orphaned and restore only allocations orphaned by that document’s void transition. Apply restoration after incoming line values and supersession are reconciled. Add needs-rate→void→active and sign-change→void→active regressions.

3. **MEDIUM — multi-allocation rescaling can produce a negative positive allocation and abort sync.**  
   [actions.py:697](/home/johnny/wt-live-cogs-alloc/app/features/costing/actions.py:697), [models.py:299](/home/johnny/wt-live-cogs-alloc/app/features/costing/models.py:299)

   Failing scenario: four positive allocations of `$0.0001` on a `$0.0004` line rescaled to `$0.0002`. Each independently rounds to `$0.0001`; the `-$0.0002` remainder is assigned to one allocation, making it `-$0.0001`. That violates `ck_purchase_allocations_shape`, so the sync fails instead of rescaling.

   Fix: distribute negative rounding remainder without taking any positive allocation below zero, deterministically, while preserving the exact target total. Add a four-minimum-allocation downscale regression.

4. **MEDIUM — a zero-dollar line cannot be marked not-stock.**  
   [actions.py:128](/home/johnny/wt-live-cogs-alloc/app/features/costing/actions.py:128), [actions.py:434](/home/johnny/wt-live-cogs-alloc/app/features/costing/actions.py:434)

   Failing scenario: POST `not-stock` on an open `$0` line adds zero and `derive_state()` deliberately excludes `amount == 0`, leaving the line `open` in To record indefinitely. The contract says `not_stock` when `not_stock_amount == amount`.

   Fix: preserve the explicit not-stock decision for zero-value lines without making `reopen` immediately derive back to not-stock. Add zero-line not-stock/reopen coverage.

## Round-1 findings

1. **Resolved.** [actions.py:678](/home/johnny/wt-live-cogs-alloc/app/features/costing/actions.py:678) now orphans valued allocations when the new amount is null. Regression: `test_r1_recorded_line_turning_needs_rate_is_orphaned_for_review`.

2. **Partially resolved.** [actions.py:697](/home/johnny/wt-live-cogs-alloc/app/features/costing/actions.py:697) fixes the reported one-allocation/not-stock overage, but the multi-allocation negative-remainder failure above remains.

3. **Partially resolved.** [actions.py:719](/home/johnny/wt-live-cogs-alloc/app/features/costing/actions.py:719) restores the simple void→active cases, including review-keep, but indiscriminately restores allocations orphaned before the void.

4. **Resolved for the reported void race.** [actions.py:57](/home/johnny/wt-live-cogs-alloc/app/features/costing/actions.py:57) and [purchase_sources.py:289](/home/johnny/wt-live-cogs-alloc/app/features/costing/purchase_sources.py:289) use document→line ordering; lots are sorted at [actions.py:286](/home/johnny/wt-live-cogs-alloc/app/features/costing/actions.py:286). The separate account-transition race remains as finding 1.

5. **Resolved.** [engine.py:460](/home/johnny/wt-live-cogs-alloc/app/features/costing/engine.py:460) propagates orphaned-refund status as estimated. Regression coverage exists at line 1131.

6. **Resolved.** [actions.py:480](/home/johnny/wt-live-cogs-alloc/app/features/costing/actions.py:480) locks lots deterministically and does not reactivate allocations belonging to voided or superseded purchases.

7. **Resolved.** [actions.py:286](/home/johnny/wt-live-cogs-alloc/app/features/costing/actions.py:286) rejects duplicate lot IDs and locks unique lots in sorted UUID order for links and refunds.

8. **Resolved.** [actions.py:114](/home/johnny/wt-live-cogs-alloc/app/features/costing/actions.py:114) derives allocation presence from rows rather than the amount sum. Regression coverage exists at line 1174.

9. **Resolved.** [routes.py:244](/home/johnny/wt-live-cogs-alloc/app/features/costing/routes.py:244) gives every simple POST action a distinct idempotency scope.

10. **Resolved.** [actions.py:460](/home/johnny/wt-live-cogs-alloc/app/features/costing/actions.py:460) explicitly rejects review on null-amount lines, with a meaningful regression setup.

11. **Resolved.** [actions.py:388](/home/johnny/wt-live-cogs-alloc/app/features/costing/actions.py:388) delegates refund magnitude validation to the bounded four-decimal parser.

Static Ruff checks passed and `git diff --check` was clean. Pytest could not start because the enforced read-only environment provides no writable temporary directory; the worktree remained unchanged. No MR pipeline was monitored.

VERDICT: fail
