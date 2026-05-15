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

# Tests (requires test DB)
docker-compose -f docker-compose.test.yml up -d
ENVIRONMENT=test uv run pytest tests/ -v
ENVIRONMENT=test uv run pytest tests/test_executions.py -v   # single file

# Database
uv run workflow init-db      # create schema
uv run workflow upgrade-db   # run pending migrations
```

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
