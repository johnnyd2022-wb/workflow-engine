## Findings

1. **High — Real insufficient-scope responses become `failed`, not `needs_reconnect`.**  
   [xero_api_client.py:112](</home/johnny/wt-live-cogs-xero/app/features/crm/services/xero_api_client.py:112>), [xero_sync_service.py:591](</home/johnny/wt-live-cogs-xero/app/features/crm/services/xero_sync_service.py:591>), [test_costing_purchases.py:514](</home/johnny/wt-live-cogs-xero/tests/test_costing_purchases.py:514>)  
   Scenario: `_call_with_retry` recognizes Xero’s raw `insufficient_scope` response and replaces it with `XeroInsufficientScopeError("The Xero connection does not allow this change…")`. `_run_purchases` then calls `_is_insufficient_scope` on the replacement, whose text and attributes no longer contain `insufficient_scope`; the job gets an error and `purchases_status="failed"` instead of a successful completed job with `needs_reconnect`. The test bypasses `_call_with_retry` and manually teaches the classifier about its custom raw exception, so it cannot expose this production path.  
   Fix: explicitly catch `XeroInsufficientScopeError` in `_run_purchases` and set `needs_reconnect` without adding an error. Add an integration-shaped unit test in which `_call_with_retry` performs the translation.

2. **High — A voided/deleted transaction can supersede all its lines, contradicting “lines kept” and endangering 8.1c allocations.**  
   [purchase_sources.py:342](</home/johnny/wt-live-cogs-xero/app/features/costing/purchase_sources.py:342>), [purchase_sources.py:370](</home/johnny/wt-live-cogs-xero/app/features/costing/purchase_sources.py:370>), [test_costing_purchases.py:406](</home/johnny/wt-live-cogs-xero/tests/test_costing_purchases.py:406>)  
   Scenario: Xero returns a `DELETED` or `VOIDED` transaction with an empty or reduced `line_items` collection. The implementation sets the document to `voided`, but then marks every absent live line `superseded_at`. In 8.1c that would move allocations onto superseded rows rather than preserving the voided document’s lines for deleted-in-Xero handling. The test resends the original line, so it remains green if the broken absence handling stays.  
   Fix: for an already-stored voided/deleted document, update the header status while retaining its existing live lines regardless of the response’s line collection. Add tests for both `DELETED` and `VOIDED` with `line_items=[]`.

3. **High — `XeroTokenExpiredError` escapes before job finalization.**  
   [xero_sync_service.py:589](</home/johnny/wt-live-cogs-xero/app/features/crm/services/xero_sync_service.py:589>), [xero_sync_service.py:137](</home/johnny/wt-live-cogs-xero/app/features/crm/services/xero_sync_service.py:137>), [xero_sync_service.py:213](</home/johnny/wt-live-cogs-xero/app/features/crm/services/xero_sync_service.py:213>)  
   Scenario: organisation, accounts, or bank-transaction fetching raises `XeroTokenExpiredError`. `_run_purchases` rethrows, so `_record_purchases` and `_finalise_job` never execute. The sync job remains pending/running, has no purchases status, and successful sales work may already be committed by line 557. This violates the contract’s “job is finalised once” and “any other failure” behavior.  
   Fix: translate this purchase-phase failure into an explicit purchases outcome and always run finalization, while preserving reconnect signaling to the route separately if required. Add tests asserting the final job state, purchases fields, sales cursor, and committed sales data.

4. **High — The activation-anchor commit also commits all pending sales work, on every run.**  
   [xero_sync_service.py:554](</home/johnny/wt-live-cogs-xero/app/features/crm/services/xero_sync_service.py:554>)  
   Scenario: contacts/invoices/credit notes mutate the session, then `_run_purchases` calls `commit()` even when `start_date` already exists. If purchases or final job/event persistence subsequently aborts, sales rows are already durable while the job can remain unfinished and its intended final commit never happened. The comment says the start date is committed independently, but it is sharing the sales transaction. No test induces failure after this commit and before finalization.  
   Fix: initialize and persist `start_date` in an isolated unit of work before the sales phases, or otherwise ensure only that setting is committed. At minimum, do not commit when the anchor already exists. Test a finalization failure on both first and later syncs.

5. **Medium — A sync where every phase fails is incorrectly marked `partial`.**  
   [xero_sync_service.py:48](</home/johnny/wt-live-cogs-xero/app/features/crm/services/xero_sync_service.py:48>), [test_costing_purchases.py:534](</home/johnny/wt-live-cogs-xero/tests/test_costing_purchases.py:534>)  
   Scenario: contacts, invoices, and credit-note fetches all fail before processing anything, and purchases also fails. `purchases_status == "failed"` alone makes `result.partial` true, despite no successful phase or retained result. The job is marked partial rather than failed. The existing test only covers successful zero-row sales phases followed by purchase failure, so it cannot distinguish these cases.  
   Fix: track per-phase completion independently of row counts. Define partial as at least one phase completing successfully or retaining results while another fails.

6. **Medium — Missing or invalid base-currency amounts are silently converted to zero.**  
   [purchase_sources.py:288](</home/johnny/wt-live-cogs-xero/app/features/costing/purchase_sources.py:288>)  
   Scenario: a base-currency line has `line_amount=None`, an invalid decimal, or an inclusive line has an unavailable tax amount. `_dec(...) or Decimal("0")` stores a zero purchase and allows zero totals, despite the contract requiring totals to be null when a live line’s amount is null. This can silently underprice stock.  
   Fix: preserve an unavailable `line_amount` as `None`; propagate `None` through ex-tax calculation and totals. For `Inclusive`, unavailable tax must also prevent an ex-tax value. Reserve zero for an explicit numeric zero or the specified `NoTax` case. Add malformed/missing-value tests.

7. **Medium — Accounts that cease to be expenses leave stale live purchase lines.**  
   [purchase_sources.py:119](</home/johnny/wt-live-cogs-xero/app/features/costing/purchase_sources.py:119>), [purchase_sources.py:127](</home/johnny/wt-live-cogs-xero/app/features/costing/purchase_sources.py:127>)  
   Scenario: an account changes from `EXPENSE` to a balance-sheet class, but its bank transaction is not included in the incremental response. `default_treatment` becomes null, then `reclassify_account_lines` returns immediately, leaving its old lines live and stock-classified indefinitely. That contradicts the requirement that only expense-account lines are stored and will mislead 8.1c.  
   Fix: explicitly reconcile live lines when an account becomes ineligible—supersede them in 8.1b, through the same future deleted/recoded transition seam needed by 8.1c. Add an account-only incremental-change test.

8. **Medium — `source_unit_amount` loses the contracted “as sent” precision.**  
   [models.py:244](</home/johnny/wt-live-cogs-xero/app/features/costing/models.py:244>), [costing_purchases_001.py:94](</home/johnny/wt-live-cogs-xero/app/core/db/migrations/versions/costing_purchases_001.py:94>), [test_costing_purchases.py:55](</home/johnny/wt-live-cogs-xero/tests/test_costing_purchases.py:55>)  
   Scenario: Xero sends a unit amount with more than four decimal places. PostgreSQL rounds it to `NUMERIC(18,4)`, even though the specification describes it as Xero’s value “as sent” and the broader data model assigns unit costs six decimal places. The test fixture never supplies or asserts `unit_amount`.  
   Fix: use the contract’s unit-cost precision, at least `NUMERIC(18,6)`, consistently in migration and model; add a precision-preservation test.

9. **Low — Several acceptance tests are not independently falsifiable.**  
   [test_costing_purchases.py:258](</home/johnny/wt-live-cogs-xero/tests/test_costing_purchases.py:258>), [test_costing_purchases.py:318](</home/johnny/wt-live-cogs-xero/tests/test_costing_purchases.py:318>), [test_costing_purchases.py:362](</home/johnny/wt-live-cogs-xero/tests/test_costing_purchases.py:362>), [test_costing_purchases.py:380](</home/johnny/wt-live-cogs-xero/tests/test_costing_purchases.py:380>), [test_costing_purchases.py:458](</home/johnny/wt-live-cogs-xero/tests/test_costing_purchases.py:458>), [test_costing_purchases.py:797](</home/johnny/wt-live-cogs-xero/tests/test_costing_purchases.py:797>)  
   Concrete gaps:

   - Several Layer-1 keywords are combined in one account name, so breaking `excise`, `salar`, `power`, `heating`, `courier`, or `postage` independently can remain green; `fuel` has no direct case.
   - `NoTax` supplies tax zero, so retaining a nonzero Xero tax would not be caught.
   - `A,X,B` does not assert that old B was superseded and both X and the new B were inserted.
   - LineItemID coverage does not exercise moving position, changing account, or other “whatever changed” fields.
   - Cross-org account PUT does not assert that the target org’s line treatment stayed unchanged.
   - Cursor coverage does not assert `started_at − RESUME_OVERLAP`, and counting coverage does not prove that a transaction with no storable lines contributes zero.
   - Foreign-currency coverage omits assertions that both line tax and both document totals are null.
   - There is no downgrade-refusal test for an existing `treatment_override`.

   Fix: split keyword cases, use adversarial inputs, and assert row identity/history and every nullable amount explicitly.

VERDICT: fail
