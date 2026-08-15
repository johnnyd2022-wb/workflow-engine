# SPEC: crm
status: reviewed
name: CRM (Customers & Xero)
slug: crm
blueprint: app/features/crm/
url_prefix: /crm, /api/crm, /crm/xero

## Description
Customer relationship + invoicing integration layered on top of Xero. Customers, invoices,
and payment terms are sourced from a one-way OAuth2 sync from a connected Xero
organisation — this app never creates Xero contacts, only invoices against contacts that
already exist there. On top of the synced Xero data it adds app-native CRM objects (notes,
tasks, product-to-Xero-description mappings, a sales-traceability matching config) and
sales analytics (monthly revenue, customer/product rankings, churn risk).

Gated behind the `crm_enabled` feature flag — the only flag in the app that gates an entire
blueprint's registration (`app_factory.py:112`), not a per-route check. ASSUMPTION: because
the flag gate is structural (blueprint never registered when off), no individual route
needs its own flag check, and none has one.

## Provenance
ASSUMPTION: reconstructed 2026-08-15 from code — no prior `.agents/specs/crm.md` existed.
Feature index (`.agents/feature-index.md` → `## crm`) already documents this as "ALREADY
CORRECTLY SLICED... the reference layout for the whole carve" and notes it talks to a real
external API with its own token-refresh and sync-job retry table.

## Users & permissions
Any authenticated member of an org (`@requires_auth`) may read/write that org's CRM data.
No role gate beyond org membership — same permission model as the rest of core tier.
Tenant scoping is defense-in-depth: every CRM model is `TenantScoped` (global ORM filter,
`app/core/db/tenant_filter.py`), every repository method also takes and filters on
`org_id` explicitly, and `g.org_id`/`g.current_org_id` are populated unconditionally by
`tenant_context` middleware before any route body runs (there is no per-route
`@requires_org_scope` call in this codebase outside `org_routes.py` — that decorator is not
the mechanism tenant isolation actually relies on here).

## Acceptance criteria

### OAuth connect/disconnect (`app/features/crm/routes/oauth_routes.py`)
- `GET /crm/xero/auth` — starts OAuth2 flow: generates a CSRF `state`, stores it in the
  session, redirects to Xero's authorize URL. If `xero_client_id`/`xero_redirect_uri` are
  not configured, redirects to `/crm/configuration?error=xero_not_configured` instead of
  erroring.
- `GET /api/crm/xero/auth-url` — same as above but returns `{"auth_url": ...}` JSON for a
  client-side redirect, with cache-busting headers. Same not-configured fallback as a 400
  JSON error.
- `GET /crm/xero/callback` — exchanges the code, validates `state` against the session
  (mismatch → redirect with `xero_state_mismatch`, never proceeds), fetches the tenant
  connections. One connection → auto-connects and kicks off a synchronous full sync.
  Multiple connections → stores tokens against the first connection as a placeholder,
  stashes only non-sensitive connection metadata (id/tenantId/tenantName/tenantType) in
  the session, redirects to the tenant picker. Any exchange/connection-fetch failure
  redirects to `xero_exchange_failed`, never 500s to the user.
- `GET`/`POST /crm/xero/select-tenant` — tenant picker page and submit handler for the
  multi-tenant case. Submitting an unlisted `tenant_id` re-renders the picker with an
  error, does not silently connect the wrong tenant.
- `GET /api/crm/xero/status` — connection status: `connected`, tenant name/id, last sync
  time, contact/invoice counts. Touches token validity so a near-expiry token gets
  refreshed on ordinary status checks, not just on sync.
- `POST /api/crm/xero/sync` — manual sync, `?mode=incremental` (else full). Full is the
  default because it's the only mode that reconciles deleted/missing Xero invoices.
  Returns `{ok, contacts_synced, invoices_synced, errors}`. Expired token → 401
  `reconnect_required`; insufficient Xero scope → 401 `xero_insufficient_scope` with
  `action: reconnect_xero`; any other failure → 500 with a message, never a bare 500 with
  no body.
- `POST /api/crm/xero/disconnect` — revokes the refresh token at Xero (best-effort — a
  revocation failure still disconnects locally), invalidates the stored token, marks the
  tenant disconnected. Idempotent-ish: never blocks on Xero being unreachable.

### Customers (`routes/api_routes.py`)
- `GET /api/crm/customers` — paginated, searchable (`q`), filterable (`status`), sortable
  list, org-scoped. `page_size` clamped to [1, 100].
- `GET /api/crm/customers/<id>` — single customer with recent invoices (last 5), notes,
  tasks, and all org product mappings. 404 `Customer not found` if the id doesn't resolve
  in this org (including a different org's real id — cross-tenant read must 404, not leak).

### Invoices
- `GET /api/crm/customers/<id>/invoices`, `GET /api/crm/invoices` (`kind`=all|this_month|
  outstanding) — paginated, org-scoped invoice listing.
- `GET .../line-item-descriptions`, `.../line-item-pricing`, `.../invoice-defaults` — draft
  helpers: prior line-item descriptions/pricing for a customer (for autocomplete), and a
  suggested due date derived from the customer's Xero payment terms (fetched from Xero and
  cached onto the local contact row the first time it's needed).
- `POST /api/crm/customers/<id>/invoices` — creates a DRAFT or AUTHORISED ACCREC invoice in
  Xero (never against a customer missing a `xero_contact_id`), validates every line item
  (`description` required, `quantity > 0`, `unit_amount` present), commits a local
  `crm_invoice.created` event, then best-effort incremental-syncs so the new invoice shows
  up locally without waiting for the next scheduled sync. Insufficient Xero scope → 401
  `xero_insufficient_scope`; any other validation failure → 400.
- `POST /api/crm/invoices/<id>/authorise` — authorises a DRAFT invoice in Xero. Already
  AUTHORISED/PAID → returns the current state idempotently (no-op, not an error). Any
  other non-DRAFT status → 400. Updates the local row immediately, then best-effort
  refreshes from Xero.
- `GET /api/crm/invoices/<id>/pdf` — streams the Xero-rendered PDF. DRAFT invoices are
  rejected (Xero doesn't render PDFs for drafts) with a clear 400 message.
- `GET /api/crm/invoices/<id>/view-url` — Xero's hosted online-invoice URL; falls back to
  a deep link into the Xero web app if Xero doesn't expose `OnlineInvoiceUrl` for this
  invoice's status/tenant.
- `GET /api/crm/customers/<id>/analytics` — per-customer monthly sales + top products over
  an optional date range.

### Notes (`crm_notes` table)
- `POST /api/crm/customers/<id>/notes` — `content` required (400 if blank/whitespace).
- `PUT /api/crm/notes/<id>` — 404 if the note doesn't resolve in this org.
- `DELETE /api/crm/notes/<id>` — 404 if not found in this org.
- All three emit a `crm_note.*` event; update additionally emits a content-length diff
  (not the raw content — event payloads never carry note text).

### Tasks (`crm_tasks` table)
- `GET /api/crm/tasks` — filterable by `contact_id`/`status`/`assigned_to`, org-scoped.
- `POST /api/crm/tasks` — `title` required. Optional `contact_id` must resolve in this org
  or 400 `Customer not found` (a task cannot be silently attached to another org's
  customer).
- `PUT /api/crm/tasks/<id>` — partial update over an explicit allow-list of fields; same
  cross-tenant `contact_id` re-validation on change. 404 if the task itself isn't in this
  org.
- `DELETE /api/crm/tasks/<id>` — 404 if not found in this org.

### Analytics (`crm_service.py` analytics methods)
- `GET /api/crm/analytics/monthly-sales`, `/customer-breakdown`, `/rankings`, `/churn-risk`
  — all org-scoped aggregate reads, no write path. `rankings` accepts several mutually-
  exclusive period selectors (`period_n`+`period_unit`, `start_date`/`end_date`, `months`,
  `start_month`/`end_month`) and validates `entity`/`direction` against a fixed allow-list
  (400 on anything else).
- `GET /api/crm/overview` — the CRM landing dashboard: current/previous month revenue,
  outstanding receivables, 6-month trend, top products/customers, and an open+recently-
  completed task list gated by the org's configured `task_done_archive_days`.

### Traceability config (`crm_sales_traceability_config` table)
- `GET`/`PUT /api/crm/traceability-config` — per-org settings controlling how synced sales
  are matched back to production batches (`matching_strategy` ∈ {fifo, manual, hybrid},
  `manual_review_days` ∈ [1,90], `strict_mapping`, `task_done_archive_days` ∈ [1,90],
  optional `revenue_baseline_target_mtd` ≥ 0). Upsert semantics — first `GET` on an
  unconfigured org returns sensible defaults without creating a row.

### Product mappings (`product_mappings` table)
- `GET /api/crm/product-mappings`, `GET /api/crm/final-products` (mapping candidates
  sourced from this org's `InventoryItem` rows where `inventory_type = FINAL_PRODUCT`).
- `POST /api/crm/product-mappings` — `biz_e_product_name` + `xero_description_pattern`
  required; optional `biz_e_source_output_id` must be a valid UUID. Duplicate
  (org, name, pattern) → 409, both via an explicit pre-check and a DB-unique-constraint
  fallback (`unique` in the exception text) so a race between two identical creates still
  surfaces as 409, not a 500.
- `PUT`/`DELETE /api/crm/product-mappings/<id>` — 404 if not found in this org.

### Static assets
- `GET /crm/static/js/<file>`, `/crm/static/css/<file>` — auth-gated, extension-and-
  traversal-guarded (`..`/`/` rejected, extension must match) file serving from the CRM
  blueprint's own frontend directory.

## Data model
`XeroTenant`, `XeroOAuthToken` (Fernet-encrypted access/refresh tokens), `XeroContact`,
`XeroInvoice`, `XeroInvoiceLineItem`, `XeroSyncJob` (audit trail of full/incremental sync
runs — status, counts, error detail), `CRMNote`, `CRMTask`, `ProductMapping`,
`SalesTraceabilityConfig`. All ten are `TenantScoped` with an `org_id` column and index.

## External surfaces
Talks to the real Xero Accounting API (`api.xero.com`) and Xero Identity
(`identity.xero.com`) over OAuth2 authorization-code + refresh-token grants, via the
`xero-python` SDK plus a few raw `requests` calls (PDF fetch, which the SDK doesn't cover).
Rate-limited client-side to Xero's 60-calls/60s window with retry/backoff on 429/500/503,
one token-refresh-and-retry on a single 401, and a `XeroInsufficientScopeError` surfaced to
the caller as 401 `xero_insufficient_scope` rather than retried.

## Out of scope
- Creating/editing Xero contacts from this app (contacts are read-only, sync only).
- A background/scheduled sync job — sync is triggered by OAuth connect, manual
  `POST /api/crm/xero/sync`, or opportunistically after a local invoice
  create/authorise (best-effort incremental, failure swallowed).
- Multi-currency handling beyond storing whatever `currency_code` Xero reports.

## Notes for the audit
- ASSUMPTION: every "org-scoped" and "404 if not found in this org" AC above is derived
  from the code's own `org_id` parameter threading (repo methods all take `org_id` and
  filter on it) plus the existing `test_org_isolation`/`test_note_org_isolation`/
  `test_list_tasks_org_isolation` unit tests — not from a written requirement. Flagging
  per the skill's own rule: reviewing against criteria the code trivially satisfies is
  circular, so the *values* of these ACs (should a cross-org note 404 vs 403?) are
  inherited from the rest of the app's convention, not independently decided here.
- Two issues surfaced while reading, ahead of the formal audit stages below:
  1. `XeroSyncService.incremental_sync` (xero_sync_service.py:109) creates its
     `XeroSyncJob` row with `sync_type="full"` — hardcoded, not `"incremental"`. Every
     incremental sync's audit trail row lies about what kind of sync it was.
  2. `XeroOAuthService._fernet()` derives the Fernet key as `SHA256(app.secret_key)` with
     no per-tenant salt — every org's Xero access/refresh tokens are encrypted under the
     *same* derived key. A leak of the Flask secret key (via any other vector) decrypts
     every tenant's Xero credentials at once, not just one org's.
- e2e coverage (`tests/e2e/test_crm_flow.py`) currently only cross-tenant-probes
  `/api/crm/customers`; invoices, notes, tasks, product-mappings, and traceability-config
  have no cross-tenant test, and there is no test of the OAuth callback's state-mismatch
  rejection or the tenant-picker's invalid-selection path.
