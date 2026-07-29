# DESTRUCTIVE MIGRATION PERMIT: `inventory_quantity_numeric_001`

status: **ACKNOWLEDGED — roll forward** (johnny, 2026-07-29)
raised_by: review-feature → migration-safety, inventory audit, 2026-07-27
revision: `inventory_quantity_numeric_001`
file: `app/core/db/migrations/versions/inventory_quantity_numeric_001.py`
applied: 2026-03-28 (commit `68268ab`) — already in every environment's `alembic_version`

## Why this file exists

`migration-safety` §2 requires a destructive migration to carry three things: an
`ALLOW_DESTRUCTIVE=<revision_id>` guard in `upgrade()`, a permit file, and recorded human
approval before merge. This revision has none of them, and `.agents/reports/migrations/`
did not exist in this repo at all until this audit created it.

The revision is four months old and already applied everywhere. Rewriting it is not the
remediation — its own docstring correctly insists the revision id stay stable. The
remediation is to close the paper trail so the next auditor doesn't have to re-derive
this from scratch, and so the founder gets to see, once, what was actually done to the
data.

**Approval status: see the Decision section below** — acknowledged 2026-07-29, roll forward.

## What was destroyed

`inventory_items.quantity` was altered from `String(50)` to `NUMERIC(18,4)` **in place**,
with a raw `ALTER TABLE ... ALTER COLUMN quantity TYPE NUMERIC(18,4) USING (...)` — not
the expand-contract pattern (add column → backfill → dual-write → drop in a later
revision) the skill requires.

Two distinct data losses are possible in that statement:

1. **Precision narrowing.** Any pre-existing string quantity with more than four decimal
   places was silently rounded by the `::numeric` cast. No row-count or sample-row check
   ran before or after, so the number of affected rows is unknown and, four months later,
   unknowable.
2. **Silent value substitution.** The `CASE WHEN trim(...) = '' THEN 0::numeric ELSE
   ...::numeric END` clause turned any blank legacy quantity into `0`. That is a data
   *edit* hidden inside a schema migration — skill §1: "No data edits hidden in schema
   migrations. Backfills live in their own revision."

## Why it was done

The inventory feature's whole correctness story depends on Decimal-exact arithmetic:
quantity comparison, wastage deduction against on-hand stock, and unit conversion all
produce wrong numbers under float or string-lexical comparison. `NUMERIC(18,4)` is the
storage type the rest of the code is written against (`coerce_stored_quantity`,
`STORAGE_QUANTIZE_EXP`, the `inventory_movements` ledger). The change was correct in
intent; only its handling was undocumented.

## What backs it up

**Nothing.** No pre-migration snapshot was taken, and none exists now. If a quantity was
rounded or blanked in March 2026, that value is gone. This is the honest answer and the
main reason this permit is worth signing rather than filing. (Mitigated in practice by the
fact that the feature is not yet live in production — see Decision.)

## Restore path

There is a `downgrade()` and it works — verified by this audit's full up/down/up
rehearsal on a scratch database. It converts the column back to `VARCHAR(50)` via
`to_char`. It restores the *type*, not the *lost precision*: a value rounded to 4dp on
the way in comes back out as its rounded self.

## Decision (2026-07-29)

**Acknowledged; roll forward.** The founder's call, recorded verbatim in substance: this
is not live in production yet, so no customer stock figures are at risk from the rounding
or the blank→0 coercion, and there is nothing to investigate. Preventing a repeat is being
delegated to a separate agent rather than handled in this MR.

That makes the two data losses accepted risk on pre-production data. No code change
follows from this either way — the migration is applied and its forward behaviour is
correct. What this decision closes is the audit trail: the next auditor reading
`inventory_quantity_numeric_001` will find a deliberate, dated decision here instead of
having to re-derive the whole question from the SQL.

The permit's factual content above is unchanged and still stands — in particular that
**nothing backs up the lost values**, and that the downgrade restores the column type but
not the rounded precision. If this feature reaches production with real customer stock,
that fact does not become less true; it just stops being cheap.

## Prevention

The gap that let this ship is that `.gitlab-ci.yml`'s `migration_reversibility` job only
runs `alembic downgrade -1` / `upgrade head` against a database already at head — it
never provisions from empty, and it does not check for destructive statements or permit
files at all. A CI check that greps new revisions for in-place type narrowing and
`DROP COLUMN`/`DROP TABLE`, then fails unless a matching permit file exists, would have
caught this at the merge request. Recommended to **ci-gate** as a follow-up; not built
in this audit, which was scoped to the inventory feature. Per the 2026-07-29 decision, the
founder is assigning this prevention work to a separate agent.
