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

**Execution & DAG**: Processes are defined as DAGs of steps. `app/core/backend/dagtraversal.py` walks them. `ApiIdempotencyKey` prevents duplicate operations. `workflow_execution_lineage` tracks parent-child execution relationships.

**Inventory**: Quantity writes require an `InventoryQuantityWriteReason` enum value (guards against untracked mutations). Unit conversion utilities live in `app/core/utils/`. Wastage is tracked in a separate table with batch-based entry hashing for idempotency.

**Security**: Session-based auth + TOTP 2FA (pyotp). CSRF via Flask-WTF — SPAs send `X-CSRFToken` header. Rate limiting via Flask-Limiter is per-route with no app-wide default (`app/api/routes/auth_routes.py:131`): only `/auth/login`, `/auth/signup` and the public `/telemetry*` ingest routes carry a limit. The other `/auth/*` routes do not — notably `/auth/verify-2fa`, an open finding (F6 in `.agents/reports/auth/security-audit.md`). Passwords hashed with bcrypt.

**Database sessions**: Scoped per request; cleaned up in `teardown_appcontext`. All queries are multi-tenant filtered by `org_id`.

**Secrets**: Local dev uses KeePassXC CLI (`scripts/local_secrets.py`). CI/CD uses env vars (`POSTGRES_USER`, `POSTGRES_PASSWORD`).

### Frontend

Vanilla JS SPA — no React/Vue. HTML templates live alongside their feature blueprints (`app/core/frontend/`, `app/features/*/frontend/`). Shared JS/CSS is in `app/ui/shared/`.

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
