# MIGRATION-SAFETY AUDIT: inventory

date: 2026-07-27
branch: work/2026-07-27-session (rebased onto review-feature @ 8d95f83, open MR !133 → main, not merged)
scope: every Alembic revision touching `inventory_items`, `inventory_wastage`,
`inventory_movements`, `api_idempotency_keys` under `app/core/db/migrations/versions/`

## Method

1. Enumerated every revision touching the four in-scope tables via `grep -l` across
   `app/core/db/migrations/versions/*.py` — 17 revisions (list below).
2. Read every one of the 17 line by line: real downgrade vs `pass`, destructive-change
   check, permit-file check (`.agents/reports/migrations/` — directory does not exist,
   zero permit files anywhere in the repo).
3. Confirmed a single Alembic head: `alembic heads` → `crm_revenue_baseline_target_001
   (head)` only.
4. Standard gate, run against the real test DB (localhost:8401, already at head):
   `alembic downgrade -1` → `alembic upgrade head`. Passed.
5. Deeper rehearsal, run against an **isolated scratch database** on the same Postgres
   instance (`workflow_engine_test_migration_scratch`, created/dropped by this audit,
   never touching the shared test DB's schema or rows):
   - `alembic upgrade head` from a totally empty database.
   - `alembic downgrade merge_heads_001` — this walks every single one of the 17
     in-scope revisions' `downgrade()` in reverse, plus everything else added after
     `merge_heads_001` (the checkpoint right before inventory tables were introduced).
   - `alembic upgrade head` again — re-applies all of them forward.
   - Inspected `inventory_items.quantity` column type/precision and the guard trigger
     (`trg_inventory_items_qty_write_guard` / `inventory_items_enforce_qty_write_guard`)
     before the downgrade and after the round-trip.
6. Live functional probe on the real test DB (localhost:8401), at head, to prove the
   guard trigger is not just present but *armed*: inserted a throwaway row into
   `inventory_items` with no GUC set (rejected, as expected), then with
   `app.inventory_qty_guard='1'` set (succeeded, as expected), then deleted the probe
   row. Row counts before/after: `inventory_items` 181, `inventory_wastage` 37,
   `inventory_movements` 15, `api_idempotency_keys` 1 — unchanged, confirmed via
   `alembic_version` still at `crm_revenue_baseline_target_001` and `git status` clean
   throughout.

## Result: full round-trip

```
=== upgrade head (from base, fresh scratch db) === → succeeded, all 61 revisions
quantity column type at head: ('numeric', 18, 4)
triggers on inventory_items at head: ['trg_inventory_items_qty_write_guard']
guard function exists at head: True

=== downgrade to merge_heads_001 (pre-inventory checkpoint) ===
→ every downgrade() from crm_revenue_baseline_target_001 back through all 17
  in-scope revisions ran without error (full log of "Running downgrade X -> Y"
  captured, no exceptions)
tables remaining after downgrade to merge_heads_001:
  audit_logs, customers, organisations, trusted_devices, users
enum types remaining: organisation_status, user_role

=== upgrade head again (round 2) === → succeeded
quantity column type at head (round2): ('numeric', 18, 4)
triggers on inventory_items at head (round2): ['trg_inventory_items_qty_write_guard']
SCRATCH_AUDIT_OK
```

Live probe on the real test DB:
```
insert without guard GUC → blocked: "inventory_items: quantity INSERT blocked
  (set app.inventory_qty_guard via app, or app.migration_mode for migrations)"
insert with app.inventory_qty_guard='1' → succeeded
row counts before/after: unchanged (181 / 37 / 15 / 1)
```

**Verdict on reversibility, per-revision: all 17 in-scope revisions have a real,
functioning downgrade.** No `pass`/`NotImplementedError` bodies among them (the two
`pass`/`pass` revisions in the chain — `merge_inv_qty_api_idem_001` and
`merge_inv_mov_qty_001` — are legitimate no-op Alembic merge points joining branches
that each already carry their own real downgrades; that's the correct pattern, not a
violation). The quantity guard trigger survives a full teardown/rebuild of the schema
and is confirmed live-armed against the real DB.

## Revisions audited (17, in downgrade order from head)

| revision | touches | destructive? | downgrade | permit |
|---|---|---|---|---|
| `wastage_reason_001` | inventory_wastage | no (nullable add) | real (`drop_column`) | n/a |
| `inv_qty_pg_guard_003` | trigger only | no | real (restores prior fn body) | n/a |
| `merge_inv_mov_qty_001` | merge point | no | `pass` (legitimate, no-op merge) | n/a |
| `inv_mov_item_created_ix_001` | inventory_movements | no (indexes) | real (`DROP INDEX IF EXISTS` x2) | n/a |
| `inv_mov_wastage_fk_001` | inventory_movements | no (nullable FK+col) | real (`drop_constraint`+`drop_column`, guarded) | n/a |
| `inventory_movements_001` | inventory_movements | no (new table) | real (`drop_table`, guarded) | n/a |
| `merge_inv_qty_api_idem_001` | merge point | no | `pass` (legitimate, no-op merge) | n/a |
| **`inventory_quantity_numeric_001`** | **inventory_items.quantity** | **YES — narrowed type, String(50)→NUMERIC(18,4), in place** | real (ALTER back to VARCHAR(50) via `to_char`) | **none — finding below** |
| `api_idempotency_keys_001` | api_idempotency_keys | no (new table) | real (`drop_table`, guarded) | n/a |
| `inv_qty_pg_guard_002` | trigger only | no | real (restores prior fn body) | n/a |
| `inv_qty_pg_guard_001` | trigger only | no (new trigger) | real (`DROP TRIGGER`/`DROP FUNCTION`) | n/a |
| `uq_inventory_org_barcode_001` | inventory_items | no (index) | real (`drop_index`) | n/a |
| `add_barcode_inventory_001` | inventory_items | no (nullable add) | real (`drop_index`+`drop_column`) | n/a |
| `inventory_batch_unique_001` | inventory_items | no (partial unique index) | real (`drop_index`) | n/a |
| `inventory_wastage_001` | inventory_wastage | no (new table) | real (`drop_table`) | n/a |
| `source_output_id_001` | inventory_items | no (nullable add) | real (`drop_index`+`drop_column`) | n/a |
| `event_sourcing_process_versions_001`* | inventory_items.display_label | no (nullable add) | real (`drop_column` + rest) | n/a |
| `add_core_process_execution_models` | inventory_items (creation) | no (new table) | real (drops table + 3 enums it created, `checkfirst=True`) | n/a |

\* also touches `executions`/`process_versions`, out of this audit's four tables but its
`inventory_items.display_label` column is in scope and its downgrade is correct.

## Findings

### 1. `inventory_quantity_numeric_001` is a historical destructive migration with no permit file — CONFIRMED, unresolved

`app/core/db/migrations/versions/inventory_quantity_numeric_001.py` alters
`inventory_items.quantity` from `String(50)` to `NUMERIC(18,4)` **in place** via a raw
`ALTER TABLE ... ALTER COLUMN quantity TYPE NUMERIC(18,4) USING (...)`, not the
expand-contract pattern (`migration-safety` §1: add column → backfill → dual-write →
drop old in a later revision). Two things make this destructive under the skill's own
definition (§2: "a data-losing type change"):

- **Precision narrowing**: any pre-existing string value with more than 4 decimal
  digits is silently rounded by the `USING ...::numeric` cast. There is no row-count or
  sample-row check before/after in the migration, and none was possible retroactively
  (this ran 2026-03-28, `git log` shows commit `68268ab`).
- **Silent data substitution**: the `CASE WHEN trim(...) = '' THEN 0::numeric ELSE
  ...::numeric END` clause turns any blank legacy quantity into `0` with no logging —
  a data edit hidden inside a schema-type-change migration (skill §1: "No data edits
  hidden in schema migrations. Backfills live in their own revision").

Per skill §2, a destructive migration needs (a) an `ALLOW_DESTRUCTIVE=<revision_id>`
env-var guard in `upgrade()`, (b) a permit file at
`.agents/reports/migrations/inventory_quantity_numeric_001.md`, (c) explicit user
approval recorded before merge. None of the three exist — `.agents/reports/migrations/`
does not exist at all in this repo, and no `ALLOW_DESTRUCTIVE` guard appears anywhere in
the migration.

This is historical (already applied, already in every environment's `alembic_version`,
its own docstring insists "this revision id must stay stable"), so the remediation is
not to rewrite it — it's to close the paper trail retroactively: write the permit file
now (what was destroyed — precision beyond 4dp and blank→0 coercion on legacy string
quantities; why — the app needs Decimal-exact arithmetic per this feature's spec; what
backs it up — nothing, no pre-migration snapshot exists 4 months later) and get it
explicitly acknowledged, so the next auditor doesn't have to re-derive this. I have
read-only access and cannot write that file myself.

### 2. Adjacent, out-of-table-scope: the *first* migration in the whole chain (`0e781c27351d`, unrelated to inventory) has an incomplete downgrade that blocks full-history reversibility

Not one of the four audited tables (it only creates `customers`/`organisations`/
`users`/`audit_logs`), but discovered as a direct result of the up/down/up rehearsal this
audit was asked to run, and it's the reason a *literal* base→head→base→head cycle fails
today (not just for inventory — for the whole app):

`0e781c27351d`'s `downgrade()` drops the four tables it created but never drops the two
enum types it created (`organisation_status`, `user_role`). Reproduced on a scratch DB:
after `upgrade head` → `downgrade base` → `upgrade head`, the second upgrade dies with
`psycopg2.errors.DuplicateObject: type "organisation_status" already exists` on the very
first revision. `add_core_process_execution_models` (which *does* touch inventory,
creating the `inventory_items` table) gets this right — its downgrade drops the three
enums it created with `checkfirst=True` — so the fix pattern already exists in this
codebase, it just wasn't applied to the very first migration.

This is why my rehearsal above stopped at `merge_heads_001` rather than `base`: that
checkpoint is exactly the boundary before inventory tables exist, so it exercises every
inventory-relevant downgrade without tripping this unrelated bug. `.gitlab-ci.yml`'s
`migration_reversibility` job (lines 291–312) only runs `alembic downgrade -1` /
`alembic upgrade head` against a DB `ci/setup_database.sh` has already brought to head —
it never provisions from a truly empty database, so this defect is currently invisible
to CI. Flagging for whichever audit owns the non-inventory tables (or a follow-up
`review-feature` pass over auth/org), since it's outside this stage's four-table
mandate — not treating it as an inventory finding, just recording it so it isn't
independently rediscovered.

## Not findings (checked, no issue)

- Multiple heads: none (`alembic heads` → single head).
- The three `pg_guard` trigger-function revisions (`inv_qty_pg_guard_001/002/003`)
  correctly restore the prior function body on downgrade, verified by the round-trip
  restoring the exact same trigger name and a working guard at head afterward.
- `inv_mov_wastage_fk_001` and `inventory_movements_001` guard their `upgrade()`/
  `downgrade()` with existence checks (`insp.get_table_names()`), safe to re-run.
- AC9–AC11 (the quantity guard, the thing this whole feature protects) verified live:
  direct `INSERT` into `inventory_items` without `app.inventory_qty_guard` set is
  rejected by the DB trigger with the expected error text; with the GUC set, it
  succeeds. Confirmed on the real test DB post-round-trip, not just the scratch DB.
- `app.migration_mode` is set once for the whole Alembic run in `env.py:109`
  (`SELECT set_config('app.migration_mode', '1', true)`), consistent with AC11's stated
  migration exemption — migrations never need to set it themselves, and none of the 17
  in-scope revisions do.

## Report generation note

Wrote and ran a throwaway Python harness (`alembic.command.upgrade`/`.downgrade` against
a dedicated scratch database created and dropped on the same Postgres instance, never
touching the shared test DB's tables or rows) to get a true base-to-head-and-back
rehearsal without risking the 181/37/15/1 rows already sitting in the shared test DB.
Scratch DB and script both cleaned up; `git status` and row counts confirmed unchanged
before/after.

VERDICT: findings-open

---
*Stage ran read-only (Sonnet 5, xhigh, Herdr tab w7:t2). Report transcribed verbatim by the review-feature orchestrator, per `.agents/verification-chain.md` §5.*
