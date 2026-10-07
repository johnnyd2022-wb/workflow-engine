# Production, demo and admin plan

Started 2026-10-07. Goal: Whistlebird runs on a production copy of the app while the test
environment carries on as the development copy; a demo organisation can be reset between
customer demos by someone non-technical; and organisations and users can be managed from
an admin site without the command line.

Status: `[x]` done, `[~]` started, `[ ]` to do. "Owner" is who has to act next.

## The order, and why

1. **Production up with Whistlebird's data** first: it is the only part with real urgency,
   and everything after it runs against a production that already exists.
2. **Demo organisation** second: it is built from the replay, so the replay has to keep
   working until the demo scenario stands on its own.
3. **Admin site** third: its first job is resetting the demo, so it follows the demo.
4. **Retire the Whistlebird replay** last: only once production holds Whistlebird's data
   and has been backed up and restored at least once, and the demo replay covers what the
   Whistlebird replay proved (the real API calls, end to end).

## Phase 1: production with Whistlebird's data

| | Step | Owner |
| --- | --- | --- |
| [x] | **Tenant copy tool** (`scripts/tenant_copy.py`). Copies one organisation between databases: `organisations` plus every table with an `org_id`, filtered to it, verified table by table inside one transaction. A table with no `org_id` is never copied. | done |
| [x] | **Production secrets in KeePassXC** (`scripts/prod_secrets.py`). Generated: database password, session key, 2FA backup-code key, Xero token key. Read by `scripts/run_prod.sh`; never written to a file. Moves to AWS Parameter Store at go-live. | done |
| [x] | **Production database container** (`scripts/prod_db.sh`): PostgreSQL 16 on its own Docker network, data on a named volume, port on loopback only. Commands: `up`, `status`, `backup`, `psql`, `url`. | done |
| [x] | **`scripts/run_prod.sh` rewritten**: loads secrets, builds, backs up (a failed backup stops the deploy), migrates, replaces the app, waits for health. Listens on `127.0.0.1:8010` (8000 belongs to Mission Control). Uploads on named volumes. | done |
| [x] | **`prod.ini`**: database by container name, Xero redirect URI, upload storage on `/data`, Google sign-in off until a production client exists. Observability was already off. | done |
| [x] | **One environment name.** The image and the script both run as `prod` (the config file's name); `is_production` now accepts `prod` as well as `production`. | done |
| [x] | **Backup-code key is mandatory in production**, like the Xero token key already was. | done |
| [x] | **Whistlebird Ltd copied into production**: 6,429 rows across 32 tables, no other organisation, no Xero token, the two `@whistlebird.test` accounts kept but locked. Both NP3 evidence files restored from `docs/evidence/`. | done |
| [x] | **Smoke test on this machine**: health check passes, the admin signs in and is sent to 2FA enrolment, a locked account is refused, pages are protected. | done |
| [ ] | **Confirm the Xero app.** `run_prod.sh` reads `workflow-engine/xero_client_id` and `xero_client_secret` from KeePassXC. Confirm those are the production Xero app and that `https://biz-e.app/crm/xero/callback` is registered on it. | Johnny |
| [ ] | **Route the domain.** Point the Cloudflare tunnel for `biz-e.app` at `https://localhost:8010` (self-signed certificate, so "No TLS Verify" on, as for test). | Johnny |
| [ ] | **First sign-in.** Sign in as `johnny@whistlebird.co.nz`, enrol 2FA, then change the password: it is still the replay's test password. | Johnny |
| [ ] | **Connect Xero in production** and sync, then run `scripts/whistlebird_replay_correct_timestamps.py --sales-only` against production if the sync re-dates sale stock movements to today. | Johnny, then Claude |
| [ ] | **Refresh the copy just before go-live** if more has been entered in test since 2026-10-07: `scripts/prod_seed_from_test.sh "Whistlebird Ltd" --disable-user … --replace`. After go-live production is the source of truth and this is never run again. | Claude, on request |
| [ ] | **Backups on a schedule.** `scripts/prod_db.sh backup` works by hand and runs before every deploy; add a nightly timer and rehearse one restore. | Claude |
| [ ] | **Deploy production from CI** rather than by hand: a manual `deploy_prod` job that pulls the `prod-<sha>` image `main` already builds. Today `run_prod.sh` builds from the checkout. | Claude |
| [ ] | **Secrets to AWS Parameter Store** at go-live; `run_prod.sh` then reads from there instead of KeePassXC. | Johnny to provision, Claude to wire |

### What production looks like now

- Containers: `workflow-engine-prod` (app, `127.0.0.1:8010`) and `workflow-engine-prod-db`
  (database, `127.0.0.1:8432`), both `restart: unless-stopped`, on the Docker network
  `workflow-engine-prod`.
- Volumes: `workflow-engine-prod-db`, `workflow-engine-prod-evidence`,
  `workflow-engine-prod-process-docs`.
- Built from the branch that added this plan. Redeploy from `main` with `scripts/run_prod.sh`.
- Not yet reachable from outside this machine.

## Phase 2: demo organisation

A fictional distillery with a believable history, rebuilt on demand.

| | Step | Owner |
| --- | --- | --- |
| [ ] | **Decide the scenario**: company name, product lines, how much history. Proposal: "Tui Ridge Distilling Co.", two gins and a liqueur, about 18 months of batches, suppliers, customers and sales, one stock write-off, one mock recall, NP3 evidence part-complete so there is something to show in Compliance. | Johnny to confirm |
| [ ] | **Generalise the replay** into a scenario engine: the API client, idempotency markers, step completion, timestamp correction and verification stay; everything Whistlebird-specific (legacy import, production-sheet quirks, named corrections) is left out. Input is one scenario manifest. | Claude |
| [ ] | **Write the demo scenario manifest** with invented suppliers, customers, batches and sales. No real Whistlebird data. Sales come from the manifest directly, since a demo has no Xero. | Claude |
| [ ] | **Reset = wipe and rebuild that one organisation** through the real API, the same way the replay does today. Keeps the property you want from the replay: every rebuild exercises the real endpoints. | Claude |
| [ ] | **Run it in CI** against the test database on `main`, so a change that breaks the API breaks the demo rebuild visibly. | Claude |
| [ ] | **Replace the old demo reset** (`app/features/demo_data`, `demo@whistlebird.co.nz`, local/test only) with this, or keep it as the fast fixture for tests; decide once the new one exists. | Claude to propose |

## Phase 3: admin site (`admin.biz-e.app`)

A separate container, not part of the customer app, for people who are not developers.

| | Step | Owner |
| --- | --- | --- |
| [ ] | **Decisions**: who may sign in (proposal: a short allow-list of platform staff, separate from tenant users, 2FA required); whether it can act on production (proposal: yes, with every action written to an audit log and destructive ones needing a typed confirmation). | Johnny |
| [ ] | **Admin service**: its own container and image target, its own port, talks to the same database through a small set of admin operations shared with the CLI, so the CLI and the site can never disagree. | Claude |
| [ ] | **Screens, first cut**: organisations (list, create, suspend, features on/off), users (list, invite, role, lock, reset 2FA, reset password), demo (reset the demo organisation, see when it was last reset and by whom), system (version deployed, last backup, health). Built from the same shared `workspace-*` elements as the app. | Claude |
| [ ] | **CLI parity**: every admin action available as `workflow admin …` too. `create-org` and `create-user` exist; add the rest alongside the screens. | Claude |
| [ ] | **Cloudflare route** for `admin.biz-e.app` to the admin container, behind Cloudflare Access as a second gate. | Johnny |
| [ ] | **Audit log** of admin actions, visible in the site. | Claude |

## Phase 4: retire the Whistlebird replay

| | Step | Owner |
| --- | --- | --- |
| [ ] | Production has Whistlebird's data, has been backed up, and one restore has been rehearsed. | Claude |
| [ ] | The demo scenario rebuild passes in CI and covers the API calls the Whistlebird replay exercised. | Claude |
| [ ] | Remove `scripts/whistlebird_*.py`, `scripts/replay_whistlebird.sh`, the `docs/whistlebird-*-source.json` manifests and their tests; keep `docs/evidence/` only if production still needs to restore from it. The test tenant's Whistlebird data stays until you choose to drop it. | Claude, after Johnny confirms |

## Open questions for Johnny

1. Is `workflow-engine/xero_client_id` in KeePassXC the production Xero app?
2. Demo scenario: happy with the proposal above, or a different company and product mix?
3. Admin site: who signs in, and may it act on production?
4. `biz-e.app` for production and `admin.biz-e.app` for admin: confirm both names.
