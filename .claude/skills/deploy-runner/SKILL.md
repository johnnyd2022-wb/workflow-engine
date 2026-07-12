---
name: deploy-runner
description: "Technical half of shipping: cut the release tag, run the deploy, post-deploy smoke test against the live environment (reusing the e2e suite), and a rehearsed rollback if the smoke test or healthcheck fails. Hands off to release-manager for readiness sign-off, release notes, changelog, and marketing/sales comms — this skill does not write any of those. Use this skill when the user says 'deploy this', 'ship to prod/test', 'roll this back', or when release-manager's readiness checklist reaches go and needs the technical deploy executed."
---

# Deploy Runner

Named to keep ownership obvious next to **release-manager** (founder ops workspace),
which already owns the pre-release checklist, go/no-go call, release notes, customer
changelog, and downstream marketing/sales handoff — do not duplicate any of that here.
This skill owns exactly the technical mechanics: tag, deploy, prove it worked, and be
able to undo it fast if it didn't.

## Division of labour

| | release-manager | deploy-runner |
|---|---|---|
| Go/no-go decision | ✓ owns it | consumes it — never deploys without a stated go |
| Pre-release checklist | ✓ | — |
| Cut the tag, run the deploy | — | ✓ |
| Post-deploy smoke test | — | ✓ |
| Rollback execution | — | ✓ |
| Release notes / changelog | ✓ | — |
| Marketing/sales handoff | ✓ | — |

Call order: release-manager's readiness report reaches **go** → deploy-runner executes
→ deploy-runner reports success/failure back → release-manager writes notes/changelog
and triggers downstream comms only after a confirmed-healthy deploy.

## 0. This repo's existing deploy mechanism — extend it, don't replace it

`scripts/git_workflow.sh` already does tagging and deploy for this repo:
`./scripts/git_workflow.sh {test|prod|status|restore-db}`. `deploy_prod()`
(`scripts/git_workflow.sh:99-144`) already: checks out `main`, runs the pre-deployment
test suite, tags `prod-<timestamp>`, runs `scripts/run_prod.sh`, waits for a healthcheck
on port 8000, and only pushes the tag to origin once the healthcheck passes. Production
is `https://workflow-engine.whistlebird.co.nz`. Use this script as the deploy step below
— do not hand-roll a parallel deploy path.

**What it doesn't have, and what this skill adds:** a post-deploy smoke test beyond the
bare healthcheck, and any rollback procedure at all — there is no `rollback` command in
`git_workflow.sh` today.

## 1. Tag and deploy

```bash
./scripts/git_workflow.sh prod
```

This blocks until the healthcheck passes or fails and exits non-zero on failure (local
tag is deleted automatically in that case — see `git_workflow.sh:142-143`). Do not
proceed to step 2 if this step failed; there is nothing live to smoke-test.

For a test-environment deploy ahead of a prod release: `./scripts/git_workflow.sh test`.

## 2. Post-deploy smoke test — reuse the e2e suite, don't write a new one

Point the **e2e-playwright** suite's critical-path tests (signup/login smoke +
whatever flows this release touched) at the just-deployed URL instead of the local test
server:

```bash
E2E_BASE_URL=https://workflow-engine.whistlebird.co.nz \
  ENVIRONMENT=production \
  uv run pytest tests/e2e -k "smoke or <slug>" -q --tracing=retain-on-failure
```

Never run destructive or data-seeding E2E tests against production — smoke tests here
are read-only/idempotent flows only (login, load dashboard, view a known record); the
cross-tenant probe and any test that creates rows stays test-environment-only. If the
release has no E2E coverage yet for what changed, that's a gap to report, not a reason
to skip smoke testing what does exist.

## 3. Rollback — rehearsed, not just documented

Because `git_workflow.sh` has no rollback command, this is the procedure until one gets
built into the script itself:

```bash
# 1. Find the last known-good tag
git tag -l 'prod-*' --sort=-creatordate | head -5

# 2. Check out that tag and redeploy through the same path (not a manual docker command —
#    keep using run_prod.sh so config/healthcheck behavior matches a normal deploy)
git checkout <last-good-tag>
./scripts/run_prod.sh

# 3. If the failed release included a migration, downgrade first (check
#    .agents/specs/<slug>.md's Data model section, or `alembic history` since the last
#    good tag)
ENVIRONMENT=production uv run alembic downgrade <revision-before-this-release>

# 4. Re-run the healthcheck the same way deploy does
```
Return to `main` (`git checkout main`) once the rollback is confirmed healthy — don't
leave the working tree on a detached tag.

**"Rehearsed" means tested, not just written down.** Run this procedure for real against
the test environment at least once (`git_workflow.sh test`, break something on purpose,
roll it back) before trusting it in a real prod incident, and note the date it was last
rehearsed in this file's own changelog below. A rollback procedure nobody has run is a
guess with extra steps.

**Last rehearsed:** not yet — first real run is owed before this skill is trusted for a
live incident. Whoever runs it next updates this line with the date and outcome.

## 4. Report back to release-manager

```markdown
# DEPLOY: <tag> <environment>
date: <date>
tag: prod-<timestamp>
healthcheck: pass
smoke_test: <n>/<n> pass, tests: [...]
rollback_available: yes (last-good tag: prod-<...>)
verdict: healthy | rolled-back | degraded
```

Hand this to **release-manager** as the technical confirmation it needs before writing
release notes/changelog and triggering marketing/sales handoffs — it should never
announce a release that hasn't smoke-tested healthy.

## Rules

- Never deploy without release-manager's stated go — this skill executes, it doesn't
  decide readiness.
- Never smoke-test with anything that mutates production data beyond what a real user
  action would (no bulk creates, no cross-tenant probes) — read the flow before pointing
  it at prod.
- A failed healthcheck or failed smoke test is a rollback trigger, not a "monitor and
  see" — roll back first, diagnose after, especially outside business hours when no one
  is watching dashboards.
- If the rollback procedure itself has never been rehearsed, say so plainly when
  reporting deploy readiness; an untested rollback is a real gap, not a formality.

## Handoffs

- ← **release-manager**: go/no-go, migration/rollback-plan sign-off from its checklist.
- → **release-manager**: deploy report (healthy/rolled-back), feeding release
  notes/changelog and the downstream marketing/sales trigger.
- ← **e2e-playwright**: reuses its suite for the smoke-test step; does not maintain a
  separate smoke suite.
- ← **fix-bug**: an incident that triggers a rollback becomes a fix-bug front-door entry
  once the immediate fire is out.
