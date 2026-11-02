# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

Requires **uv >= 0.11.29** (matches `UV_VERSION` in `.gitlab-ci.yml`) — `uv audit`
(the CI security gate, see `uv_audit` job) doesn't exist before that version. Check
with `uv --version`; upgrade via however you installed it (`pip install --upgrade uv`,
`brew upgrade uv`, or `uv self update` for a standalone-installer uv).

```bash
# Install dependencies
uv sync --extra dev

# Run app (development)
python app/app.py
# or
uv run workflow start

# Lint & format
uv run ruff check app/
uv run ruff format app/
uv run workflow fix-all      # fix all ruff issues

# Preflight (what's actually up: env, DB, app server, herdr, tooling)
python3 scripts/preflight.py          # add --json for machine-readable

# Tests (requires test DB)
docker-compose -f docker-compose.test.yml up -d
uv run pytest tests/ -v
uv run pytest tests/test_executions.py -v   # single file

# Database
uv run workflow init-db          # create schema
uv run alembic upgrade head      # run pending migrations
```

Run pytest from the host with **`ENVIRONMENT` unset**. It resolves to `local`
(`app/utils/config_loader.py:16`), and `local.ini` points at the test database on
`localhost:8401` — the same one `docker-compose.test.yml` starts. Setting
`ENVIRONMENT=test` from a host shell **hangs**: `test.ini` targets
`host.docker.internal`, which only resolves for the test app running inside Docker.

The suite is about 2,400 tests (2026-09-25: `2384 passed, 5 skipped, 7 failed` with
`uv run workflow start` up and Playwright's Chromium installed). With no dev server, the
live-server suites (`pytest.mark.live_server`) and the e2e tests auto-skip with a reason
instead. The 7 failures on plain `main` that day were all known and environmental — five
e2e tests (`tests/e2e/…`, not run by CI's relevant-test selection), the NP3 replay test
(collides with the real Whistlebird tenant in the shared local DB), and `test_ac9` (an
untracked `app/features/dilution_calculator/` left in one checkout). Don't pin an exact
count here again; it rots. See the **suite-warden** skill.

The test PostgreSQL instance runs on port 8401 (`workflow-engine-test` DB, user `workflow_rw`).
`docker-compose.test.yml` sets the password `secret`, but Postgres only applies that when the
volume is first created — an existing volume keeps whatever it was initialised with. The app
doesn't need it spelled out: it loads DB credentials from KeePassXC locally, or from
`POSTGRES_PASSWORD` / `POSTGRES_PASSWORD_TEST` (`app/utils/config_loader.py:213`). For
`psql`, use `PGPASSWORD="$POSTGRES_PASSWORD_TEST"`.

## Rules of the house

These three files are the operating contract. Read the relevant one before acting; don't
restate them here:

- `.agents/autonomy.md` — the MR is the gate. Run to a pushed, verified MR without
  asking. **Never** touch a production DB, merge/approve an MR, push to `main`, deploy, send
  external comms, print secrets, or weaken a gate (delete/loosen a test, suppress a rule)
  to get green.
- `.agents/conventions.md` — code patterns, with file:line evidence. Read it before writing
  feature code. Two parts are stale: §1's "5800-line `backend.py`" (it's ~630 lines and
  shrinking) and §6's "no `conftest.py`" (`tests/conftest.py` and `tests/factories.py` exist).
- `.agents/verification-chain.md` — how every code change is verified, and by which engine.

Code rules that are easy to break:

- New feature code goes in `app/features/<slug>/{routes,services,repositories,models,frontend}/`.
  **Never add to `app/core/backend/backend.py`**: the `backend_size` CI job fails any MR
  that grows it, because routes are being carved out of it into slices.
- Repository methods take `org_id` explicitly and filter inline. There is no shared
  scoping helper. New code reads `g.current_org_id` (a UUID), not `g.org_id` (a str).
  `@requires_org_scope` guards only `org_routes.py`; the tenant middleware does the real
  scoping.
- `inventory_items.quantity` writes go through `app/core/domain/inventory_quantity_guard.py`
  with a reason. No external I/O, HTTP or publishing inside that transaction. Do side
  effects after commit.

## Working alongside other agents

Several Claude and Codex sessions work this repo at once, each in its own worktree, and
they share one test DB and one git stash list. Most past breakage came from that:

- **Compare against `origin/main`, never local `main`.** Local `main` can be dozens of
  commits behind. `git fetch origin main && git rev-list --count origin/main..HEAD`.
- **Never `git stash pop`.** To run a test against old code, swap the files in with
  `git checkout origin/main -- <paths>`, then restore with `git checkout HEAD -- <paths>`.
- **Never `git checkout -f -B <branch>`** on a branch name another worktree may have
  checked out (`git worktree list`). Work detached and `git push origin HEAD:<branch>`.
- **Before you claim a plan item**, search open *and recently merged* MRs for its ID
  (`glab mr list --merged`). Main's checkboxes lag behind the merge queue.
- **Run long waits in the background**: the full suite and pipeline polling. A blocked
  pane stalls the other agents. Exception: in headless `claude -p` runs, keep the turn
  alive with a Monitor, or the process exits before you push.

## Tests and CI: traps

- Run pytest as `env -u ENVIRONMENT uv run pytest ...`. An *empty* `ENVIRONMENT=` breaks
  config loading. A fresh worktree needs `uv sync --extra dev` first. Without it,
  conftest fails on `import factory` and `uv run ruff` picks up a stale system ruff (CI
  uses 0.14.7; to be safe, run `uv run --extra dev ruff`).
- **A branch with a migration gets a private DB. Never migrate the shared :8401 DB**
  (that broke main's deploy on 2026-10-27). `config_loader` appends `_$PYTEST_XDIST_WORKER`
  to the DB name, so: create `workflow-engine-test_<x>`, then
  `PYTEST_XDIST_WORKER=<x> env -u ENVIRONMENT uv run alembic upgrade head` and run pytest
  with the same prefix. Drop that DB once the branch merges.
- The shared test DB holds leaked rows. Before you blame your diff for a red test, run the
  same test on a clean `origin/main`. Known cases: ~39 planning tests (a leftover
  `planning_workflow_settings` row), `tests/test_tenant_filter.py` run alone (fails on
  leaked `test-user-N` emails, passes in the full suite), and the flaky
  `test_changes_feed.py::test_head_query_uses_the_partial_index` (retry the job). Don't
  delete rows you didn't create.
- CI runs in UTC and prod runs in NZ time. Also run date/time-sensitive tests with `TZ=UTC`.
- A fix needs proof: the regression test fails on the old code and passes on the new.
- **A branch push only runs GitLab's `semgrep-sast`** (green in ~50s, proves nothing). The
  real jobs run on the `merge_request_event` pipeline once the MR exists. Read that one:
  `glab api "projects/:id/merge_requests/<N>/pipelines"`.
- `glab mr create --description-file /tmp/...` fails because glab can't see `/tmp`. Use
  `--description "$(cat file)"`, then read the stored body back. Success output doesn't
  prove the body landed.

## Architecture

**Workflow Engine** is a multi-tenant manufacturing/inventory SPA. Tenants are isolated by `org_id` on every database table. Configuration is environment-specific `.ini` files in `app/config/`, selected by the `ENVIRONMENT` env var (`local`, `test`, `production`).

### Request lifecycle

```
HTTP Request
  → Middleware (HTTPS enforce, session security, tenant context → g.current_org_id)
  → @requires_auth → validates session, populates g.current_user
  → @requires_org_scope → validates org membership
  → Route handler → Repository → SQLAlchemy ORM → PostgreSQL
  → Response (JSON API or HTML, with CSP/HSTS headers)
```

### Blueprint structure

- `auth_routes` – `/auth/*` login, 2FA, signup
- `org_routes` – `/org/*` organisation management
- `core_bp` – `/api/core/*` and `/core/*` — processes, executions, inventory (always active)
- `crm_bp` – `/crm/*` — customer management, Xero invoicing (feature flag: `crm_enabled`)
- `compliant` – `/compliant/*`, `/api/compliant/*` — compliance modules, NZ Alcohol first (feature flag: `compliant_enabled`, plus a per-org subscription)
- `operational_cases` – `/core/cases/*`, `/api/core/cases/*` — operational cases (always mounted; access gated per org)
- `process_templates` – industry workflow template catalogue (always mounted; exposure gated per org)

`/workflow-engine/*` is a retired URL prefix (the app now lives under `/core/*`) and `workflow_engine_enabled` is read but never consulted — see `.agents/plans/feature-slicing-plan.md`. Lineage tracing is `/api/core/inventory/trace/*` and `/api/core/sourcemap/*`.

### Key subsystems

**Execution & DAG**: Processes are defined as DAGs of steps. `app/core/backend/dagtraversal.py` walks them. `ApiIdempotencyKey` prevents duplicate operations. Lineage is recorded on the inventory side — `InventoryItem.source_execution_id` / `source_execution_step_id` — not in a separate table (the legacy `workflow_execution_lineage` in `app/initialize.py` has no model and no writer).

**Inventory**: Quantity writes require an `InventoryQuantityWriteReason` enum value (guards against untracked mutations). Unit conversion utilities live in `app/core/utils/`. Wastage is tracked in a separate table with batch-based entry hashing for idempotency.

**Security**: Session-based auth + TOTP 2FA (pyotp). CSRF via Flask-WTF — SPAs send `X-CSRFToken` header. Rate limiting via Flask-Limiter is per-route with no app-wide default (the `limiter` in `app/api/routes/auth_routes.py`): only `/auth/login`, `/auth/signup`, `/auth/accept-invite`, `/auth/verify-2fa`, the contract-manufacturing portal's sign-in, accept, logout and staff-invite routes, and the public `/telemetry*` ingest routes carry a limit. `/auth/verify-2fa` is keyed on the pending account (the IP only when no 2FA login is pending), and five wrong codes also end the pending session (F6 in `.agents/reports/auth/security-audit.md`, patched 2026-09-25, pinned by `tests/test_admin_2fa_policy.py`). Passwords hashed with bcrypt.

**Database sessions**: Scoped per request; cleaned up in `teardown_appcontext`. All queries are multi-tenant filtered by `org_id`.

**Secrets**: Local dev uses KeePassXC CLI (`scripts/local_secrets.py`). CI/CD uses env vars (`POSTGRES_USER`, `POSTGRES_PASSWORD`).

### Frontend

Vanilla JS SPA — no React/Vue. HTML templates live alongside their feature blueprints (`app/core/frontend/`, `app/features/*/frontend/`). Shared JS/CSS is in `app/ui/shared/`.

Settled UI decisions: the sidebar tabs are **Home / Production / Compliance / Sales / Settings**.
"Core" and "Compliant" are plan names for pricing, never tab labels. The left rail
collapses to 80px. Page redesigns use the `page-design` skill, which builds three styles,
with Style 1 matching Home's board layout.

### Any UI or UX change: look at it in a real browser, then iterate

This applies to every change a user can see: templates, CSS, frontend JS, copy, layout,
empty and error states, and any route whose response a page renders. Passing unit tests
and a clean diff don't show that a page works or looks right. Only a browser does.
**Never call UI work done without having looked at screenshots of it.**

1. **Seed, then shoot.** Use the Playwright harness `scripts/ui_shots.py`, which boots
   this checkout's code and signs in through the real login form:
   ```bash
   export UI_SHOTS_HOME=~/.cache/workflow-engine-ui-shots/<page>   # per worktree
   env -u ENVIRONMENT uv run python scripts/ui_shots.py seed stock lineage   # kinds: SEED_KINDS in the script
   env -u ENVIRONMENT uv run python scripts/ui_shots.py shoot OUT --scenarios FILE
   ```
   Scenarios are Python functions taking `(page, out)`. Copy the shape of
   `.claude/skills/page-design/scenarios.example.py`. `shoot` exits 1 if any page logs a
   console error; treat that as a failure, never as noise.
2. **Read every screenshot** with the Read tool, then fix what's wrong. Typical problems:
   overlap, clipping, cramped spacing, misalignment, unclear hierarchy, raw IDs, broken
   empty states. Re-shoot and repeat until nothing is left to fix. A single pass is not
   enough.
3. **Design and shoot every change at three layouts: desktop, laptop and mobile.** A
   change isn't done until it works at all three:

   | Layout  | Viewport | In `ui_shots.py`                               |
   |---------|----------|------------------------------------------------|
   | Desktop | 1440×900 | `DESKTOP`                                      |
   | Laptop  | 1280×800 | no constant; pass `{"width": 1280, "height": 800}` |
   | Mobile  | 390×844  | `PHONE`                                        |

   **On mobile, the page must never scroll sideways.** Wide content reflows, stacks or
   becomes cards; only a deliberately scrollable inner region, such as a wide data table,
   may scroll horizontally. Assert this in the scenario rather than eyeballing it:
   `page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")` must
   be true on every mobile shot.
4. **Cover the states that break.** At each layout, shoot each of these:
   - an empty list and a populated one
   - an error state
   - a long text value
   - the sidebar expanded and collapsed (desktop and laptop)
   - light and dark themes. For dark, set `localStorage.setItem('spa-theme','dark')` and
     reload; `theme()` doesn't survive a reload.

   Judge fixed chrome from viewport shots, not full-page captures.
5. **Prove the behaviour with a Playwright test.** If a change alters what a user can do,
   add or update a test in `tests/e2e/` (see the `e2e-playwright` skill). It must fail on
   the old code and pass on the new. CI runs only the e2e files your diff touches, so run
   it locally and say so in the MR.
6. **Put screenshots in the MR.** Upload them with `ui_shots.py upload`, because `glab`
   can't send multipart. Include before and after for a change, or all three styles for a
   redesign, at desktop, laptop and mobile.
7. **Purge afterwards** with `ui_shots.py purge`. The seeded org lives in the shared test
   DB and breaks tests that count rows unscoped.

The bar is the founder's: "room to breathe", simple, polished, "almost too easy". For a
new page or a redesign, use the `page-design` skill. For a small tweak, follow steps 1–7
directly.

### System-finding module boundary

Product modules own the system-finding content and actions they expose to Core. They emit the generic `CheckResult.data["system_finding"]` and `CheckResult.data["system_alerts"]` contract; Core only renders that contract and must not branch on a product/module check ID. Read `docs/system-findings-module-contract.md` before adding or changing module alerts.

### Testing

Tests use a real PostgreSQL instance (not mocks). The test suite covers execution workflows, DAG traversal, business logic, login/2FA flows, and multi-tenant API isolation. See `tests/TEST_DOCUMENTATION.md` for details.

### Product plan

`docs/source-to-sale-plan.md` is the product roadmap: a checklist with stable item IDs
(e.g. `1.3`, `4.7c`). Before starting product work, check whether it covers the change;
when an MR delivers an item, tick it in the same MR with the MR number. Don't reopen its
"Decisions already made" without the founder.

## Observability

Structured logging (`structlog`, JSON), OpenTelemetry traces/metrics, and privacy-masked
browser RUM (pageviews, dwell, clicks, web-vitals, session replay) are wired into the app
factory and config-driven per environment (`app/config/*.ini`, `[observability]` section).
Same-origin `/telemetry` routes proxy only the specific SDK endpoints needed to Faro and
PostHog — nothing talks to a third-party collector directly.

A full local stack — Grafana LGTM (Loki/Tempo/Mimir/Pyroscope) + Alloy, and self-hosted
PostHog (event capture, session replay, feature flags) — runs via Docker Compose and a CLI:

```bash
uv run workflow observability secrets  # verify required KeePassXC entries exist
uv run workflow observability start    # start the full stack
uv run workflow observability status
uv run workflow observability stop     # stop containers, retain data
```

Stack secrets (PostHog secret key, encryption salt, Grafana admin password) live in
KeePassXC, not plaintext env files — `observability secrets` will tell you what's missing.
Full details, ports, and RUM config reference: `docs/observability-local-dev.md`.

## Founder operating workspace (`.claude/agents/`)

`.claude/agents/` is a separate, unrelated workspace for running the founder's two
businesses (Whistlebird, Biz-E) — project plans, marketing, sales, compliance — not part
of this codebase's engineering surface. Its skills are registered as project-level Claude
Code skills via symlinks in `.claude/skills/` (e.g. `/sales-manager`, `/business-operator`)
so they're invocable from any session in this repo. See `.claude/agents/README.md` for
the full skill roster and `.claude/agents/AGENTS.md` for how those skills should behave.
`.claude/skills/{html,js,python}-review` are this codebase's own review skills and are
unrelated to that workspace. Not sure which of the 38+ registered skills (engineering or
business) fits an ask? `/entrypoint` routes across both.
