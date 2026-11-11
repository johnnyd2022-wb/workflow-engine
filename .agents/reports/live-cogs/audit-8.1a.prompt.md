# security-tenant-audit + migration-safety — live-cogs 8.1a (MR !689)

Read-only. Worktree /home/johnny/wt-live-cogs, branch feat/live-cogs. Do NOT monitor or wait on
the MR pipeline; just do this audit and report.

Scope: `git -C /home/johnny/wt-live-cogs diff origin/main...HEAD -- app/` (the costing slice,
Core hooks in execution_routes / inventory_repo / step_outputs, access_policy, staff-site
registry, data export, migration `costing_engine_001`).

1. Security / tenancy (repo skill `.claude/skills/security-audit/SKILL.md`, tenant-isolation
   focus): every query org-filtered or composite-keyed; route auth + policy table + feature gate
   ordering; IDOR on lot / entry / execution ids; error handlers leaking internals; the CLI's
   unscoped() use; mass assignment on PUT bodies; DoS via the cost walk (node budget) or large
   bodies; anything a MEMBER / PRODUCTION / custom role can do that the spec's permission matrix
   forbids.
2. Migration safety (`.claude/skills/migration-safety/SKILL.md`): additive only? reversible?
   locks taken on existing big tables (the new UNIQUE on execution_steps: does it need
   CONCURRENTLY or is the table small enough; say which); defaults/backfills; model-vs-migration
   drift; downgrade data-loss guard.

Output: markdown, findings ranked high→low with file:line, concrete exploit or failure, and
fix. Separate sections for security and migration. End with exactly one line:
`VERDICT: clean` or `VERDICT: findings-open`.
