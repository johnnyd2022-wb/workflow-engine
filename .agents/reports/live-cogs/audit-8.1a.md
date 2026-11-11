## Security / tenancy

### Medium — Cost-walk budget can be bypassed and still performs unbounded N+1 queries

- **Location:** [engine.py:269](/home/johnny/wt-live-cogs/app/features/costing/engine.py:269), [engine.py:518](/home/johnny/wt-live-cogs/app/features/costing/engine.py:518), [engine.py:539](/home/johnny/wt-live-cogs/app/features/costing/engine.py:539)
- **Exploit/failure:** `MAX_NODES` charges only lots and executions reached through `_solve`. Last-known-price estimation loads every lot in the organisation and evaluates every same-name candidate through `_direct_cost` without charging them. Execution steps likewise do not count individually. A MEMBER can create many matching lots/workflow steps and repeatedly request an unpriced lot or execution, causing thousands of database round trips and large responses while remaining below the nominal 20,000-node budget.
- **Fix:** Charge every evaluated lot, execution step, and estimate candidate against a substantially lower request budget. Bulk-load flows and entries for candidate IDs, cap estimate candidates at the SQL layer, and add a route-level rate or execution-time limit.

### Medium — Tiny PUT schemas accept and parse bodies up to the global 20 MiB upload limit

- **Location:** [routes.py:63](/home/johnny/wt-live-cogs/app/features/costing/routes.py:63), [routes.py:76](/home/johnny/wt-live-cogs/app/features/costing/routes.py:76), [routes.py:118](/home/johnny/wt-live-cogs/app/features/costing/routes.py:118), [app_factory.py:54](/home/johnny/wt-live-cogs/app/api/app_factory.py:54)
- **Exploit/failure:** Both costing PUT routes call `request.get_json()` without an endpoint-specific limit. The inherited application limit is 20 MiB because it is sized for document uploads. Any MEMBER or custom role with `costs.manage` can repeatedly make workers allocate and parse 20 MiB JSON documents for requests whose legitimate payload is under 1 KiB.
- **Fix:** Set `request.max_content_length` to a small bound such as 16 KiB in the costing blueprint before-request hook, and reject oversized `Content-Length` before parsing.

### Low — Cost-entry creator is not tenant-composite-keyed

- **Location:** [models.py:143](/home/johnny/wt-live-cogs/app/features/costing/models.py:143), [costing_engine_001.py:99](/home/johnny/wt-live-cogs/app/core/db/migrations/versions/costing_engine_001.py:99)
- **Exploit/failure:** `created_by_user_id` references only `users.id`, despite the slice’s rule that cross-table links include `org_id`. The current HTTP service supplies the authenticated user, so there is no direct mass-assignment exploit, but an internal/CLI writer can persist a cross-org attribution and the database will accept it.
- **Fix:** Replace the scalar FK with `(org_id, created_by_user_id) → users(org_id, id)` in both model and migration.

No route IDOR was found: lot, entry, flow, execution, transfer, entitlement, export, and backfill access binds `org_id`. The policy table correctly grants MEMBER both costing permissions, denies PRODUCTION and other fixed roles, and permits custom-role grants. The CLI’s `unscoped()` section is limited to organisation enumeration/validation and exits before each tenant-scoped backfill. Costing error handlers expose only deliberately constructed validation messages.

## Migration safety

### High — Downgrade guard permits irreversible loss of flow history and settings

- **Location:** [costing_engine_001.py:147](/home/johnny/wt-live-cogs/app/core/db/migrations/versions/costing_engine_001.py:147), [backfill.py:79](/home/johnny/wt-live-cogs/app/features/costing/backfill.py:79)
- **Failure:** Downgrade refuses only when `lot_cost_entries` contains rows, then unconditionally drops `cost_flows` and `costing_settings`. An organisation can have no typed price but have live `reconciled_in` flows and a non-default `use_last_known_price` choice. Historical reconciliations are explicitly not reconstructed by the backfill, so downgrade/re-upgrade permanently changes calculated costs.
- **Fix:** Refuse downgrade when any of the three tables contains meaningful data—safest is any row at all—or require an explicit destructive-migration permit after export/backup. Do not describe all flows as rebuildable.

### Low — Migration omits indexes declared by the tenant mixin

- **Location:** [tenant_mixin.py:40](/home/johnny/wt-live-cogs/app/core/db/models/tenant_mixin.py:40), [costing_engine_001.py:33](/home/johnny/wt-live-cogs/app/core/db/migrations/versions/costing_engine_001.py:33)
- **Failure:** Model metadata declares `ix_cost_flows_org_id`, `ix_lot_cost_entries_org_id`, and `ix_costing_settings_org_id` through `TenantScoped.org_id(index=True)`, but the migration creates none of them. The deployed schema therefore differs from the models and a future autogeneration will propose unexpected indexes.
- **Fix:** Add and downgrade the three indexes, or explicitly change the model metadata if the redundant indexes are intentionally omitted.

The upgrade is otherwise additive: three new tables plus one unique constraint, with nullable/default-safe new-table columns and no migration-time backfill. It forms the single Alembic head. The new unique constraint on `execution_steps` does take an `ACCESS EXCLUSIVE` lock and builds a unique index, but current repository evidence shows only 252 executions and a low-hundreds-scale production history; this table is small enough that `CONCURRENTLY` is not warranted for !689. Reassess if the deployment count is materially larger. Up/down/up could not be rehearsed because the test database was unavailable. Gitleaks found no secrets; Semgrep and `uv audit` could not initialize under the strictly read-only filesystem.

VERDICT: findings-open
