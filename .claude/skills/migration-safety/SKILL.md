---
name: migration-safety
description: "Write, review, and gate Alembic database migrations so schema changes are reversible and data is never destroyed by an agent. Use this skill whenever models change, a migration is created or edited, the user mentions alembic, schema changes, or dropping/renaming columns or tables, and whenever new-feature detects data model changes in the spec. Data loss is the one mistake an agent can make that cannot be undone; this skill exists so it never gets the chance."
---

# Migration Safety

Every other agent mistake is recoverable: bad code gets reverted, bad tests get rewritten. A dropped column in production is gone. So migrations get the strictest rules in the repo, and the rules are enforced by CI (the up/down/up job from ci-gate), not by promises.

## 1. Writing a migration

Generate, never hand-write from memory:

```bash
alembic revision --autogenerate -m "<slug>: <what changed>"
```

Then read the generated file line by line; autogenerate misses renames (it emits drop+add, which destroys data) and gets server defaults wrong. Requirements for every revision:

- **Real downgrade.** `downgrade()` genuinely reverses `upgrade()`. `pass` or `raise NotImplementedError` in downgrade fails review; if a change is truly irreversible, that is a destructive migration and follows section 2.
- **Expand-contract for renames and type changes.** Never rename in place. Add the new column, backfill, switch code to write both then read new, and only drop the old column in a later revision after the code no longer references it. Same pattern for tightening types or constraints.
- **Nullable-first for new NOT NULL columns.** Add nullable with no default lock risk, backfill in batches, then add the constraint in a follow-up revision. A NOT NULL with DEFAULT on a big table takes a long lock; on a pre-launch DB it is habit-forming to do it right anyway.
- **No data edits hidden in schema migrations.** Backfills live in their own revision (or a management command), batched, idempotent, and re-runnable.
- **One concern per revision.** Small revisions make up/down/up meaningful and rollbacks surgical.

## 2. Destructive changes need a signed permit

Destructive = DROP TABLE, DROP COLUMN, data-losing type change, DELETE/TRUNCATE, or removing a constraint that guards integrity. An agent never ships one on its own initiative. Process:

1. Write the migration but include a guard at the top of `upgrade()`:

```python
import os
if os.environ.get("ALLOW_DESTRUCTIVE") != "<revision_id>":
    raise RuntimeError(
        "Destructive migration <revision_id> requires ALLOW_DESTRUCTIVE=<revision_id>. "
        "See .agents/reports/migrations/<revision_id>.md"
    )
```

2. Write the permit file `.agents/reports/migrations/<revision_id>.md`: what is destroyed, why, what backs it up, and the restore path.
3. Get explicit user approval in conversation before merging. The env-var guard means even a merged destructive migration cannot fire by accident in a deploy script.

## 3. Verify (the gate)

Locally against a scratch database, never a shared one:

```bash
alembic upgrade head
alembic downgrade -1
alembic upgrade head
```

Up, down, up proves reversibility instead of asserting it. Then for tables with a backfill, spot-check row counts and a sample row before/after. Confirm ci-gate's `migrations` job exists and includes this new revision on the chain (`alembic history`). Multiple heads (`alembic heads` shows more than one) block everything until merged with `alembic merge`.

## 4. Report

Append to `.agents/reports/<slug>/migrations.md`: revision id, tables touched, destructive yes/no (with permit link), up/down/up result, backfill verification. new-feature and review-feature read this to decide whether the data layer is green.

## Rules

- Never run alembic against a production DATABASE_URL from an agent session — this is absolute (`.agents/autonomy.md`: production databases are never touched, in any mode, attended or not). If the only configured URL looks production-like, stop and report; do not look for a way around it. `python3 scripts/preflight.py --json` reports `environment.is_production` and `decisions.db_writes_allowed` if you need to check.
- Never edit an already-applied revision; add a new one.
- Backups are the user's confirmation to give — and this does **not** block an unattended run, because an agent's up/down/up rehearsal happens against the local/test database, where the blast radius is a container. What it blocks is the *human's* first destructive migration in a real environment: flag it in the MR description ("this migration drops `x`; confirm your restore story before deploying") so the confirmation happens where the deploy decision does. An untested backup is a hope, but it is a hope about an environment agents don't run in.
