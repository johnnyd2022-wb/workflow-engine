# Core-flow test map

Owned by the **test-author** skill. This is a *flow-based* coverage inventory — the core
user journeys through the app, the test files that prove them, and an honest status per
row. It is deliberately not line-coverage: the question is "would a human walking this flow
hit an untested path", not "what percent of lines executed".

`scripts/test_map_check.py` keeps it structurally honest — it flags rows whose test file no
longer exists and `tests/test_*.py` files that appear in no row. It cannot judge whether a
row's **status** is truthful; that is test-author's job to keep current as it writes, and
test-evaluator's to catch when a test claims more than it proves.

last_synced: 2026-07-18
status legend: `covered` (happy + unhappy + isolation where scoped) · `partial` (happy
path only, or missing the hostile-org / unhappy cases) · `none` (no automated pytest
coverage) · `live` (covered only by `live_server`-marked suites that need the dev app
server up)

## Auth & session

| # | Flow | App area | Test file(s) | Status | Notes |
|---|---|---|---|---|---|
| 1 | Signup → account created | `app/api/routes/auth_routes.py` (`/signup`) | test_login_2fa_flow.py | live | driven over real HTTPS server; skips without `uv run workflow start` |
| 2 | Login / logout / `/me` session | auth_routes (`/login`,`/logout`,`/me`) | test_login_2fa_flow.py | live | same live-server gate |
| 3 | 2FA enroll → enable → verify → disable | auth_routes (`/2fa/*`,`/verify-2fa`), pyotp | test_2fa_totp_optimized.py, test_login_2fa_flow.py | live | TOTP time-window logic; both `live_server`-marked |
| 4 | Password policy + change-password | auth_routes (`/password-policy-check`,`/change-password`) | — | none | policy JS served (see safe-flow); server path untested |
| 5 | Session timeout + safe return-to | auth_routes (`/session-timeout`), middleware | test_safe_flow_return_to.py | partial | return-to open-redirect guard covered; timeout PUT not |

## Organisation & tenancy

| # | Flow | App area | Test file(s) | Status | Notes |
|---|---|---|---|---|---|
| 6 | Org read / patch settings | `app/api/routes/org_routes.py` (`GET/PATCH ""`) | — | none | no direct pytest coverage of org CRUD |
| 7 | Org membership (list/add/remove users) | org_routes (`/users`, `/users/<id>`) | — | none | user add/remove path untested |
| 8 | **Tenant isolation — org A cannot read/write org B** | every `org_id`-scoped repository | test_multi_tenant_isolation.py | covered | Batch 2: process/execution/inventory get+list+delete each proven org-scoped, hostile-org case AND same-org control. Built ProcessFactory/ExecutionFactory + a `world` fixture on `two_org_two_user`. Wastage repo → Batch 3. (`test_multi_tenant_api.py` remains a manual `main()` script, kept as a manual tool) |

## Process, DAG & execution

| # | Flow | App area | Test file(s) | Status | Notes |
|---|---|---|---|---|---|
| 9 | Process CRUD + steps (add/reorder/delete) | core_bp `/api/core/processes*` | test_executions.py, test_corechecks.py | partial | CRUD exercised; org-isolation cases thin |
| 10 | DAG traversal | `app/core/backend/dagtraversal.py` | test_dag_traversal.py | covered | 29 tests, cycles + ordering |
| 11 | Execution lifecycle (create → complete step) | core_bp `/api/core/executions*` | test_executions.py, test_complete_step_payload.py | partial | happy path strong; failure/partial-completion cases thin |
| 12 | Idempotency (`ApiIdempotencyKey`) on executions | idempotency key handling | — | none | idempotency tested for CRM only, not execution replays |
| 13 | Execution lineage (parent→child) | `workflow_execution_lineage`, reconciliation_service | test_dag_traversal.py (helpers) | partial | traversal helpers touch it; lineage-record assertions absent |

## Inventory

| # | Flow | App area | Test file(s) | Status | Notes |
|---|---|---|---|---|---|
| 14 | **Quantity-write guard** (every `InventoryQuantityWriteReason`) | `app/core/domain/inventory_quantity_guard.py` | test_inventory_quantity_guard.py | covered | Batch 1: direct write rejected, create/add/set repository paths accepted, nested-allow rejected, guard re-arms. **Found + fixed a real bug**: `set_inventory_item_quantity` flushed its event outside the allow block, so `POST /api/core/inventory/<id>/adjust` raised on every call |
| 15 | Inventory read / add / out-of-stock | core_bp `/api/core/inventory*` | test_corechecks.py | partial | reads covered; write reasons per row 14 |
| 16 | Wastage entry + batch-hash idempotency | core_bp `/api/core/inventory/wastage` | — | none | no wastage test at all; batch-hash idempotency unproven |
| 17 | Unit conversion | `app/core/utils/` | test_execution_modal_frontend_assets.py, tests/js/ | partial | JS-side conversion asserted; server-side utils untested |

## CRM & Xero (feature flag `crm_enabled`)

| # | Flow | App area | Test file(s) | Status | Notes |
|---|---|---|---|---|---|
| 18 | Customers / invoices / notes / tasks | `app/features/crm/routes/api_routes.py` | test_crm.py | partial | 39 tests incl. idempotency; Xero OAuth + authorise/pdf paths mocked-thin |
| 19 | Analytics (sales, churn, rankings) | crm api_routes `/api/crm/analytics/*` | test_crm.py | partial | some analytics endpoints uncovered |

## Dashboard & cross-cutting

| # | Flow | App area | Test file(s) | Status | Notes |
|---|---|---|---|---|---|
| 20 | Dashboard summary | core_bp `/core/dashboard` | test_dashboard_summary.py | partial | 4 tests; single-org only, no cross-org leak test |
| 21 | Core system checks | `app/core/backend/corechecks.py` | test_corechecks.py | covered | 23 tests |
| 22 | Frontend asset/guards (execution modal, batches) | core frontend JS/templates | test_execution_modal_frontend_assets.py, test_batches_refactor_frontend_guards.py, test_execution_shared_utils_js.py | covered | asset-presence + guard tests |
| 23 | Observability (logging/tracing/telemetry ingress/CLI) | `app/observability/*` | test_observability_*.py (10 files) | covered | broad; owned jointly with observability skill |

## Known highest-value gaps (test-author works these first)

1. **Row 8 / 14 / 16** — tenant isolation, the inventory quantity-write guard, and wastage
   idempotency are the three `none` rows guarding the app's core integrity invariants
   (multi-tenancy, untracked-mutation prevention, duplicate-wastage prevention). A break in
   any of them is silent and data-corrupting. These are the highest risk-times-exposure
   rows in the map.
2. **Row 12** — execution idempotency: without it, a retried execution can double-apply.
3. **Rows 6/7** — org CRUD and membership have no direct coverage.

## Not in this map (owned elsewhere)

- Browser / end-to-end journeys → `e2e-playwright` (`.agents/specs/playwright-e2e.md`).
- The 2FA live-server suites' *gating* (when they skip vs run) → `suite-warden`.
- Whether a listed test is a valid claim vs gamed → `test-evaluator`.
