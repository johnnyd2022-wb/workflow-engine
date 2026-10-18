<!-- Codex security-tenant-audit (gpt-5.6-sol, high, --sandbox read-only), pane w55:p2, 2026-10-18. Transcribed verbatim by the orchestrator: a read-only grader cannot write its own report (.agents/verification-chain.md §5). -->
# SECURITY: crm

date: 2026-10-18
verdict: findings-open
scope: all 69 `/crm/*` and `/api/crm/*` routes, downstream services/repositories, and `origin/main...HEAD -- app/`

Applied the requested [security-audit skill](.claude/skills/security-audit/SKILL.md) and the [Herdr Breaker p
rotocol](.codex/skills/herdr-multi-agent-collab-breaker/SKILL.md) in read-only mode.

## Findings

### F1 — Medium — CRM write permissions permit inventory quantity changes

Several endpoints resolve to `sales.record` or `sales.manage`, but their downstream effects decrement or restore `InventoryItem.quantity`:

- `POST /api/crm/matching/assign` resolves to `sales.record` and calls `consume_final_product_lot`.
- `POST /api/crm/matching/run` resolves to `sales.record` and runs full reconciliation/FIFO consumption.
- Creating an already-authorised invoice and authorising a draft both run incremental sync and may consume inventory.
- OAuth callback, tenant selection and manual Xero sync resolve to `sales.manage` and can run the same reconciliation.

The permission descriptions reserve stock adjustment/removal for `inventory.adjust`, while the built-in Sales role has `sales.record` but not `inventory.adjust`. Thus a Sales user can directly select lots and change stock through matching. Cus
tom roles can also receive `sales.manage` without `inventory.adjust`.

Evidence:

- [access_policy.py:38](app/core/security/access_policy.py:38)
- [access_policy.py:338](app/core/security/access_policy.py:338)
- [api_routes.py:867](app/features/crm/routes/api_routes.py:867)
- [sales_traceability_service.py:255](app/features/crm/services/sales_traceability_service.py:255)
- [inventory_repo.py:529](app/core/db/repositories/inventory_repo.py:529)

Expected remediation: require `inventory.adjust` for explicit matching/reconciliation, or formally redefine and test the sales permissions as authorizing sales-driven stock mutations. The current policy supports OR requirements, not AND, so th
is may need a route-level check or a dedicated permission.

rule_added: none — read-only grader.

### F2 — Low — Product mappings accept unowned `biz_e_source_output_id` values

Create, bulk-create, and update accept any syntactically valid UUID for `biz_e_source_output_id`. They never prove that the ID represents an output or final product belonging to the caller’s organisation.

The mapping row itself is correctly written under the caller’s `org_id`, and downstream inventory queries remain tenant-filtered, so this does not expose or mutate the other tenant. It nevertheless accepts a cross-tenant logical reference and
can make matching silently stale or prevent the caller’s stock from being consumed.

Evidence:

- [crm_service.py:1096](app/features/crm/services/crm_service.py:1096)
- [crm_service.py:1110](app/features/crm/services/crm_service.py:1110)
- [crm_service.py:1154](app/features/crm/services/crm_service.py:1154)
- [product_mapping.py:22](app/features/crm/models/product_mapping.py:22)

Expected remediation: when non-null, verify it against an org-scoped final-product/source-output lookup and reject unknown or foreign values.

rule_added: none — read-only grader.

### F3 — Low hardening gap — Several queries rely solely on the global tenant filter

No exploitable route leak was found: authenticated CRM requests activate the global ORM filter before route execution, and the flush guard blocks cross-org writes. Nevertheless, these source queries omit their own `org_id` predicate:

- Invoice line-item replacement and reads: [xero_invoice_repo.py:57](app/features/crm/repositories/xero_invoi
ce_repo.py:57), [xero_invoice_repo.py:150](app/features/crm/repositories/xero_invoice_repo.py:150)
- Sync-job updates by ID only: [xero_sync_job_repo.py:28](app/features/crm/repositories/xero_sync_job_repo.py
:28)
- CRM task contact serialization: [crm_service.py:1380](app/features/crm/services/crm_service.py:1380)
- Inventory and execution-step `Session.get()` calls: [sales_traceability_service.py:284](app/features/crm/se
rvices/sales_traceability_service.py:284), [sales_traceability_service.py:360](app/features/crm/services/sale
s_traceability_service.py:360), [sales_traceability_service.py:725](app/features/crm/services/sales_traceabil
ity_service.py:725)

The global filter explicitly documents that it is fail-open without tenant context and that identity-map hits can bypass filtering in unusual same-session scenarios: [tenant_filter.py:15](/home/johnny/event-factory/.local/worktrees/workflow-en
gine/fd35062c-96bf-46ab-b43f-cf220f652d97/bb71aa65-9423-4aa8-96d0-78c7b1d34cd8/app/core/db/tenant_filter.py:15).

These are safe on the audited HTTP paths because tenant context is active and their IDs originate from already scoped parent rows. Adding explicit predicates would preserve the repository invariant outside HTTP requests and remove reliance on
that ambient guarantee.

rule_added: none — read-only grader.

## Route matrix

`Yes†` means every executed tenant query is filtered, but at least one downstream query relies on the global ORM tenant filter rather than spelling out `org_id`.

### Pages and assets

| Route | Endpoint | requirement_for | DB isolation |
|---|---|---|---|
| GET `/crm/static/js/<filename>` | `crm.serve_crm_js` | `public` | N/A; `requires_auth` still blocks anonymous callers |
| GET `/crm/static/css/<filename>` | `crm.serve_crm_css` | `public` | N/A; `requires_auth` still blocks anonymous callers |
| GET `/crm` | `crm.crm_pages.crm_index` | `sales.view` | N/A |
| GET `/crm/customers` | `crm.crm_pages.crm_customers` | `sales.view` | N/A |
| GET `/crm/customers/<contact_id>` | `crm.crm_pages.crm_customer_detail` | `sales.view` | N/A; ID is only rendered, API fetch is scoped |
| GET `/crm/tasks` | `crm.crm_pages.crm_tasks` | `sales.view` | N/A |
| GET `/crm/analytics` | `crm.crm_pages.crm_analytics` | `sales.view` | N/A |
| GET `/crm/configuration` | `crm.crm_pages.crm_configuration` | `sales.manage` | N/A |
| GET `/crm/matching` | `crm.crm_pages.crm_matching` | `sales.view` | N/A |

### Xero/OAuth

| Route | Endpoint | requirement_for | DB isolation |
|---|---|---|---|
| GET `/crm/xero/auth` | `crm.crm_oauth.xero_auth` | `sales.manage` | N/A; session state only |
| GET `/api/crm/xero/auth-url` | `crm.crm_oauth.xero_auth_url` | `sales.manage` | N/A; session state only |
| GET `/crm/xero/callback` | `crm.crm_oauth.xero_callback` | `sales.manage` | Yes†; OAuth state checked, token/tenant writes scoped; F1 effect |
| GET `/crm/xero/select-tenant` | `crm.crm_oauth.xero_select_tenant_page` | `sales.manage` | N/A; pending session metadata only |
| POST `/crm/xero/select-tenant` | `crm.crm_oauth.xero_select_tenant_submit` | `sales.manage` | Yes†; selected ID must be in pending session list; F1 effect |
| GET `/api/crm/xero/status` | `crm.crm_oauth.xero_status` | `sales.view` | Yes |
| POST `/api/crm/xero/sync` | `crm.crm_oauth.xero_sync` | `sales.manage` | Yes†; F1 for custom roles |
| POST `/api/crm/xero/disconnect` | `crm.crm_oauth.xero_disconnect` | `sales.manage` | Yes |

### Customer and invoice APIs

| Route | Endpoint | requirement_for | DB isolation |
|---|---|---|---|
| GET `/api/crm/customers` | `crm.crm_api.list_customers` | `sales.view` | Yes |
| GET `/api/crm/customers/<contact_id>` | `crm.crm_api.get_customer` | `sales.view` | Yes†; foreign ID returns 404 |
| POST `/api/crm/customers` | `crm.crm_api.create_customer` | `sales.record` | Yes |
| PATCH `/api/crm/customers/<contact_id>` | `crm.crm_api.update_customer` | `sales.record` | Yes; foreign ID returns 404 |
| PUT `/api/crm/customers/<contact_id>/xero-sync` | `crm.crm_api.set_customer_xero_sync` | `sales.record` | Yes |
| POST `/api/crm/customers/<contact_id>/xero-sync/retry` | `crm.crm_api.retry_customer_xero_sync` | `sales.record` | Yes |
| GET `/api/crm/contact-sync-settings` | `crm.crm_api.get_contact_sync_settings` | `sales.view` | Yes |
| PUT `/api/crm/contact-sync-settings` | `crm.crm_api.update_contact_sync_settings` | `sales.manage` | Yes |
| GET `/api/crm/customers/<contact_id>/invoices` | `crm.crm_api.get_customer_invoices` | `sales.view` | Yes†; foreign contact produces an empty result |
| GET `/api/crm/invoices` | `crm.crm_api.get_org_invoices` | `sales.view` | Yes† |
| GET `/api/crm/invoices/<invoice_id>/trace-items` | `crm.crm_api.get_invoice_trace_items` | `sales.view` | Yes; invoice and allocations both explicitly scoped |
| GET `/api/crm/customers/<contact_id>/line-item-descriptions` | `crm.crm_api.get_customer_line_item_descriptions` | `sales.view` | Yes |
| GET `/api/crm/customers/<contact_id>/line-item-pricing` | `crm.crm_api.get_customer_line_item_pricing` | `sales.view` | Yes |
| GET `/api/crm/customers/<contact_id>/invoice-defaults` | `crm.crm_api.get_customer_invoice_defaults` | `sales.view` | Yes; contact ownership verified |
| GET `/api/crm/line-item-descriptions` | `crm.crm_api.get_org_line_item_descriptions` | `sales.view` | Yes |
| POST `/api/crm/customers/<contact_id>/invoices` | `crm.crm_api.create_customer_invoice` | `sales.record` | Yes†; contact scoped; F1 if authorised |
| POST `/api/crm/invoices/<invoice_id>/authorise` | `crm.crm_api.authorise_invoice` | `sales.record` | Yes†; local invoice scoped; F1 |
| GET `/api/crm/invoices/<invoice_id>/pdf` | `crm.crm_api.get_invoice_pdf` | `sales.view` | Yes |
| GET `/api/crm/invoices/<invoice_id>/view-url` | `crm.crm_api.get_invoice_view_url` | `sales.view` | Yes |
| GET `/api/crm/customers/<contact_id>/analytics` | `crm.crm_api.get_customer_analytics` | `sales.view` | Yes; invoice queries bind both org and contact |

### Notes, tasks, and lanes

| Route | Endpoint | requirement_for | DB isolation |
|---|---|---|---|
| POST `/api/crm/customers/<contact_id>/notes` | `crm.crm_api.create_note` | `sales.record` | Yes; contact ownership checked |
| PUT `/api/crm/notes/<note_id>` | `crm.crm_api.update_note` | `sales.record` | Yes |
| DELETE `/api/crm/notes/<note_id>` | `crm.crm_api.delete_note` | `sales.record` | Yes |
| GET `/api/crm/tasks` | `crm.crm_api.list_tasks` | `sales.view` | Yes† |
| POST `/api/crm/tasks` | `crm.crm_api.create_task` | `sales.record` | Yes†; contact scoped; assignee must be active in caller org |
| PUT `/api/crm/tasks/<task_id>` | `crm.crm_api.update_task` | `sales.record` | Yes†; task/contact/assignee scoped |
| DELETE `/api/crm/tasks/<task_id>` | `crm.crm_api.delete_task` | `sales.record` | Yes |
| GET `/api/crm/tasks/lanes` | `crm.crm_api.list_task_lanes` | `sales.view` | Yes; org and `board="crm"` scoped |
| POST `/api/crm/tasks/lanes` | `crm.crm_api.create_task_lane` | `sales.record` | Yes |
| PUT `/api/crm/tasks/lanes/<lane_id>` | `crm.crm_api.update_task_lane` | `sales.record` | Yes |
| PUT `/api/crm/tasks/lanes/order` | `crm.crm_api.reorder_task_lanes` | `sales.record` | Yes; rejects IDs not exactly matching caller’s board |
| DELETE `/api/crm/tasks/lanes/<lane_id>` | `crm.crm_api.delete_task_lane` | `sales.record` | Yes |
| PUT `/api/crm/tasks/<task_id>/lane` | `crm.crm_api.assign_task_lane` | `sales.record` | Yes; both task and lane scoped |

### Analytics and configuration

| Route | Endpoint | requirement_for | DB isolation |
|---|---|---|---|
| GET `/api/crm/analytics/monthly-sales` | `crm.crm_api.monthly_sales` | `sales.view` | Yes |
| GET `/api/crm/analytics/customer-breakdown` | `crm.crm_api.customer_breakdown` | `sales.view` | Yes† |
| GET `/api/crm/analytics/rankings` | `crm.crm_api.rankings` | `sales.view` | Yes† |
| GET `/api/crm/analytics/churn-risk` | `crm.crm_api.churn_risk` | `sales.view` | Yes† |
| GET `/api/crm/analytics/customer-contact` | `crm.crm_api.customer_contact` | `sales.view` | Yes |
| GET `/api/crm/overview` | `crm.crm_api.crm_overview` | `sales.view` | Yes† |
| GET `/api/crm/traceability-config` | `crm.crm_api.get_traceability_config` | `sales.view` | Yes |
| PUT `/api/crm/traceability-config` | `crm.crm_api.update_traceability_config` | `sales.manage` | Yes |

### Matching and mappings

| Route | Endpoint | requirement_for | DB isolation |
|---|---|---|---|
| GET `/api/crm/matching` | `crm.crm_api.get_matching_queue` | `sales.view` | Yes† |
| GET `/api/crm/matching/candidates` | `crm.crm_api.get_matching_candidates` | `sales.view` | Yes†; `site_id` resolved against caller org |
| POST `/api/crm/matching/confirm` | `crm.crm_api.confirm_matching_line` | `sales.record` | Yes; external invoice ID and line key constrained by allocation org |
| POST `/api/crm/matching/assign` | `crm.crm_api.assign_matching_line` | `sales.record` | Yes†; invoice, site and inventory item scoped; F1 |
| POST `/api/crm/matching/run` | `crm.crm_api.run_matching` | `sales.record` | Yes†; F1 |
| GET `/api/crm/product-mappings` | `crm.crm_api.list_mappings` | `sales.view` | Yes |
| GET `/api/crm/final-products` | `crm.crm_api.list_final_products` | `sales.view` | Yes |
| POST `/api/crm/product-mappings` | `crm.crm_api.create_mapping` | `sales.manage` | DB row scoped; F2 source-output reference unchecked |
| POST `/api/crm/product-mappings/bulk` | `crm.crm_api.create_mappings_bulk` | `sales.manage` | DB rows scoped; F2 source-output references unchecked |
| PUT `/api/crm/product-mappings/<mapping_id>` | `crm.crm_api.update_mapping` | `sales.manage` | Mapping ID scoped; F2 if changing source output |
| DELETE `/api/crm/product-mappings/<mapping_id>` | `crm.crm_api.delete_mapping` | `sales.manage` | Yes; foreign mapping returns 404 |

## Identifier conclusions

- `contact_id`: scoped on object reads and validated before note/task/invoice writes.
- `assigned_to_user_id`: branch fix is correct; it now requires an active user with the caller’s `org_id`.
- `inventory_item_id`: `consume_final_product_lot` filters by both item ID and caller org.
- `site_id`: `resolve_site` requires an active site belonging to the caller org.
- `lane_id`: every operation filters `org_id`, board type and lane ID.
- `invoice_id`: local UUID and Xero string IDs are always combined with caller org before data access.
- `mapping_id`: update/delete use `(mapping_id, org_id)`.
- `biz_e_source_output_id`: not ownership-validated; F2.
- No route response was found to expose another organisation’s customer, invoice, note, task, mapping, inventory, site or Xero-token data.

## Authentication and request protection

- All 69 routes carry `@requires_auth`.
- No endpoint resolves to `DENY`.
- The two static handlers resolve to `public` in `requirement_for`, but remain authenticated through their decorators and expose only fixed-extension files from fixed directories.
- CRM mutating routes are protected by the application-wide Flask-WTF CSRF hook; no CRM route is exempt.
- Request-body updates use service allowlists. No direct `Model(**request.json)` mass assignment was found.
- Xero network destinations are constants; request input cannot choose an SSRF destination.

## Branch diff review

The branch’s tenant-security change is correct:

- `create_task` and `update_task` now validate `assigned_to_user_id` through the same-org active-user lookup in `_parse_optional_user`.
- The added tests cover foreign, unknown and valid same-org assignees.
- No new route, `DENY` resolution, tenant bypass, unscoped external ID lookup, or response leak was introduced by `origin/main...HEAD -- app/`.
- F1–F3 are broader/pre-existing CRM issues, not regressions introduced by this diff.

Suppressed (prior verdict): the shared Xero token-encryption key remains a previously accepted architectural risk from the 2026-08-15 review. The current implementation uses a dedicated `xero_token_secret`, but still not a per-tenant key.

## Verification limits

- gitleaks: completed, 0 findings in `app/features/crm/`.
- Semgrep: not run; it attempted to create its settings temp file and the grader filesystem is read-only.
- `uv audit`: not run; it attempted to create a temp file and the grader filesystem is read-only.
- Dynamic database tests: not run; preflight reported the test PostgreSQL instance down and Docker unavailable.
- Live-server tests: skipped as instructed.
- Manual scoped checklist: 7/7 completed.

VERDICT: findings-open
