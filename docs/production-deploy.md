# Production deployment safeguards

Run `scripts/run_prod.sh` from a clean checkout whose HEAD equals `origin/main`.
The script fetches main itself and refuses staged, unstaged, or untracked files,
unavailable origin, or a different commit. Detached HEAD at current main is allowed.
It neither checks out, resets, nor stashes the operator's work. It checks again after
building, before starting the database or taking a backup, and rejects a changed commit
even if that commit is now current main. Treat the checkout as
read-only during a deployment; Git checking cannot prevent a concurrent editor.

The deployment is still a **human action**. Nothing in this change deploys production.
For an isolated checkout, a human can use:

```bash
git fetch origin main
git worktree add --detach ../workflow-engine-prod-deploy origin/main
cd ../workflow-engine-prod-deploy
scripts/run_prod.sh
```

Use `PROD_HOST_PORT` to override the default loopback-only port, 8010. The tunnel
must point to that same port. Docker, Git, Python 3, curl, and `flock` are required.
One lock under `$HOME/.cache/workflow-engine/` serializes deployments across worktrees
for the same operator. Use a single deployment account: this is not a cross-user or
cross-host deployment lock. Do not run other deployment tooling concurrently.

## Backup and migration

Secrets come from KeePassXC. A failed secret export, image build, database startup,
`pg_dump`, or archive listing aborts the deployment. A custom-format dump is taken
**every time**, including for a database without Alembic metadata. It is saved under
`~/db-backups/workflow-engine-prod/` (override with `PROD_DB_BACKUP_DIR`) with a unique
name and mode 0600. Failed dumps are removed. The deploy prints its path only after
`pg_restore -l` succeeds, then runs migrations using the new, uniquely tagged image.

Archive listing checks readability; it does **not** prove full restoration.
This deployment does not upload backups off-host or schedule retention. See
[database recovery](database-recovery.md) and `scripts/prod_backup.sh` for the separate
recovery and backup processes.

## Candidate and handover

The old app keeps serving through the build, backup, migrations, and candidate check.
The candidate uses the same new image, configuration, network, and upload volumes as
the replacement, with no published host port and no restart policy. Its internal HTTPS
health endpoint checks application startup and database connectivity. Each probe has a
five-second timeout, with up to 60 attempts two seconds apart.

Once the candidate is healthy, it is removed, the existing app is renamed and stopped,
and the new app starts on the existing loopback port. This is a **brief interruption**,
not a zero-downtime switch. The second startup and the published endpoint must pass
health checks too. A health check is not a full functional smoke test.

A failed candidate leaves the old app untouched. A failure or INT/TERM signal during
handover removes the failed replacement, restores the old container's name, restarts
it, and checks its published health endpoint. The deploy still exits nonzero. Failed
recovery prints `CRITICAL` and requires manual intervention. A first deployment has no
old app to restore. SIGKILL, power loss, or Docker daemon failure can bypass cleanup.

**Migrations are not reversed.** The old app runs against the migrated schema during
candidate checks and after rollback. Releases therefore need backward-compatible
migrations. Destructive migrations require a separately planned maintenance/recovery
procedure. Database restoration must account for writes made after the backup.
Candidates also connect to the real database and share upload volumes: startup hooks
must be safe while two app containers coexist.

## Manual app recovery after a successful deploy

The successful deploy prints the stopped previous container name
`workflow-engine-prod-previous-<release>`. It retains the previous image, environment,
port bindings, restart policy, and mounts. After checking schema compatibility, a human
can restore it without rebuilding an old checkout:

```bash
# Replace PREVIOUS_CONTAINER with the exact name printed by the deploy.
docker stop workflow-engine-prod
docker rename workflow-engine-prod workflow-engine-prod-failed-UNIQUE
docker rename PREVIOUS_CONTAINER workflow-engine-prod
docker start workflow-engine-prod
curl --max-time 5 -kfs https://127.0.0.1:8010/healthcheck
```

Use the configured port if different. Keep the failed container for diagnosis and
check real login/application flows before declaring recovery complete. Checking out
an old tag and calling `run_prod.sh` is deliberately refused by the current-main guard.
Remove retained stopped containers and unused release images manually after acceptance;
the deploy does not prune recovery artifacts automatically. Host failure recovery and
a full real-world rollback rehearsal remain operational work.

## Automated evidence

`uv run pytest --noconftest tests/test_prod_deploy.py -q` runs the real deployment and
backup shell scripts in disposable Git repositories against a fake Docker command.
It exercises source guards, backup failures, migration/candidate failures, successful
first/replacement deploys, interrupted/failed handover, and restoration of the old
container. It uses no production secrets, Docker daemon, or database. This verifies
orchestration; it is not a live production deployment or a real container rehearsal.

## Manual staging deployment

`scripts/run_test.sh` now uses the same shared checkout, backup, candidate, and app
rollback helpers (`scripts/deploy_common.sh`). It requires clean current main, checks
again after building, and holds a separate `test-deploy.lock` for the same operator.
Staging and production have separate container names, images, backup directories,
ports, credentials, and locks; neither can replace the other's app.

The manual staging path:

1. Resolves the test session/Google/database credentials before changing Docker.
   `POSTGRES_PASSWORD_TEST` takes priority over `POSTGRES_PASSWORD`; absent both,
   the test config loader resolves the password as before. Optional Xero credentials
   default to empty and telemetry lookup is best-effort.
2. Builds `workflow-engine:test-<release>` while the old app remains running.
3. Requires the existing `workflow-engine-test-db` container to be running and creates
   a private, validated dump under `~/db-backups/workflow-engine-test/` (override with
   `TEST_DB_BACKUP_DIR`). It never recreates or restores the shared development/test DB.
4. Ensures the `workflow-observability` network exists and runs migrations with the new
   image. An unknown branch-only migration aborts; the deploy never automatically
   downgrades the shared database. The host-gateway alias lets the image reach the
   configured test database port 8401 on Linux Docker.
5. Checks an internal candidate on 8001, then hands over `127.0.0.1:8001` (override the
   host port with `TEST_HOST_PORT`) with the same app rollback and retention behavior
   described above. Point the staging tunnel at this loopback endpoint.

Run from a clean current-main checkout:

```bash
scripts/run_test.sh
# Optional: TEST_HOST_PORT=8011 scripts/run_test.sh
```

For manual recovery, use the previous staging container name printed by this script,
replace `workflow-engine-prod` with `workflow-engine-test` in the recovery commands
above, and check the configured staging port. The same migration/host-failure caveats
apply. Staging's existing container-local upload storage remains unchanged; the backup
here is PostgreSQL only, not uploaded files.

This change covers **human-triggered `run_test.sh`**. Registry-based CI still calls
`scripts/deploy_test_simple.sh` with a tested image ref and has its own `:test-stable`
rollback pipeline. That path does not use these new helpers or this lock. Do not run a
manual staging deployment concurrently with CI deployment. This change does not deploy
staging or migrate the shared database during development/testing of the scripts.
