# Tastings task types: migration safety

Date: 2026-10-27. Spec: `.agents/specs/tastings-tasks.md`. Read `.claude/skills/migration-safety/SKILL.md`. Read-only reviewer; no schema operation or app/test/script edit performed.

## Revisions and destructive scope

- `tastings_tasks_001`, parent `tastings_001`: adds only nullable `crm_tasks.task_type` varchar20, then the general server default and supported-value check. Existing rows may remain NULL until the follow-up. The retained raw Alembic autogenerate output contains this exact new column; unrelated cloned-schema drift/drop operations were removed rather than shipped.
- `tastings_tasks_002`, parent `tastings_tasks_001`: explicit backfill revision followed by NOT NULL. It fills NULLs with general, then marks only same-org task/event links tasting. Both updates select at most1000 IDs per iteration and stop when no row is changed. Re-running the backfill on a completed state selects no rows. Existing nonnull ordinary labels remain unchanged unless a same-org tasting link makes them specialized.

**Upgrade destructive: no.** Neither upgrade drops an existing object, deletes rows, changes an existing type nor weakens an existing integrity constraint. No destructive-upgrade permit is required. The proposed original combined revision was private/unpushed and was reversed in scratch before regeneration; this is not an edit to a deployed migration.

Downgrade002 reverses the NOT NULL tightening and retains backfilled values. Downgrade001 removes the newly introduced check and column; as expected, rolling back the feature removes its type labels but preserves every pre-existing task and all tasting/event/allocation/removal records. A later re-upgrade re-derives tasting identity from the retained same-org event link. There is no attempt to reverse or credit physical stock/excise during schema rollback.

## Chain and CI

Independently ran the read-only Alembic graph commands: `heads` reports exactly **tastings_tasks_002 (head)**. History is `tastings_001 -> tastings_tasks_001 -> tastings_tasks_002`; no duplicate revision or multiple head was present. The existing `migration_reversibility` CI job upgrades to head, downgrades and upgrades again, including a full base/head cycle, so these revisions participate in its normal chain.

## Scratch rehearsal evidence

Read root's actual migration logs and verified its wrapper explicitly sets database name `workflow-engine-test_tastings_build`; the shared incompatible DB is not the target. Logs show both new revisions upgrading, then the seeded run downgrading002/001 to tastings_001 and upgrading001/002 again without error. The root's retained raw autogenerate file and log establish generation, with explicit safety edits afterward. I did not perform additional schema operations.

Parsed the final JSON records from the seeded snapshots, rather than comparing the surrounding config logs:

| Fact | Before | After seeded down/up |
|---|---:|---:|
| CRM tasks | 7 | 7 |
| Tasting events | 7 | 7 |
| Tasting stock lots | 2 | 2 |
| Remaining stock, mL | 1950.0000 | 1950.0000 |
| Same-org linked tasks typed tasting | 7 | 7 |
| NULL types | 0 | 0 |

Snapshots are identical for every recorded value. This proves the seeded link backfill and counted balances survived rollback/re-upgrade. The snapshot does not contain an ordinary task sample or every individual allocation field; ordinary NULL/default handling and nonnull label preservation were additionally checked directly in the bounded update predicates, not misrepresented as sampled data evidence.

## Final migration002 delta recheck

Re-reviewed the subsequent static-SQL rewrite read-only. The two complete SQL literals preserve the original NULL-to-general and same-org-linked-to-tasting predicates. Assigned values and the1000-row limit are bound parameters; no predicate concatenation remains. `count=1000; while count == 1000` executes at least one bounded batch, repeats after a full batch, and terminates after a partial or empty batch. Each changed row ceases to match its pass's predicate, so the loop makes progress and remains idempotent. Exact multiples of1000 correctly incur one final empty batch before stopping.

The NOT NULL tightening, parent/head IDs and nullable downgrade are unchanged. No new destructive scope or constraint weakening was introduced. Root reports that it reversed only scratch002 before this private revision edit and successfully upgraded again; this report's earlier seeded snapshot comparison remains evidence for the same unchanged data predicates, not a claim that the reviewer reran a database operation on the rewrite. No DB mutation was performed for this follow-up.

Final mechanical recheck: the batch loop now lives in `_backfill(db, query, value)`, called explicitly once for NULL/general and once for same-org tasting links. I read the final helper and both complete SQL call arguments. Query predicates, bound parameters,1000-row progress/termination, ordering and constraint/downgrade behavior remain the same. Removing the outer Python `for` does not change which records are updated or the transaction boundary; it avoids misclassifying the deliberate batch loop as a per-record request N+1. No additional schema or database operation was performed by this reviewer.

No open migration finding. Exact-head migration CI remains required after the changes are committed/pushed.

VERDICT: clean
