# DESTRUCTIVE MIGRATION PERMIT: `drop_uq_steps_psn_001`

status: **ACKNOWLEDGED — roll forward** (johnny, 2026-08-03)
raised_by: review-feature, process-design audit, 2026-08-02
revision: `drop_uq_steps_psn_001`
file: `app/core/db/migrations/versions/drop_uq_steps_psn_001.py`
applied: 2026-04-13 — already in every environment's `alembic_version`, several
revisions behind current head (`crm_revenue_baseline_target_001`)

## Why this file exists

`migration-safety` §2 treats "removing a constraint that guards integrity" as
destructive, requiring an `ALLOW_DESTRUCTIVE=<revision_id>` guard, a permit file, and
recorded human approval before merge. This revision has none of them — it predates
`.agents/reports/migrations/` existing in this repo at all.

## What was removed

`uq_steps_process_step_number` — a UNIQUE constraint on `steps(process_id,
step_number)` — was dropped outright (`op.drop_constraint(...)`, no data touched).

## Why it was done (not a bare removal — a design supersession, same day)

Three revisions landed on 2026-04-13, in this order:
1. `uq_steps_process_step_number_001` — added the constraint (a TOCTOU fix for
   step_number assignment races).
2. `steps_position_001` — added `steps.position` (NUMERIC(50,20)), the real ordering
   mechanism for drag/drop ("Option B": fractional positions, no bulk renumbering).
3. `drop_uq_steps_psn_001` (this one) — dropped the now-wrong constraint, because
   `step_number` stopped being canonical ordering once `position` took over; two
   steps legitimately sharing a `step_number` is expected under Option B (the app
   code's own comment confirms this: `backend.py`'s step-write helper explicitly
   declines to enforce step_number uniqueness, "step_number is not canonical
   ordering").

Read together, this is "added constraint → added its replacement → removed the
now-incorrect constraint" within a single development arc, not an ad-hoc drop against
a table already holding data that depended on the old uniqueness.

## What backs it up / restore path

No pre-migration snapshot exists, but none was needed: no data was destroyed (a
constraint removal doesn't touch existing rows), and the `downgrade()` genuinely
reverses it (`op.create_unique_constraint(...)`, verified by reading — not rehearsed
locally against the shared test DB, see `.agents/reports/process-design/migrations.md`
for why; CI's `migration_reversibility` job rehearses the full chain including this
revision against a fresh per-pipeline database on every MR).

**Caveat on the restore path**: re-creating the constraint today would fail if any
process, in the ~3.5 months since, now has two steps sharing a `step_number` under
Option B ordering (exactly the state this migration intentionally made legal). That's
expected — the downgrade restoring a constraint the app no longer honors is a
statement about the schema's history, not a claim that downgrading is safe to run
against current data.

## Decision (2026-08-03)

**Acknowledged; roll forward.** No data was lost (constraint removal only), the
downgrade genuinely reverses it, and the removal was part of a same-day, coherent
design supersession (Option B ordering) rather than an ad-hoc drop against live data.
No code or migration change follows from this — the migration is applied and its
forward behaviour is correct and already relied upon. This closes the audit-trail gap
the migration-safety skill requires, even retroactively for a revision this old and
already shipped everywhere.
