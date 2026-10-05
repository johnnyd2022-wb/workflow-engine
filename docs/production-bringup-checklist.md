# Production bring-up checklist

Written 2026-10-05 from reading the scripts and config, plus read-only checks on this
machine. Nothing here has been changed yet. Work through it top to bottom: each section
says what is missing, why it matters, and what "done" looks like.

The goal: bring production up with the Whistlebird Ltd tenant, and nothing from the test
database that should not be there.

## Decisions needed first

These three answers shape most of what follows.

1. **Is there already a production database for this app?** `app/config/prod.ini` expects a
   database named `workflow-engine` and a role `workflow_rw` at `host.docker.internal:5432`.
   The only Postgres on 5432 here is the `whistlebird_db_prod` container, which sits beside
   the old `wb_inv_prod` inventory app. It has no `postgres` role, so its databases could not
   be listed. Either confirm the database and role exist there, or decide where to create them.
2. **Where do production secrets live?** KeePassXC is only read in `local` (and `test` for the
   session key). Production reads environment variables only. Decide the store (a root-only
   env file on this machine, GitLab CI variables, or similar) and who passes them to the
   container.
3. **What routes the public domain to the container, and on which port?** `prod.ini` and
   `run_prod.sh` disagree on the domain (`biz-e.app` vs `workflow-engine.whistlebird.co.nz`),
   and port 8000 is already in use (see below).

## 1. Secrets and keys that are missing

Production will not start, or will start insecurely, without these. None is passed by
`scripts/run_prod.sh` today, which only sets `ENVIRONMENT=prod`.

| Variable | What happens without it | Notes |
| --- | --- | --- |
| `POSTGRES_PASSWORD` | App refuses to start (`RuntimeError`) | Production never reads the password from `prod.ini`. |
| `FLASK_SECRET_KEY` | App refuses to start | Random, at least 32 bytes. Signs sessions; must be the same for every worker and stable across restarts. |
| `BACKUP_CODE_ENCRYPTION_KEY` | 2FA backup codes are encrypted with a development default | Base64 Fernet key. Set it before the first admin enrols in 2FA; changing it later invalidates stored codes. |
| `XERO_CLIENT_ID`, `XERO_CLIENT_SECRET` | Xero connect fails | `prod.ini` leaves both blank. Use the production Xero app's credentials, not the test app's. |
| `XERO_REDIRECT_URI` | Xero connect fails | `prod.ini` has no `redirect_uri` at all. Must match the URI registered on the production Xero app. |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Google sign-in fails | Known and deferred: no Google tenant wired yet. Either supply them or set `[google_sign_in] enabled = false` in `prod.ini` so the button does not show. |
| `POSTHOG_PROJECT_API_KEY` | No product analytics | Optional. `posthog_data_enabled` is already `false`. |

One more key is not an environment variable:

- **Xero token encryption key.** Stored Xero tokens are encrypted with a key derived from
  `[app] secret_key`. No config file sets it, so every environment falls back to the
  hard-coded string `dev-secret-key-change-in-production`. Set a real `secret_key` for
  production (ideally from an environment variable, which needs a small code change) before
  any Xero connection is made there. Changing it afterwards means reconnecting Xero.

## 2. `scripts/run_prod.sh` fixes

`scripts/git_workflow.sh prod` is the documented deploy path and it calls this script.

- [ ] **Pass the secrets.** Add an `--env-file` (or `-e` for each) to `docker run`.
- [ ] **Port 8000 is taken.** Mission Control's backend listens on `127.0.0.1:8000`, so
      `-p 8000:8000` fails to bind. Pick a free host port and point the proxy/tunnel at it.
- [ ] **Environment name.** The script forces `ENVIRONMENT=prod`; the Dockerfile's production
      target sets `production`. Database-credential handling accepts both, but
      `config.is_production` only matches `production`, so at least one production-only guard
      (wastage error detail) does not apply under `prod`. Only `prod.ini` exists, so pick one
      spelling and make the config filename, the script and the Dockerfile agree.
- [ ] **Database host.** `prod.ini` uses `host.docker.internal`. On native Docker in WSL that
      name does not resolve unless the run adds `--add-host=host.docker.internal:host-gateway`.
- [ ] **Persistent storage.** No volume is mounted. Evidence files and process documents are
      written inside the container (`app/core/evidence_storage`, `app/core/process_docs_storage`)
      and are lost on every redeploy. Mount a host directory and set `[evidence] storage_root`
      and `[process_docs] storage_root` in `prod.ini`.
- [ ] **Backups do not run.** The script calls `~/workflow-engine_backups.sh` and
      `~/workflow-engine_db_backups.sh`. Neither exists, and with no `set -e` the deploy
      carries on without a backup. Restore or replace them, and make a failed backup stop
      the deploy.
- [ ] **Stale message.** The script prints `config/$ENVIRONMENT.ini` and
      `https://workflow-engine.whistlebird.co.nz`; update both once the domain is settled.
- [ ] **TLS.** gunicorn serves a self-signed certificate from `app/tls/` if the files exist
      in the image. Confirm whatever fronts production (tunnel or reverse proxy) terminates
      public TLS and is happy with a self-signed upstream.

## 3. `app/config/prod.ini` gaps

- [ ] `[xero] redirect_uri` is missing.
- [ ] `[evidence]` and `[process_docs]` sections are missing (storage roots, size limits,
      allowed types). They fall back to in-container defaults.
- [ ] `[app]` has no `secret_key` (see the Xero token key above).
- [ ] `[google_sign_in] enabled = true` with KeePass entry names that production cannot read.
- [ ] `[observability]`: `otel_enabled = true` pointing at `localhost:4317`, and
      `rum_enabled = true` with Faro at `localhost:12347` and PostHog at `localhost:8000`.
      Inside the container `localhost` is the container itself, so nothing is collected, and
      `localhost:8000` is the app. Either point these at real collectors or switch them off.
- [ ] `[docker]` names a `workflow-engine-prod-db` container on host port 8432 that is not
      running and does not match `[database] port = 5432`. Reconcile with decision 1.

## 4. Database

- [ ] Create (or confirm) the `workflow-engine` database and the `workflow_rw` role.
- [ ] Create the schema with `uv run alembic upgrade head`. The test database is at the
      current head (`np3_record_files_001`), so there is no version gap to worry about.
- [ ] Decide how production is backed up and rehearse one restore
      (`scripts/db_restore.sh` runs an isolated rehearsal).

## 5. Getting Whistlebird data in: do not copy the test database

A `pg_dump` of `workflow-engine-test` restored into production is easy but wrong:

- It holds **3,811 organisations and 2,944 users**, almost all pytest leftovers, including
  accounts with known test passwords. Whistlebird Ltd is one organisation with 3 users.
- Its Xero token was issued to the **test** Xero app. Production cannot refresh it, and
  while two environments share one refresh token, a refresh on either side can invalidate
  the other.
- NP3 evidence files and process documents are on disk, not in the database, so the
  restored records would point at files production does not have.

**Use the replay instead.** `scripts/replay_whistlebird.sh` builds only Whistlebird Ltd from
the committed manifests under `docs/whistlebird-*-source.json`, including the NP3 evidence
files. It currently assumes a local target, so before pointing it at production:

- [ ] `WHISTLEBIRD_REPLAY_BASE_URL` and `BIZE_MIGRATION_DATABASE_URL` must be set explicitly;
      the default database URL is derived from `local.ini`.
- [ ] The admin password comes from a KeePassXC entry, or `WHISTLEBIRD_ADMIN_PASSWORD`.
      Choose a real production password; do not reuse the replay one.
- [ ] **Admin 2FA blocks the replay.** Production enforces 2FA for admins
      (`require_admin_2fa` is ignored outside local/test), and the replay signs in as an
      admin with no authenticator. This needs a deliberate answer: a one-off bootstrap
      window, or a replay path that can complete 2FA.
- [ ] The timestamp-correction scripts refuse any organisation other than `Whistlebird Ltd`
      by name; keep that name.
- [ ] `--confirm` resets the tenant. On production, only ever run it for the first load.
      Later additions use `--resume`, which adds new history without resetting.

After the replay:

- [ ] Connect Xero in the app with the production Xero app, then sync.
- [ ] Run `scripts/whistlebird_replay_correct_timestamps.py --sales-only` so synced sales are
      dated to their invoices rather than the sync.
- [ ] Each admin enrols in 2FA at first sign-in.

## 6. First-run checks

- [ ] `https://<domain>/healthcheck` answers.
- [ ] Sign in as the Whistlebird admin and complete 2FA enrolment.
- [ ] Dashboard, Production, Compliance, Sales and Settings load with Whistlebird data.
- [ ] Upload an NP3 evidence file, redeploy, and confirm the file is still there.
- [ ] Xero connect and sync complete; Sales analytics shows customers.
- [ ] A backup runs, and a restore rehearsal passes.

## Not a problem

- Schema version: test and code are at the same migration head.
- Feature flags in `prod.ini` already match test (Sales, Compliance and Cases on).
