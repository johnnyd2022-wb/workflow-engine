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
  First run (`gitleaks detect --source .`, full history) found 20-32 pre-existing
  findings in git history (count varies with clone depth), none introduced by the
  branch that added this job — confirmed by scoping to just that branch's commits
  (`--log-opts="main..HEAD"`): 0 leaks. Rather than weaken the gate, the job is scoped
  to only the commits each MR actually introduces
  (`$CI_MERGE_REQUEST_DIFF_BASE_SHA..$CI_COMMIT_SHA`, `GIT_DEPTH: 0` so that range
  always resolves) — it stays a real blocking gate for new secrets without dragging
  every future MR down on a backlog nobody in that MR created. Full-history findings
  (20, as of 2026-07-12) are a separate one-off triage — see below.
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

   **RESOLVED (2026-07-20), partially, on Johnny's explicit go-ahead:** `main` is now a
   protected branch (`push: no one`, `merge: Maintainers`, via `glab api
   projects/:id/protected_branches`) — done specifically because the Socket supply-chain
   job needs a protected CI/CD variable, which GitLab only exposes on protected branches
   (see `chore/socket-supply-chain-scanning`'s `.gitlab-ci.yml` comment). The other half
   of this item — Settings → Merge requests → Merge checks → "Pipelines must succeed" —
   is **still not done**; ask before assuming it's covered.
4. **Full git-history gitleaks findings — still pending triage, not touched.** 20 findings
   (full-history scan, redacted values, 2026-07-12); 3 allowlisted in `.gitleaksignore`
   per Johnny's call the same day (`tls/wb_cert.key`, `config/local.ini`,
   `config/test.ini` — by design, not production credentials), **17 remain open**.
   Roughly by apparent severity:
   - Likely genuine, worth checking/rotating: `tls/wb_cert.key` (a TLS private key
     committed 2025-06-27); `config/{local,test,prod}.ini` line 16, a `generic-api-key`
     match in all three environments incl. prod (commit `3a5001c`, 2025-09-24, plausibly
     the Xero `client_secret`); `ci/scripts/production/prod_container.sh` and
     `ci/scripts/test/test_container.sh` (both a `gitlab-pat` and `generic-api-key`
     match, commit `713e7d2`, 2025-09-24); old backup/diff files `app.py.bak`,
     `app.py.xero_processing_updates_in_progress`, `app.diff` (commits `05aaee7`/
     `713e7d2`) carrying what looks like a real key inline even though later cleaned
     from HEAD — still live in history either way.
   - Likely false positives, lower urgency: `.claude/skills/python-review/SKILL.md`,
     `.cursor/rules/python-review.mdc`, `.agents/skills/python.md` (all `generic-api-key`,
     2026-05-02/03) — plausibly an example key format in documentation prose, not a real
     credential; worth a quick look, not a fire.
   No rotation or history rewrite attempted — deliberately a human decision, not a side
   effect of installing skills.
