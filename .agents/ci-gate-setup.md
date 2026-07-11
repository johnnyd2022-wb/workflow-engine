# ci-gate — initial setup pass (2026-07-12)

Run in "bare" mode (self-discovery + gap-fill against the existing pipeline), not verify
mode for a specific feature slug.

## Discovery

- DB config: `app/config/<ENVIRONMENT>.ini` `[database]` section (host/port/name/user/
  password), loaded via `app/utils/config_loader.py`. No single `DATABASE_URL` env var.
- Alembic reads the same `.ini` config in `app/core/db/migrations/env.py` — the
  `sqlalchemy.url` placeholder in `alembic.ini` is unused.
- Test config: `ENVIRONMENT=test` selects `app/config/test.ini`. `ci/setup_database.sh`
  waits for the GitLab `postgres` service, sed-patches host/port to match the service
  container, then runs `alembic upgrade head`.
- Existing `.gitlab-ci.yml` already had: `check_dependency_updates` (lockfile freshness,
  not vuln scanning), `ruff`, `unit_tests` (full `pytest tests/` against a real Postgres
  service + Flask server + Node for JS tests), `semgrep`, `semgrep_observability`.
  No Playwright/e2e dependency in the repo yet — no fake e2e job added; `e2e-playwright`
  will bootstrap it the first time a feature chain calls for it.

## What ci-gate added (additive only — no existing job touched)

- `gitleaks` job (security stage, blocking) — secret scanning was entirely absent.
- `pip_audit` job (security stage, `allow_failure: true` for now) — known-CVE scanning
  of resolved dependencies; distinct from the existing lockfile-freshness check. Feeds
  the new `dependency-update` skill.
- `migration_reversibility` job (new `migrations` stage, blocking) — proves
  `alembic downgrade -1` / `upgrade head` round-trips; reuses `ci/setup_database.sh`.
- `.pre-commit-config.yaml`: added `gitleaks` and a local `semgrep` hook alongside the
  existing ruff hooks, so both new CI checks have a fast local mirror.

## Flagged to Johnny, not changed

1. **`ruff` CI job runs `--fix` and `ruff format app/` (mutating), not `--check`.** A
   fixable lint issue gets silently auto-corrected and the job goes green rather than
   failing on unformatted/unclean code reaching the pipeline. This is existing,
   merge-blocking behaviour I did not change without your sign-off — flagging per
   ci-gate's "never weaken/silently change a gate" rule. If you want it strict, swap to
   `ruff check app/` and `ruff format --check app/`.
2. **`pip_audit` starts as `allow_failure: true`.** First run may surface pre-existing
   CVEs in current dependencies with no triage yet. Once `dependency-update` clears the
   initial backlog, flip this to `allow_failure: false`.
3. **Protected branch / merge checks — human-only, pending.** GitLab Settings →
   Repository → Protected branches (protect `main`, push: no one, merge: Maintainers) and
   Settings → Merge requests → Merge checks → enable "Pipelines must succeed". Without
   this, every gate above is advisory only — nothing currently stops a direct push to
   `main` bypassing CI. I did not attempt this via `glab api`; it's a shared-repo
   permissions change and should be a deliberate action, not a side effect of a skill
   install.
