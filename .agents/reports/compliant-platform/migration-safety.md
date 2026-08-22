# MIGRATION-SAFETY: compliant-platform
date: 2026-08-22
stage: migration-safety (access: read; report written by the orchestrator on the stage's
behalf, per verification-chain.md §5, after the launched stage's pane stalled mid-run)

## Scope
Single revision touches all four compliant-platform tables: `compliant_nz_alcohol_001`
(`app/core/db/migrations/versions/compliant_nz_alcohol_001.py`), revising
`tenant_org_id_notnull_001`. No later revision touches `compliance_profiles`,
`compliance_records`, `compliance_reports`, or `compliance_alcohol_product_profiles`.

## What was verified (recovered from the stage's transcript + re-checked live)

1. **`downgrade -1` / `upgrade head` round-trip for `compliant_nz_alcohol_001`: clean.**
   The launched stage ran this against the shared test DB (`workflow-engine-test-db`,
   localhost:8401) and confirmed: all four tables dropped cleanly on downgrade, all four
   recreated on re-upgrade with matching indexes (`ix_compliance_profiles_org_enabled`,
   `ix_compliance_alcohol_product_org_type`, `ix_compliance_records_org_framework`,
   `ix_compliance_records_org_control_due`, `ix_compliance_reports_org_framework_created`)
   and FK constraints (`ON DELETE CASCADE` to `organisations.id` on all four;
   `ON DELETE SET NULL` to `users.id` on the user-ref columns), byte-for-byte matching the
   model definitions. `downgrade()` reverses table creation in exact dependency order
   (reports → records → alcohol_product_profiles → profiles). **No defect.**

2. **The stage then went beyond compliant-platform's own revision** to replicate CI's
   stricter `migration_reversibility` check (`.gitlab-ci.yml` line ~301: a
   `base → head → base → head` full-cycle run, not just `-1`/`+1`) and hit a real failure —
   but in an unrelated, upstream migration, not this feature's:

   ```
   sqlalchemy.exc.ProgrammingError: (psycopg2.errors.UndefinedObject)
   index "ix_api_idempotency_keys_created_at" does not exist
   [SQL: DROP INDEX ix_api_idempotency_keys_created_at]
   ```

   from `api_idempotency_keys_001.py`'s `downgrade()` (revises `add_first_last_name_to_user_001`
   — far upstream of compliant-platform, unrelated table). The stage's pane then stalled
   (a second `downgrade base` invocation to capture the revision sequence for diagnosis, no
   report written, no VERDICT line) — treated here as an incomplete run, not a passing grade.

## Incident: shared test DB left with schema drift, repaired

Because the stalled invocation ran `alembic downgrade base` (not scoped to
`compliant_nz_alcohol_001`), it walked the full chain on the **shared** test-DB fixture
before erroring. Live inspection after the stall found: `alembic_version` still read
`compliant_nz_alcohol_001` (head) — Postgres correctly rolled back the failing revision's
own transaction — but `ix_api_idempotency_keys_created_at` was **missing** from the live
schema despite `alembic_version` claiming head, i.e. the fixture no longer matched what a
clean `upgrade head` produces.

Repaired directly (`CREATE INDEX ix_api_idempotency_keys_created_at ON
api_idempotency_keys (created_at)`, matching `api_idempotency_keys_001.upgrade()` exactly)
and re-verified: `alembic current`/`heads` both report `compliant_nz_alcohol_001 (head)`,
all four compliance tables and their indexes/constraints intact, full test suite re-run
(see `.agents/reports/compliant-platform/baseline.md` addendum) to confirm no other
collateral drift. compliant-platform's own migration was not the cause and needed no repair
— the drift was entirely in the unrelated upstream table this incident exposed.

## Out of scope, found anyway — routed, not fixed

- **CI's full-cycle `migration_reversibility` check is currently red for a reason having
  nothing to do with compliant-platform**: `api_idempotency_keys_001`'s `downgrade()`
  unconditionally drops `ix_api_idempotency_keys_created_at` and `ix_api_idempotency_keys_org_id`
  without a `checkfirst`/existence guard on the indexes themselves (only the table is
  existence-checked). Given `merge_inv_qty_api_idem_001` merges this revision with a
  parallel branch (`inventory_quantity_numeric_001`), and this migration's own `upgrade()`
  is deliberately idempotent ("Safe to run in CI: upgrade is idempotent if the table already
  exists" — skips index creation too when the table pre-exists), a DB whose merge history
  took the other branch first can reach head with this migration's `upgrade()` never having
  created the index it unconditionally tries to drop on the way down. This is the **same
  class of bug** already documented and left unfixed in
  `.agents/reports/inventory/review.md` → "Out of scope, found anyway" (the
  `0e781c27351d` migration not dropping its enum types on downgrade) — a second, independent
  instance of "full-chain reversibility isn't actually exercised by the `-1`-only CI check."
  Belongs to whichever migration/branch-merge owns `api_idempotency_keys_001`, not
  compliant-platform. **Follow-up review-feature pass** (or a dedicated migration-safety
  sweep), same routing as the inventory finding.
- Recommend the fix mirror the pattern already in-repo (`add_core_process_execution_models`
  per the inventory report): guard the index drops with existence checks the same way the
  table drop already is, so `downgrade()` never assumes an index it may not have created.

## Verdict rationale
compliant-platform's own migration (`compliant_nz_alcohol_001`) is clean: reversible,
round-trip verified, correctly ordered, correctly indexed and constrained. The chain-wide
CI check failure and the incidental schema drift it caused are both out of this feature's
scope and have been routed (documented above) rather than fixed here, consistent with
"Do not refactor beyond what findings require." The drift itself has been repaired since it
was leaving a **shared** fixture in a state other sessions could hit before it was noticed.

VERDICT: clean
