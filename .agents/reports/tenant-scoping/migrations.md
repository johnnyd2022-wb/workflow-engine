# MIGRATIONS: tenant-scoping
date: 2026-08-09

## Revisions

| revision | tables | change | downgrade present | destructive | permit |
|---|---|---|---|---|---|
| tenant_org_id_add_001 | steps, execution_steps, trusted_devices, two_factor_backup_codes | add nullable `org_id` UUID + FK (`ON DELETE CASCADE` to organisations.id) + index | yes, drops index/FK/column in reverse order | no (additive, nullable) | n/a |
| tenant_org_id_backfill_001 | same 4 tables | data-only: `UPDATE ... SET org_id = <parent>.org_id`, guarded by `WHERE org_id IS NULL` (idempotent, re-runnable) | yes, sets org_id back to NULL on the same 4 tables | no (backfill of a nullable column, no prior data touched) | n/a |
| tenant_org_id_notnull_001 | same 4 tables | `ALTER COLUMN org_id SET NOT NULL` | yes, reverts to nullable | no (tightens, doesn't remove, a constraint — and only after the backfill revision guarantees no NULLs remain) | n/a |

Three-revision split (add nullable+FK+index → backfill → NOT NULL) follows this skill's
nullable-first rule verbatim rather than the single-revision shape I drafted first — caught
before running anything, by rereading `.claude/skills/migration-safety/SKILL.md` before
executing.

`alembic heads` → single head (`tenant_org_id_notnull_001`). No branching.

Revision IDs are capped at 32 chars (`alembic_version.version_num` is `VARCHAR(32)`,
confirmed against the live schema) — my first draft (`tenant_scope_transitive_org_id_*`,
34-44 chars) failed on `alembic upgrade head` with `StringDataRightTruncation` on the very
first `UPDATE alembic_version SET version_num=...`. Transactional DDL rolled the schema
change back cleanly (verified via `\d steps` showing no `org_id` column post-failure), so no
partial state resulted. Renamed to the current `tenant_org_id_*` slugs (21-26 chars) and
re-ran clean.

## Why these tables, why now

`steps` and `execution_steps` previously had no `org_id` column of their own — tenancy was
transitive through a join to their parent (`process_id` → `processes.org_id`, `execution_id`
→ `executions.org_id`). `trusted_devices` and `two_factor_backup_codes` were transitive
through `user_id` → `users.org_id`. This is exactly the shape of the confirmed CRITICAL and
MEDIUM cross-tenant read findings in `.agents/reports/{inventory,execution}/security-audit.md`
— a query fetched or joined one of these tables by ID without also joining back to the
parent's `org_id`, in the same files where a sibling method got it right. Denormalizing
`org_id` closes that structurally: these four tables now carry the same column every other
tenant-scoped table has, and join the global ORM tenant filter
(`app/core/db/tenant_filter.py`) as plain `TenantScoped` models — one uniform equality
filter, no per-table special case.

A correlated-subquery loader-criteria alternative (no schema change) was prototyped instead
of denormalizing and rejected on technical grounds, not just preference: SQLAlchemy's
`with_loader_criteria` lambda-caching layer explicitly rejects a `Session`/`Query` object as
a closure variable (`InvalidRequestError: ... does not refer to a cacheable SQL element`),
which a subquery approach needs. Reproduced in `tests/test_tenant_filter_spike.py`.

## Backfill verification

Row counts (post-backfill, all 4 tables, live test DB):

| table | total rows | rows with org_id | mismatches vs parent org_id |
|---|---|---|---|
| steps | 299 | 299 | 0 |
| execution_steps | 267 | 267 | 0 |
| trusted_devices | 6 | 6 | 0 |
| two_factor_backup_codes | 4900 | 4900 | 0 |

100% backfill coverage, zero drift from the parent's `org_id`, confirmed by direct SQL
(`SELECT count(*) FROM steps s JOIN processes p ON p.id = s.process_id WHERE s.org_id !=
p.org_id` → 0, and equivalent for the other three). Backfill correctness follows from schema
guarantees already in place before this migration: every `steps.process_id`,
`execution_steps.execution_id`, `trusted_devices.user_id`, and
`two_factor_backup_codes.user_id` is `NOT NULL` and FK-enforced, so every row has exactly one
parent to inherit `org_id` from — no NULL/ambiguous cases were possible under the existing
schema, and none were observed.

Not chunked/batched — these are dev/test-scale tables today (largest is 4900 rows). Matches
this codebase's own existing precedent (`add_execution_step_tracking_fields.py`, an
unchunked single-`UPDATE` backfill). Flagged in the migration's own docstring as
straightforward to convert to a batched rewrite later if row counts ever make one
unconditional `UPDATE` risky — not a design commitment against it, just not needed yet.

## up/down/up rehearsal

Run against the live test DB (`workflow-engine-test-db`, shared across worktrees but
confirmed idle/reusable — no errors from concurrent access):

```
uv run alembic upgrade head      # crm_revenue_baseline_target_001 -> ...notnull_001, clean
uv run alembic downgrade -1      # notnull_001 -> backfill_001, clean
uv run alembic downgrade -1      # backfill_001 -> add_001, clean
uv run alembic downgrade -1      # add_001 -> crm_revenue_baseline_target_001, clean
uv run alembic upgrade head      # back to notnull_001 (head), clean
```

Full round trip, no errors, no manual intervention. Post-rehearsal state verified identical
to the first upgrade (schema via `\d`, backfill counts via the table above, re-run after the
second `upgrade head`).

## Models updated to match

`Step`, `ExecutionStep`, `TrustedDevice`, `TwoFactorBackupCode` now inherit `TenantScoped`
(`app/core/db/models/tenant_mixin.py`) instead of `Base` alone. Creation sites updated to set
`org_id` explicitly, mirroring every other `create_*` in the codebase:
- `ProcessRepository.add_step` — already had `org_id` in scope (used for the existing
  `get_process_by_id(process_id, org_id)` ownership check); just threaded it into the `Step(...)`
  constructor.
- `ExecutionRepository.create_execution` — same, `org_id` was already a parameter.
- `TrustedDeviceRepository.create_trusted_device` — did not previously take `org_id`; added
  as a new required parameter. Two call sites updated: `auth_routes.py` (`user_org_id` was
  already in scope from the enclosing 2FA-verification flow) and
  `tests/test_auth_gap_coverage.py` (`org_id` was already in scope from the test fixture).
- `BackupCodeRepository.generate_and_store_codes` and its caller
  `AuthService.generate_backup_codes` — neither previously took `org_id`; added to both, and
  threaded through from `auth_routes.py`'s single call site (`user.org_id` was already
  available on the loaded `User`).

## Related, no migration needed

`EntityEventSummary.org_id` had no `ForeignKey` in the SQLAlchemy model despite the live
schema already enforcing one (`entity_event_summaries_org_id_fkey`, `ON DELETE CASCADE`,
added by the pre-existing `event_sourcing_org_cascade_001` migration) — model/DB drift, not
a gap. Confirmed via `\d entity_event_summaries` against the live test DB before assuming a
migration was needed. Swapping this model to `TenantScoped` only makes the ORM model
correctly reflect schema that already existed; zero migration required. Worth a mention in
the global-wins findings index as a class of drift worth an automated check, separate from
this migration's scope.

## Verdict
Three new revisions, all additive/tightening (no drops, no data loss), real symmetric
downgrades on all three, full up/down/up rehearsed clean against the live test DB, backfill
100% verified with zero parent-org_id drift. No `ALLOW_DESTRUCTIVE` permit needed — nothing
here is destructive per this skill's definition.
