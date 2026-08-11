# migration-safety: wastage
date: 2026-08-11
scope: wastage

## Migrations touching this slice's tables
`inventory_wastage` (own table) and `inventory_movements.source_wastage_id` (FK into it):

| revision | what | downgrade | verdict |
|---|---|---|---|
| `inventory_wastage_001` (2025-02-14) | creates `inventory_wastage`, `org_id` **NOT NULL** from inception, `ix_...recorded_at` | drops index then table | clean |
| `inv_mov_wastage_fk_001` | adds `inventory_movements.source_wastage_id` FK + unique constraint | drops constraint then column, guarded by table/column-exists checks (idempotent under partial runs) | clean |
| `wastage_reason_001` (2026-05-10) | adds nullable `reason` column | drops column | clean (reason values lost on downgrade, but the column is genuinely optional/new — not the "silent data edit hidden in a schema migration" class of problem the inventory review's permit was about) |

`add_inventory_batch_unique_constraint` chains after `inventory_wastage_001` in revision
history but operates on `inventory_items`, not `inventory_wastage` — out of scope for
this slice.

## Tenant-scoping migration check (this branch's own effort)
This branch (`feat/global-org-scoping`) is mid-flight adding `org_id NOT NULL` across
several tables (`tenant_org_id_backfill_001` → `tenant_org_id_notnull_001`, current head).
**`inventory_wastage` is not in that migration's `TABLES` tuple** (`steps`,
`execution_steps`, `trusted_devices`, `two_factor_backup_codes` only) — correctly so:
`inventory_wastage.org_id` has been `nullable=False` since its original 2025-02-14
migration, so it never needed backfill+tighten. The model's `TenantScoped` mixin adoption
(commit `35e4ec9`) declares `org_id` identically (`UUID`, FK `organisations.id`,
`nullable=False`, `index=True`, no `ondelete`) to what the original migration already
created — a pure model-layer refactor, correctly shipped with no accompanying migration.

## Historical destructive changes
None on this slice's tables. (The one destructive migration flagged by the prior
inventory review, `inventory_quantity_numeric_001`, alters `inventory_items.quantity` —
a different table, already permitted and accepted as a founder decision; not reachable
from wastage's own migrations.)

## up/down/up
Not run live — no new migration is proposed by this review, and the DB is already
confirmed at head (`tenant_org_id_notnull_001`, preflight). Live up/down/up is warranted
when a migration changes; none does here.

## VERDICT: clean
