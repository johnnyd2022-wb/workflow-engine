## Round-1 findings

1. **Resolved — insufficient scope classification.**  
   `xero_sync_service.py:594-595` directly handles `XeroInsufficientScopeError` as `needs_reconnect`; regression at `tests/test_costing_purchases.py:891-898`.

2. **Resolved — voided/deleted documents retain lines.**  
   `purchase_sources.py:342-374` skips line reconciliation for stored voids and ignores unseen voids. Both statuses are covered at `tests/test_costing_purchases.py:901-919`.

3. **Resolved — purchase-phase token expiry finalizes the job.**  
   `xero_sync_service.py:596-599` records the failure instead of rethrowing; regression at `tests/test_costing_purchases.py:922-931`.

4. **Resolved — activation-anchor mid-sync commit.**  
   The anchor is now written with the new job before sales work at `xero_sync_service.py:87-89` and `160-162`. `_anchor_purchases` itself does not commit. Its settings-row lock is released by that immediate commit, and concurrent purchase phases subsequently serialize through the same row. A separate job-lifecycle regression remains below.

5. **Resolved — every phase failing no longer becomes partial.**  
   `SyncResult.partial` at `xero_sync_service.py:50-58` requires a successfully completed sales phase when purchases fail. Tests distinguish all-failed from successful zero-row sales at `tests/test_costing_purchases.py:945-964`. This does not otherwise alter legacy count-based CRM partial semantics.

6. **Partially resolved — missing monetary values.**  
   Lines now preserve missing values at `purchase_sources.py:310-323`, but document tax totals still convert a missing tax amount to zero at line 422. See finding 3 below.

7. **Partially resolved — accounts ceasing to be expenses.**  
   `retire_account_lines` was added, but its caller fails when the account has a treatment override. See finding 2 below.

8. **Resolved — unit-amount precision.**  
   Model and migration use `NUMERIC(18,6)`; regression at `tests/test_costing_purchases.py:997-1003`.

9. **Partially resolved — independently falsifiable acceptance tests.**  
   The new tests cover individual keywords, adversarial `NoTax`, positional history, LineItemID movement/recode, cross-org mutation, cursor arithmetic/counting, and foreign nulls. The requested downgrade-refusal test is still absent.

## Remaining findings

1. **High — a full-sync sales token expiry leaves a durable job permanently `running`.**  
   `app/features/crm/services/xero_sync_service.py:87-104` (also lines 123-124 and 137-138)

   Failing scenario: the job and anchor are committed at lines 87-89, then fetching contacts, invoices, or credit notes raises `XeroTokenExpiredError`. Full sync rethrows immediately, bypassing `_record_purchases` and `_finalise_job`. The route can return the intended reconnect response, but the committed job remains `running` without `completed_at` or a completion event. Before the new early commit, that job was not durable.

   Fix: catch sales-phase token expiry at the full-sync orchestration boundary, mark and commit the job as failed, then rethrow to preserve the existing HTTP reconnect behavior. Add coverage for expiry in each full-sync sales phase.

2. **Medium — a treatment override prevents retirement when an account stops being an expense.**  
   `app/features/costing/purchase_sources.py:119-126`

   Failing scenario: a user overrides an expense account to `stock`; later Xero changes it to `ASSET`, with no affected transaction in the incremental feed. Because `row.treatment` returns the override, it remains non-null and the code calls `reclassify_account_lines` instead of `retire_account_lines`. The stale purchase lines remain live even though their account is no longer eligible. The regression at lines 983-995 uses no override.

   Fix: decide retirement from expense eligibility—such as `row.account_class != "EXPENSE"` or `row.default_treatment is None`—independently of `treatment_override`. Preserve the override for history/future eligibility, but retire all current live lines. Add the override-plus-account-class transition test.

3. **Medium — a missing tax amount can still produce a false zero document tax total.**  
   `app/features/costing/purchase_sources.py:409-422`

   Failing scenario: an `Exclusive` base-currency line has a valid `LineAmount` but a missing or malformed `TaxAmount`. The line correctly stores `tax_amount=None`, yet line 422 uses `r[1] or Decimal("0")`, producing `total_tax=0`. This violates the contract that totals remain null when a live line amount is unknown.

   Fix: if any live line has either `amount_ex_tax is None` or `tax_amount is None`, leave both document totals null. `NoTax` remains unaffected because it explicitly stores tax zero. Add an `Exclusive`, valid-line/missing-tax regression.

The void early-continue and settings-row locking showed no additional HIGH/MEDIUM defect. Focused Ruff checks passed; pytest could not start because the read-only environment exposed no writable temporary directory.

VERDICT: fail
