# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

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

Expect `252 passed, 30 skipped` with no dev server running. The 30 skips are the
live-server 2FA suites (`pytest.mark.live_server`), which auto-skip with a reason unless
`uv run workflow start` is up — start it and they run. See the **suite-warden** skill.

The test PostgreSQL instance runs on port 8401 (`workflow-engine-test` DB, user `workflow_rw`, password `secret`).

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
- `workflow_engine_bp` – `/workflow-engine/*` — lineage tracing (feature flag: `workflow_engine_enabled`)

### Key subsystems

**Execution & DAG**: Processes are defined as DAGs of steps. `app/features/workflow_engine/dagtraversal.py` walks them. `ApiIdempotencyKey` prevents duplicate operations. `workflow_execution_lineage` tracks parent-child execution relationships.

**Inventory**: Quantity writes require an `InventoryQuantityWriteReason` enum value (guards against untracked mutations). Unit conversion utilities live in `app/core/utils/`. Wastage is tracked in a separate table with batch-based entry hashing for idempotency.

**Security**: Session-based auth + TOTP 2FA (pyotp). CSRF via Flask-WTF — SPAs send `X-CSRFToken` header. Rate limiting on `/auth/*` via Flask-Limiter. Passwords hashed with bcrypt.

**Database sessions**: Scoped per request; cleaned up in `teardown_appcontext`. All queries are multi-tenant filtered by `org_id`.

**Secrets**: Local dev uses KeePassXC CLI (`scripts/local_secrets.py`). CI/CD uses env vars (`POSTGRES_USER`, `POSTGRES_PASSWORD`).

### Frontend

Vanilla JS SPA — no React/Vue. HTML templates live alongside their feature blueprints (`app/core/frontend/`, `app/features/*/frontend/`). Shared JS/CSS is in `app/ui/shared/`.

### Testing

Tests use a real PostgreSQL instance (not mocks). The test suite covers execution workflows, DAG traversal, business logic, login/2FA flows, and multi-tenant API isolation. See `tests/TEST_DOCUMENTATION.md` for details.

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
