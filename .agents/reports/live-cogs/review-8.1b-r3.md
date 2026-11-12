## Prior findings

1. Insufficient-scope classification — resolved. `xero_sync_service.py:597-608` maps direct and wrapped insufficient-scope failures to `needs_reconnect`.
2. Voided/deleted line retention — resolved. `purchase_sources.py:342-374` preserves stored lines and skips unseen voids.
3. Purchases-phase token expiry — resolved. `xero_sync_service.py:599-602` records the error and allows normal finalisation.
4. Activation-anchor commit — resolved. `xero_sync_service.py:87-89,163-165` commits the anchor with the job before sales work. Same-org contention can wait on the settings row, but no lock-order cycle or additional HIGH/MEDIUM failure was found.
5. Every phase failing becoming partial — partially resolved. Phase-level exceptions now produce `failed`, but record-level failures still expose the MEDIUM defect below.
6. Missing monetary values — resolved. `purchase_sources.py:310-323,418-422` preserves unknown amounts and nulls both totals when either component is unknown.
7. Accounts ceasing to be expenses — resolved. `purchase_sources.py:119-146` bases retirement on `default_treatment` eligibility independently of overrides.
8. Unit-amount precision — resolved. Model and migration both use `NUMERIC(18,6)`.
9. Independently falsifiable acceptance tests — partially resolved. The downgrade-refusal regression remains absent; this is below MEDIUM and belongs in the MR as a known limitation.

The three defects remaining in the previous report are otherwise resolved: sales token expiry closes the durable job (`xero_sync_service.py:103-140,613-618`), overrides no longer prevent retirement, and missing tax now nulls document totals.

## Remaining finding

1. **MEDIUM — all record-level sales failures plus a purchases failure are reported as partial success.**  
   `app/features/crm/services/xero_sync_service.py:50-58,100-102,118-123,136-138`

   Failing scenario: each sales fetch returns records, but every contact, invoice, and credit-note record fails inside the per-record savepoints. Each helper returns a `SyncResult` containing errors and zero synced records. The orchestration nevertheless increments `sales_phases_ok` for all three because no exception escaped. If purchases also fail, `SyncResult.partial` becomes true, so the job is marked `partial` and the manual endpoint returns HTTP 200 despite every attempted record and the purchases phase failing. A direct construction with zero counts, errors, `purchases_status="failed"`, and `sales_phases_ok=3` confirms `partial == True`.

   Fix: increment `sales_phases_ok` only when the returned phase result has no errors. Partially successful phases already qualify through their positive synced count. Add a regression where all three helpers return zero counts with record-level errors and purchases fail; require job `failed`, not `partial`.

Focused Ruff checks passed. Pytest could not start because the read-only environment provides no writable temporary directory.

VERDICT: fail
