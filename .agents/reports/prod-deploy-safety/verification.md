# Production deployment safety verification

Date: 2026-10-27
Branch: `fix/prod-deploy-safety`

## Scope and acceptance

Claude's pane `w29:p1` showed the founder accepted two proposed changes before Claude
hit quota: require clean current main and retain the running old app until a new
candidate is healthy. The user explicitly assigned the implementation takeover here.
No relevant unfinished edits existed in Claude's checkout; its unrelated dirty files
were left untouched. This change uses the existing deployment scripts, not a new deploy
path. It does not deploy, merge, access production, or migrate a shared database.

Acceptance: dirty/stale/unknown source aborts before secrets or Docker; a backup failure
aborts before migrations; candidate failure leaves the old app serving; handover failure
returns nonzero and restores the old container; successful deploy retains a stopped
previous container. The documented port handover includes a short interruption.

## Evidence

- `uv run pytest --noconftest tests/test_prod_deploy.py tests/test_prod_config_bringup.py -q`:
  **33 passed**, 17.90 seconds (26 deployment orchestration cases plus 7 config checks).
  Disposable real Git repositories, real shell scripts, fake Docker/curl/secrets only.
  `--noconftest` avoids unrelated application/database fixture initialization.
- `uvx --from shellcheck-py shellcheck scripts/run_prod.sh scripts/prod_db.sh`: clean.
- `bash -n scripts/run_prod.sh scripts/prod_db.sh`: clean.
- Ruff check and formatting of `tests/test_prod_deploy.py`: clean.
- `uv run semgrep scan --config=auto --error scripts/run_prod.sh scripts/prod_db.sh tests/test_prod_deploy.py`:
  293 rules, 3 targets, zero findings.
- `git diff --check`: clean.

Coverage includes staged/unstaged/untracked changes, stale/ahead main, unavailable
origin, corrupt index, changed files or commit during build, detached current main,
failed secret export/build/backup/archive validation/migration/candidate check,
first deploy, successful replacement, final port-bind/health failure, stop failure,
interruption during final startup and rename, rename failure, concurrent deploy lock,
backup permissions, and removal of incomplete dumps.

## Read-only review

A separate inherited-model subagent reviewed scripts, tests, and recovery instructions
without editing them. This is a same-engine fallback, not an independent model review.
Initial review found a P2 interruption gap between Docker rename and recording rollback
state, and a stale legacy entrypoint in the deployment skill. Both were fixed; the
original interruption reproduction is now a regression test. Second review: **clean**,
26 deployment tests passed and shell syntax clean. No production/Docker access.

## Limits and operational follow-up

This is shell orchestration verification, not a live container rollback rehearsal.
No production credentials, production database, or real Docker daemon were used.
Archive listing is not full restoration. App rollback does not reverse migrations;
backward-compatible schemas remain required while old/new apps coexist. Candidates
share the real database/upload volumes. The deploy lock covers one account on one host,
not other operators/tooling. SIGKILL/host/daemon failure can bypass cleanup. Previous
containers/images require manual cleanup after acceptance. A full restoration/recovery
rehearsal and functional smoke test remain human operational work.

No application feature, UI, tenant query, schema, or performance path changes; browser,
application migration, and UX review stages are not applicable to this script-only scope.
Exact-head GitLab CI results are recorded in the MR after pushing, not predicted here.
