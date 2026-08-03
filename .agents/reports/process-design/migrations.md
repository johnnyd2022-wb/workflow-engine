# MIGRATIONS: process-design
date: 2026-08-02

## Revisions touching process-design tables (processes, steps, process_versions, process_step_documents)

| revision | tables | change | downgrade present | destructive | permit |
|---|---|---|---|---|---|
| add_core_models_001 | processes, steps (+ executions, execution_steps, inventory_items — shared with execution/inventory) | create tables + process_category enum | yes, symmetric drop | no (creates only) | n/a |
| add_execution_prompts_001 | steps | add `execution_prompts` JSONB NOT NULL DEFAULT '[]' | yes, drops column | no (additive, has default) | n/a |
| add_is_draft_001 | processes | add `is_draft` BOOLEAN NOT NULL DEFAULT false + index | yes, drops column+index | no (additive, has default) | n/a |
| uq_steps_process_step_number_001 | steps | add UNIQUE(process_id, step_number) | yes, drops constraint | no (adds a constraint) | n/a |
| **drop_uq_steps_psn_001** | steps | **drop** UNIQUE(process_id, step_number) — Option B ordering switch | yes, recreates constraint | **yes — removes a constraint that guards integrity** | **none found** |
| steps_position_001 (referenced, not process-design-specific content beyond adding `position`) | steps | add `position` NUMERIC | yes | no | n/a |
| add_process_step_docs_001 | process_step_documents | create table + CHECK constraint (storage_path OR content_markdown OR deleted_at) | yes, symmetric drop | no (creates only) | n/a |
| event_sourcing_proc_ver_001 | process_versions (+ executions.process_version_id, inventory_items.display_label) | create table + FK columns | yes, symmetric drop | no (creates only) | n/a |

`alembic heads` → single head (`crm_revenue_baseline_target_001`). No branching/multiple-heads problem in this chain.

## Finding: undocumented destructive migration (pre-existing, already shipped)

`drop_uq_steps_psn_001` (2026-04-13) drops `uq_steps_process_step_number` — a unique constraint that
was guarding integrity (no two steps in a process could share a step_number). Per this skill's
definition, removing an integrity-guarding constraint is destructive and requires an
`ALLOW_DESTRUCTIVE` env guard plus a permit file at `.agents/reports/migrations/<revision_id>.md`.
Neither exists for this revision.

Mitigating context: it's paired with `uq_steps_process_step_number_001` (added the constraint) and
`steps_position_001` (added the replacement `position` ordering column) in the **same day**
(2026-04-13) — the sequence reads as "added constraint, added the real ordering mechanism, removed
the now-wrong constraint" within one development arc, not an ad-hoc drop against a live table with
data depending on the old uniqueness. The migration is already merged, applied, and is many
revisions behind current head (`crm_revenue_baseline_target_001`) — it's history, not something this
review is introducing.

**Recommendation:** backfill a permit file documenting the intent (Option B ordering supersedes
step_number uniqueness) for the audit trail, but do not attempt to re-guard or revert an
already-shipped, already-relied-upon schema change. Not blocking this review.

**Update (Step 4, this review):** permit file backfilled at
`.agents/reports/migrations/drop_uq_steps_psn_001.md` — status `pending founder
acknowledgement`, surfaced in the final review report alongside the F3 authorization-model
question.

## up/down/up rehearsal

Not run. The test DB container (`workflow-engine-test-db`) is a single shared instance (confirmed
via `docker ps`, uptime 41h) used across concurrent worktrees/sessions on this machine, currently at
head `crm_revenue_baseline_target_001` — many revisions ahead of any process-design migration.
Downgrading it to rehearse process-design's revisions individually would require rolling back every
intervening migration first, which risks disrupting other sessions' state and is not reversible
in-place without re-seeding. Since this review introduces **no new migrations**, structural review
(every revision above has a real, symmetric `downgrade()` that was read and verified by hand) is the
appropriate substitute here. If this review's patch work ends up requiring a new migration (e.g. to
add version/event tracking to the reorder endpoint), that new revision will get a full
upgrade→downgrade→upgrade rehearsal against a disposable scratch DB before it ships.

## Verdict
No new migrations from this review (yet). One pre-existing undocumented-destructive finding
(`drop_uq_steps_psn_001`, low severity — historical, already shipped, has a real downgrade,
recommend backfilling a permit file for the record). Everything else: real downgrades present,
correctly reversed.
