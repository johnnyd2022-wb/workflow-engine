## Security

### Medium — Cost-walk budget does not bound actual work

- **Files:** [engine.py:204](/home/johnny/wt-live-cogs-xero/app/features/costing/engine.py:204), [engine.py:269](/home/johnny/wt-live-cogs-xero/app/features/costing/engine.py:269), [engine.py:397](/home/johnny/wt-live-cogs-xero/app/features/costing/engine.py:397)
- **Exploit/failure:** A MEMBER can create large workflows/executions and repeatedly request execution costs. `MAX_NODES` charges an execution once, regardless of its number of steps, while `_info()` loads every step and flow and `execution()` evaluates every step. Even 20,000 charged lots can generate tens of thousands of ORM queries. There is no endpoint rate limit or separate work/output budget, so requests below the nominal limit can occupy shared workers and affect other tenants.
- **Fix:** Add an operational budget covering evaluated steps, loaded flows, estimate candidates, queries, and response rows independently of the contract’s “lots + executions” semantic count. Bulk-load lot flows/entries, return `too_large` before constructing oversized results, and rate-limit costing reads.

### Low — Purchase-sync exceptions expose internals and potentially Xero data

- **Files:** [xero_sync_service.py:603](/home/johnny/wt-live-cogs-xero/app/features/crm/services/xero_sync_service.py:603), [oauth_routes.py:273](/home/johnny/wt-live-cogs-xero/app/features/crm/routes/oauth_routes.py:273)
- **Exploit/failure:** The purchases phase places `str(e)` into `result.errors`; the manual-sync API returns that string to a `sales.manage` caller. SQLAlchemy errors can include SQL, constraint/table names, and bound values such as Xero payee names or line descriptions. A malformed or oversized Xero value can therefore turn a sync failure into an internal-schema and purchase-data disclosure, including to a custom role without `costs.view`.
- **Fix:** Log the complete exception server-side with a correlation ID, but expose only stable codes/messages such as `purchases_sync_failed`. Persist sanitized error summaries in sync jobs.

No tenant-IDOR or role bypass was found in the new account API or inherited lot/entry/execution routes. Queries bind `org_id`; purchase-line relationships use composite tenant foreign keys; foreign account IDs return 404. The policy hook runs before the costing feature gate, and unauthenticated requests still reach `@requires_auth` as 401. PRODUCTION and other fixed roles remain denied; account PUT uses an exact-field allowlist, and costing bodies are capped at 16 KiB. The CLI’s `unscoped()` block only enumerates or validates organisations before entering `tenant_scope()`.

Xero account names/codes are stored in `xero_accounts` and returned as JSON; payee/reference/bank fields go to `purchase_documents`; descriptions and item/account snapshots go to `purchase_lines`. No HTML or unsafe-template sink exists in this MR. The data export neutralizes spreadsheet formulas before CSV output. The two added OAuth scopes are valid read-only granular scopes and match the fetched resources: `accounting.banktransactions.read` and `accounting.settings.read` ([Xero scope documentation](https://developer.xero.com/documentation/guides/oauth2/scopes/)).

Gitleaks scanned the 11-commit range and found no leak. Semgrep and `uv audit` could not run because both require temporary/cache writes while this audit was constrained to a read-only filesystem.

## Migration safety

### High — Existing `execution_steps` table receives a blocking UNIQUE constraint

- **File:** [costing_engine_001.py:31](/home/johnny/wt-live-cogs-xero/app/core/db/migrations/versions/costing_engine_001.py:31)
- **Failure:** This inherited migration in the stacked chain uses `ALTER TABLE … ADD CONSTRAINT UNIQUE`, which scans/builds an index on the existing, append-growing `execution_steps` table while taking a write-blocking lock. There is no cardinality cap or production measurement establishing that the table is small.
- **Decision:** It needs a concurrent index; the table is not demonstrated small enough for blocking DDL.
- **Fix:** In an Alembic autocommit block, run `CREATE UNIQUE INDEX CONCURRENTLY` on `(org_id, execution_id, id)`, then attach it with `ALTER TABLE … ADD CONSTRAINT … UNIQUE USING INDEX …`. Keep the constraint downgrade.

### Medium — Downgrade guard permits non-recoverable purchase-history loss

- **Files:** [costing_purchases_001.py:138](/home/johnny/wt-live-cogs-xero/app/core/db/migrations/versions/costing_purchases_001.py:138), [xero_sync_service.py:620](/home/johnny/wt-live-cogs-xero/app/features/crm/services/xero_sync_service.py:620)
- **Failure:** Downgrade refuses only when a treatment override exists. After an ordinary successful sync with no override, it drops purchase documents/lines and the original `start_date`. On re-upgrade, `_anchor_purchases()` sets `start_date` to the current day, so older previously imported purchases are no longer fetched. The claim that purchase rows are simply re-fetchable is therefore false after the anchor is lost.
- **Fix:** Refuse downgrade when any purchase document/line exists or when any costing row has `start_date`, purchase cursor/tenant, or base currency populated. Alternatively preserve and restore the original anchor through an explicitly approved destructive rollback procedure.

The 8.1b upgrade is otherwise additive: new tables, nullable columns, and a constant `NOT NULL DEFAULT 0` on `xero_sync_jobs`. On supported modern PostgreSQL that default is metadata-only, though it still needs a brief table lock. No backfill is present, model and migration definitions align, and Alembic reports the single head `costing_purchases_001`. Up/down/up was not run because the test database was unavailable and the audit was read-only.

VERDICT: findings-open
