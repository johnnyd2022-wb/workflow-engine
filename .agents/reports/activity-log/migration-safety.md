# MIGRATION SAFETY: activity-log
date: 2026-08-09
verdict: clean (static audit only — live up/down/up not run, see below)

This review made no schema changes (the fix was a query filter, not a model/migration
change), so this is an audit of the *existing* migration history for this slice's three
tables, not a review of a new migration.

## Migrations touching entity_events / entity_event_summaries / audit_logs

| revision | down_revision | table(s) | upgrade | downgrade |
|---|---|---|---|---|
| `0e781c27351d` (initial schema) | `None` | `audit_logs` (create) | creates table + 4 indexes | drops 4 indexes + table — symmetric |
| `event_sourcing_core_001` | `wastage_reason_001` | `entity_events` (create) | creates table, self-referential FK, 7 indexes | drops all 7 indexes, the FK, then the table — symmetric |
| `event_sourcing_summaries_001` | `event_sourcing_core_001` | `entity_event_summaries` (create) | creates table (entity_id PK, org_id FK) + 2 indexes | drops both indexes + table — symmetric |
| `event_sourcing_org_cascade_001` | `event_sourcing_proc_ver_001` | `entity_events`, `entity_event_summaries` (alter) | drops+recreates both org_id FKs with `ondelete="CASCADE"` | drops+recreates both FKs without cascade — symmetric, restores exact pre-upgrade constraint |
| `org_fk_cascade_users_audit_001` | `crm_sales_trace_cfg_001` | `users`, `audit_logs` (alter) | drops+recreates both org_id FKs with `ondelete="CASCADE"` | drops+recreates both FKs without cascade — symmetric |

All five have a real `downgrade()` (no stub/`pass` bodies), and each downgrade reverses
exactly what its own upgrade did — no destructive change with a missing or partial permit.
`entity_event_summaries.entity_id` being the table's primary key (not `org_id` or a
composite) is confirmed at the migration level (`event_sourcing_summaries_001.py:27`),
matching the model and explaining why F1 (security-audit.md) was possible: the table's own
schema never enforced tenant scoping structurally — that was always the query layer's job,
and one query forgot it.

## What was not done: live up/down/up

`migration-safety` normally verifies reversibility by actually running
`alembic downgrade -1 && alembic upgrade head` (or similar) against the test DB. Not run
here: `alembic current` on this worktree fails —

```
ERROR [alembic.util.messaging] Can't locate revision identified by 'tenant_org_id_notnull_001'
```

— because the shared test DB (`localhost:8401`, used by every concurrent `review/*`
worktree today, confirmed via `docker ps`) has its `alembic_version` pointing at a revision
that exists in some *other* worktree's in-flight branch, not in this one's migration files
(`alembic heads` here resolves to `crm_revenue_baseline_target_001`, no relation). Running a
live downgrade/upgrade cycle against a DB in an unknown foreign state risks stepping through
migrations relative to a revision this worktree doesn't recognize, which could disrupt the
other concurrent review sessions sharing that same database — a shared-infrastructure action
outside this review's blast radius to take unilaterally. Flagged for the user: this is an
environment/worktree-coordination issue (multiple `review-feature` runs sharing one test DB
container), not a defect in any of the five migrations audited above, and not something to
resolve by force-stepping the shared DB mid-review.

not_verified: live up/down/up reversibility (static read of upgrade/downgrade pairs only,
per the above).

VERDICT: clean
