# Feature Index

**What this is:** the cached map of what this app does and where each capability lives, so a
session can scope work to one slice instead of treating `core` as a single 6784-line feature.
Read the slice you're touching plus its `depended on by` line before you start.

17 implemented slices + platform. Six — **crm**, **demo-data**, **compliant-platform**,
**compliant-nz-alcohol**, **operational-cases** and **process-templates** — have feature
directories under `app/features/`. The other slices still live in `app/core/` or
`app/api/routes/`.

Each slice block carries a `reviewed:` line, one of three states: a **date** (last
`review-feature` audit, linking to the `.agents/reports/<slug>/review.md` that proves it),
**`in progress (review/<slug> @ <worktree path>, started <date>)`** (a review is running
right now in its own worktree and hasn't produced `review.md` yet), or **`never`**. This is
what `entrypoint` and `review-feature` sort their picklist by (never-reviewed and
longest-stale first, most-recently-reviewed at the bottom, in-progress ones excluded
entirely — offering one back would start a second review colliding with the first). Don't
hand-edit this field: `scripts/feature_index_sweep.py` derives and writes it every run.

**The slice blocks describe code as it is today.** The customer-value programme below
distinguishes shipped cases from capabilities still planned. The carve
(`.agents/plans/feature-slicing-plan.md`) is in progress: Phase 1 has moved demo-data.
Line ranges into `app/core/backend/backend.py` are load-bearing and shift every time a slice
leaves that file — treat a miss as a signal to re-locate and update this file, not as licence
to guess.

Last verified: 2026-09-25, `backend.py` @ 6784 lines.

## Two axes

- **subscription** — what the customer buys. A commercial fact. Three tiers (below).
  `/core/*` is a subscription tier in the URL, not an architecture layer.
- **layer** — `platform` / `domain` / `derived` / `integration` / `shell`. Drives import
  direction: platform never imports a slice; derived slices read domain slices, not the
  reverse.

They cross: dashboard is `core` tier but `derived` layer.

## Subscription tiers

| Tier | Status | What it is |
|---|---|---|
| **core** | built — all non-Compliant slices in this file | Production control: processes, executions, inventory, traceability, CRM, dashboard, cases and templates. |
| **compliant** | initial NZ Alcohol module built | Sits on top of core. Industry-specific compliance modules capture evidence and apply rules to production steps. |
| **enterprise** | not built | Core + compliant, plus multi-site, plus customer-facing logins so contract manufacturers' customers see live status and data about their own products. |

**Every non-Compliant slice is core tier, CRM included.** `crm_enabled` is a feature
toggle, not a tier gate — don't read it as a paid-add-on boundary.

Two slices are load-bearing for the unbuilt tiers, and are noted as such in their blocks:
**compliance-checks** is where the compliant tier plugs in, and **identity** is where
enterprise's customer-facing principals will land. See the slicing plan for why that affects
how they get carved.

## Quick routing table

| If the ask mentions… | Slice |
|---|---|
| login, 2FA, TOTP, backup codes, signup, org members, invites | identity |
| designing a process, the create wizard, steps, reordering, step docs | process-design |
| running a batch, completing a step, DAG, evidence upload | execution |
| stock levels, adding/adjusting items, CSV import, barcodes, units | inventory |
| sites, multiple sites setting, physical stock and execution tags | sites |
| disposal, waste, writing stock off | wastage |
| untracked stock, matching, "the numbers don't line up" | reconciliation |
| expired materials, findings, system status, notifications, compliance | compliance-checks |
| where did this come from, lineage, trace, sourcemap | traceability |
| history, audit trail, who changed what, activity feed | activity-log |
| dashboard, summary, metrics, action board | dashboard |
| customers, Xero, invoices, sync | crm |
| dilution, ABV, proofing down, water to add | compliant-nz-alcohol |
| supplier records and intake sources | inventory |
| tasks, lanes and action board | dashboard |
| industry process templates | process-templates |
| sidebar, nav, landing page, static assets, settings page | shell |
| demo data, reset db, seeding | demo-data |
| compliance evidence, audit packs, framework modules | compliant-platform |
| New Zealand beer, spirits, wine, Customs, NP3 or trade waste | compliant-nz-alcohol |
| exception ownership, cases, resolution, verification | operational-cases |
| entered demand, material feasibility, capacity, stock risk | planning (planned) |
| rule templates, automated alerts, overdue chases, automation worker | automations (planned) |
| performance cockpit, metric definitions, business trends | dashboard (planned extension) |

## sites

subscription: core (enterprise operations planned)
layer: domain
flag: Organisation.multiple_sites_enabled (default off)
routes: /core/sites, /api/core/sites, /api/core/sites/settings, /api/core/sites/<site_id>, /api/core/sites/<site_id>/position
backend: app/features/sites/routes.py; app/features/sites/service.py; app/core/db/site_guard.py
models: Site; site_id tags on InventoryItem, Execution, StockLocation
frontend: app/features/sites/frontend/templates/sites/sites.html; app/features/sites/frontend/static/sites.js
tests: tests/test_sites.py
depends on: platform, identity, inventory, execution
depended on by: contract manufacturing and planning (planned)
invariant: additional-site operations stay closed until stock consumption, FIFO, transfers and compliance enforce site scope; existing physical tags cannot be edited as moves
status: plan 7.1a/b foundations only; see docs/multiple-sites-foundations.md

## Customer-value programme — delivery status

Source: [execution plan](../docs/customer-value-execution-plan-2026-09-05.md).
Delivery breakdown: [programme slices](plans/customer-value-slices.md).
The operational-cases slice has shipped; planning, automations and the dashboard cockpit
extension remain planned. This status does not imply a feature audit.
Subscription/package decisions remain unchanged; the flags below are proposed tenant
capabilities, default off, not new paid tiers.

| Order | Owning slice / proposed location | State | Dependencies and consumers |
|---|---|---|---|
| 1 / A | **operational-cases**, domain coordination, `app/features/operational_cases/` | **Built**; `operational_cases_enabled` gates ordinary use, history routes remain mounted | Depends on platform/identity; adapters consume compliance-checks and later Compliant/CRM. Consumed by dashboard, planning and automations. Owns case state, never source facts. |
| 2 / B | **planning**, derived, `app/features/planning/` | Planned — B1 material feasibility before B2 capacity; `planning_enabled` | Reads inventory, execution and process-design; optional CRM mappings; hands risk to operational-cases. Consumed by dashboard and automations. |
| 3 / C | **automations**, integration/orchestration, `app/features/automations/` | Planned; `automations_enabled` | Consumes platform events and explicit source adapters; invokes case/CRM services. Owns rules, durable outbox, runs and action receipts. Domain slices must not import the automation evaluator. |
| 4 / D | **dashboard**, existing derived composition slice | Planned cockpit extension; `business_cockpit_enabled` | Consumes compact services from A–C, CRM, Compliant and existing Core slices. Owns metric definitions/snapshots; retains one summary request. No second dashboard slice. |

Boundary additions to the existing map: compliance-checks supplies canonical finding
identities; shell owns Cases navigation; activity-log/platform supplies EventWriter and
LiveSync integration; inventory, reconciliation and wastage retain all corrective writes.
The named owning slice coordinates each change across those boundaries. Planned consumers
do not introduce reverse imports into existing domain code.

---

## identity

    subscription: core (foundational — never gated)
    layer:        platform
    flag:         none
    reviewed:     2026-07-26 (as auth + org, pre-identity-slice — see .agents/reports/{auth,org}/review.md)

    routes:
      - /auth/*
      - /org
      - /org/*
    backend:  app/api/routes/auth_routes.py (1575)
              app/api/routes/org_routes.py (268)
              app/core/security/{auth_service,org_manager,backup_code_encryption,permissions}.py
    models:   User, Organisation, TrustedDevice, TwoFactorBackupCode
    repos:    user_repo, organisation_repo, backup_code_repo, trusted_device_repo
    frontend: app/ui/shared/{account-info,password-policy}.js
    tests:    test_auth_password_session, test_2fa_totp_optimized, test_login_2fa_flow,
              test_org_routes, e2e/test_auth_flows, e2e/test_org_users_flow

    depends on:      platform
    depended on by:  everything (requires_auth, requires_org_scope, g.current_user)

    - Staying at app/api/routes/ deliberately (plan decision 4) — it is platform
      foundations, and it is the code an auditor opens first.
    - TIER-CRITICAL: the unbuilt ENTERPRISE tier adds customer-facing logins (a contract
      manufacturer's customers viewing their own products' status). That is a SECOND
      PRINCIPAL TYPE. Every requires_auth / g.current_user site in the app currently assumes
      "a staff user of this org" — an external customer principal breaks that assumption and
      needs a genuinely different authorisation model, not just another login flow. Avoid
      hard-coding that assumption any deeper than it already is.
    - Rate limiting lives here: `limiter` is defined in auth_routes.py and imported by
      backend.py:30 and app_factory.py:100. Moving it is a wider change than it looks.
    - Live-server authentication tests need the local TLS app and test database.

## process-design

    subscription: core
    layer:        domain
    flag:         none
    reviewed:     2026-08-03 (see .agents/reports/process-design/review.md)

    routes:
      - /core/processes
      - /core/flows/create
      - /core/flows/create/*
      - /api/core/processes
      - /api/core/processes/<process_id>
      - /api/core/processes/<process_id>/steps
      - /api/core/processes/<process_id>/steps/<step_id>
      - /api/core/processes/<process_id>/steps/reorder
      - /api/core/process-docs/*
    backend:  app/core/backend/backend.py:1449-2006 (processes+steps API)
              app/core/backend/backend.py:1056-1239 (wizard pages)
              app/core/backend/backend.py:260-563 (flow-wizard guards and state)
              app/core/backend/process_docs/ (routes 221, service 343, validation 180, storage 125)
    models:   Process, ProcessVersion, Step, ProcessStepDocument
    repos:    process_repo, process_step_document_repo
    frontend: frontend/processes/process-flow-*.html, process-wizard-*.html
              js/create-process-modal.js (6895 — largest file in repo), js/process-flow-spa.js,
              js/process-flow-next-steps-steps.js, js/flows2-steps.js
    storage:  app/core/process_docs_storage/<org_id>/<process_id>/<step_id>/ (on disk)
    tests:    test_process_design, test_process_templates, test_safe_flow_return_to,
              e2e/test_workflow_flow, e2e/test_process_docs_flow

    depends on:      platform, inventory (steps reference item types)
    depended on by:  execution, traceability, dashboard

    - The wizard keeps state in the Flask session (_flow_state_* helpers, backend.py:472-563)
      with a step-order guard. Wizard changes must keep _maybe_enforce_flow_wizard_step honest.
    - _safe_flow_return_to (backend.py:260) is an open-redirect guard whose ALLOWED_PREFIX
      must stay in sync with batch-start-scripts.html. It has its own test file.
    - flows2-*.js straddles this slice and execution — the least clean boundary in the app.

## execution

    subscription: core
    layer:        domain
    flag:         none
    reviewed:     2026-08-02 (review-feature; 6 real defects found and fixed — see
                  .agents/reports/execution/review.md)

    routes:
      - /core/flows
      - /core/flows/executions/step
      - /core/flows/batches/start
      - /core/executions/live
      - /api/core/executions
      - /api/core/executions/<execution_id>
      - /api/core/executions/<execution_id>/with-process
      - /api/core/executions/<execution_id>/steps/<execution_step_id>/complete
      - /api/core/execution-metadata
      - /api/core/evidence/*
    backend:  app/core/backend/backend.py:2007-3054 (executions API; complete_step is 2347-3054)
              app/core/backend/backend.py:4649-4732 (execution metadata)
              app/core/backend/dagtraversal.py (1008)
              app/core/backend/complete_step_payload.py
              app/core/backend/evidence/ (routes 180, service 332, validation 174, storage 145)
    models:   Execution, ExecutionStep, ExecutionEvidence, ApiIdempotencyKey
    repos:    execution_repo, evidence_repo
    frontend: frontend/processes/execution-step-*.html, shared/execution-modal.html
              js/execution-*.js (~19 files, ~5000 lines), js/flows2-executions.js
    storage:  app/core/evidence_storage/<org_id>/<execution_id>/ (on disk)
    tests:    test_executions, test_dag_traversal, test_complete_step_payload,
              test_batches_refactor_frontend_guards, test_execution_modal_frontend_assets,
              test_execution_shared_utils_js, e2e/test_workflow_flow

    depends on:      platform, process-design, inventory
    depended on by:  traceability, reconciliation, dashboard, compliance-checks

    - complete_step is about 700 lines and the highest-risk function in the app: it consumes
      inventory, produces outputs, writes movements, emits events and enforces idempotency
      in one transaction. Read all of it before changing any of it.
    - Incoming execution_data is stripped of audit/trace keys (_strip_incoming_execution_trace_keys,
      backend.py:611) then re-derived from the session. Any other persistence path must do
      the same — the contract is documented beside that helper.
    - workflow_execution_lineage records parent/child execution relationships.

## inventory

    subscription: core
    layer:        domain
    flag:         none
    reviewed:     2026-07-29 (MR !133 open, not yet merged — see .agents/reports/inventory/review.md)

    routes:
      - /core/inventory/add
      - /core/inventory/add/*
      - /core/inventory/view
      - /core/inventory/live
      - /core/suppliers
      - /api/core/inventory
      - /api/core/inventory/<item_id>
      - /api/core/inventory/<item_id>/adjust
      - /api/core/inventory/out-of-stock
      - /api/core/inventory/consume-fifo
      - /api/core/inventory/barcode/<path:code>
      - /api/core/inventory/csv-validate
      - /api/core/inventory/csv-commit
      - /api/core/inventory/decode-barcode
      - /api/core/config/units
      - /api/core/suppliers
      - /api/core/suppliers/<supplier_id>
      - /api/core/suppliers/import-from-inventory
    backend:  app/core/backend/backend.py:3055-3525 (list/read), :4012-4402 (CRUD+adjust)
              app/core/backend/backend.py:3947-4011 (out-of-stock)
              app/core/backend/inventory_upload_routes.py
              app/core/backend/suppliers.py (supplier page and API)
              app/core/utils/{unit_conversion,inventory_quantity}.py
              app/core/domain/inventory_quantity_guard.py (169)
    models:   InventoryItem, InventoryMovement
    repos:    inventory_repo
    frontend: frontend/inventory/*.html, js/inventory-*.js, js/add-inventory-reconciliation.js
    tests:    test_inventory, test_inventory_quantity_guard, test_unit_conversion,
              test_core_suppliers, test_multi_tenant_api, e2e/test_inventory_flow

    depends on:      platform
    depended on by:  execution, wastage, reconciliation, compliance-checks, traceability, dashboard

    - HARD RULE: every quantity write passes an InventoryQuantityWriteReason. Enforced by
      inventory_quantity_guard.py, documented in conventions.md §5. Not a style preference.
    - Units are converted at the boundary (convert_to_inventory_unit_decimal); compatibility
      is checked with are_units_compatible. Quantities are Decimal, not float.
    - The most depended-on domain slice. A change here reaches six others.

## wastage

    subscription: core
    layer:        derived
    flag:         none (candidate for one)
    reviewed:     2026-08-11 (see .agents/reports/wastage/review.md)

    routes:
      - /core/inventory/dispose
      - /core/inventory/dispose/confirm
      - /api/core/inventory/wastage
    backend:  app/features/wastage/routes/wastage_routes.py (disposal pages, advisory lock,
              record+list routes; registered on core_bp)
              app/core/utils/inventory_wastage_quantity.py (89)
    models:   InventoryWastage
    repos:    wastage_repo
    frontend: frontend/inventory/dispose.html, dispose_confirm.html, css/inventory-dispose.css
    tests:    test_wastage, test_multi_tenant_isolation, e2e/test_inventory_flow

    depends on:      platform, inventory
    depended on by:  compliance-checks, dashboard

    - Idempotency is a Postgres advisory lock keyed on batch hash
      (_pg_advisory_lock_wastage_idempotency, wastage_routes.py) — not the ApiIdempotencyKey
      table the rest of the app uses. Two different mechanisms; don't assume one.
    - Separate table and separate compliance meaning from an inventory adjustment. Writing
      stock off is not the same event as correcting a count.

## reconciliation

    subscription: core
    layer:        derived
    flag:         none
    reviewed:     in progress (review/reconciliation @ /home/johnny/.herdr/worktrees/workflow-engine/review-reconciliation, started 2026-08-09)

    routes:
      - /api/core/inventory/reconcile/matching-untracked
      - /api/core/inventory/reconcile/via-addition
      - /api/core/inventory/reconcile/via-execution
    backend:  app/features/reconciliation/routes/reconciliation_routes.py (168)
              app/features/reconciliation/service.py (813)
    models:   (none of its own — operates on InventoryItem/Execution)
    frontend: js/add-inventory-reconciliation.js, js/map-to-execution-reconciliation.js
    tests:    test_reconciliation_routes, e2e/reconciliation/test_reconciliation

    depends on:      platform, inventory, execution
    depended on by:  compliance-checks (untracked-items findings feed this)

    - Carved behind the existing register_routes(bp) seam; URLs and endpoint names remain
      on core_bp. `_find_producing_step` and `reconcile_output_to_untracked_reduce_only`
      are still imported by backend.py, a coupling to break after the pure move.

## compliance-checks

    subscription: core today — and the plug-in point for the unbuilt COMPLIANT tier
    layer:        derived
    flag:         none
    reviewed:     2026-08-02 (review-feature; see .agents/reports/compliance-checks/review.md)

    routes:
      - /core/notifications
      - /api/core/system-findings
      - /api/core/inventory/expired-materials
      - /api/core/inventory/untracked-items
      - /api/core/inventory/output-expiry
      - /api/core/inventory/output-ready-date
    backend:  app/features/compliance_checks/routes/corechecks.py (CoreChecksRunner + registry)
              app/features/compliance_checks/checks/{output_ready_date_check,output_expiry_check,
                untracked_items (265),expired_materials (114)}.py
              app/features/compliance_checks/{system_findings_cache,system_status}.py
              app/core/domain/{expiry_rules,ready_date_rules,expiry_ready_date_rules}.py
    frontend: frontend/notifications/notifications.html,
              js/system-findings-notifications.js (1148), js/system-findings-banner.js (513),
              frontend/shared/system-findings-banner.html
    tests:    test_corechecks, test_finding_history, test_rule_candidates

    depends on:      platform, inventory, execution, wastage
    depended on by:  dashboard (compliance summary), inventory (findings decorate list rows)

    - Checks self-register via CoreChecksRunner._register_builtin_checks (corechecks.py:72);
      register_check (corechecks.py:97) takes a check_id and a fn. Adding a check means
      registering it there, not wiring a new route.
    - TIER-CRITICAL: that registry is the seam the Compliant product plugs into —
      industry-specific compliance modules registering their own checks. Treat the check
      interface as a public contract: findings are data, and the built-in check set is not
      the whole set. Don't bake "these are all the checks" into callers.
    - build_system_status_payload derives an overall health state from check signals and is
      consumed by the dashboard — changing signal shape breaks the dashboard's summary.
    - The live sidebar links to `/compliant`; older `/workflow-engine/*` links belong
      to the retired prefix and must not be used for new routes.

## traceability

    subscription: core
    layer:        derived
    flag:         none (workflow_engine_enabled is NOT this — it's a dead legacy flag)
    reviewed:     2026-08-09 (see .agents/reports/traceability/review.md)

    routes:
      - /core/sourcemap
      - /api/core/inventory/trace/<raw_material_id>
      - /api/core/inventory/trace-backward/<inventory_item_id>
      - /api/core/inventory/trace-graph/<inventory_item_id>
      - /api/core/sourcemap/objects
      - /api/core/sourcemap/trace
    backend:  app/core/backend/backend.py:4403-4648 (trace fwd/back/graph)
              app/core/backend/backend.py:6570-6784 (sourcemap)
              app/core/backend/temporal_dag_tracer.py (275)
    frontend: frontend/sourcemap/sourcemap.html, js/sourcemap.js (2561), css/sourcemap.css
    tests:    test_traceability, e2e/traceability/test_sourcemap_page

    depends on:      platform, inventory, execution, process-design
    depended on by:  (leaf — nothing reads it)

    - This is the lineage capability once described as a /workflow-engine/* blueprint.
      No such blueprint exists; the code lives in core and keeps its /api/core/* URLs.
      Do not "restore" a /workflow-engine prefix — see plan decision 2.
    - Forward trace (where did this material end up) and backward trace (what went into
      this item) are separate implementations, not one function with a flag.

## activity-log

    subscription: core
    layer:        derived
    flag:         none
    reviewed:     2026-08-09 (see .agents/reports/activity-log/review.md)

    routes:
      - /api/core/entities/<entity_type>/<entity_id>/story
      - /api/core/entities/<entity_type>/<entity_id>/summary
      - /api/core/entities/activity
      - /api/core/changes
    backend:  app/features/activity_log/routes/activity_routes.py (event→human diff
              rendering and three read routes; registered on core_bp)
              app/core/backend/changes_feed.py (polled change feed; registered on core_bp)
              app/core/backend/event_writer.py (497) — WRITER, belongs to platform
              app/core/utils/{emit_event,log_action}.py
    models:   EntityEvent, EntityEventSummary, AuditLog
    repos:    audit_repo
    tests:    test_activity_log, e2e/activity_log/

    depends on:      platform
    depended on by:  dashboard (event counts by day)

    - Split of responsibility: EventWriter is platform (every slice emits events); reading
      the stream back as human-readable history is this slice. Writer down, reader up.
    - _merge_inventory_legacy_audit (activity_routes.py) blends pre-event-sourcing AuditLog
      rows into the modern EntityEvent stream. There are two historical formats in play.
    - Much of the block is diff humanisation (_smart_list_diff_rows, _human_summary,
      _fmt_field_value). Presentation logic in the API layer — a candidate for a service.

## dashboard

    subscription: core
    layer:        derived (composition)
    flag:         none
    reviewed:     2026-08-12 (see .agents/reports/dashboard/review.md)

    routes:
      - /core/dashboard
      - /core/tasks
      - /core/tasks/configuration
      - /api/core/dashboard/summary
      - /api/core/metrics
      - /api/core/hub/overview
      - /api/core/tasks
      - /api/core/tasks/*
    backend:  app/features/dashboard/routes/dashboard_routes.py (summary, action board,
              weekly series, metrics; registered on core_bp with stable endpoint names)
              app/core/backend/backend.py (hub overview)
              app/core/backend/tasks.py (task and lane API)
    frontend: frontend/dashboard/dashboard.html, js/dashboard.js,
              js/core-active-batches-graph.js (1007), css/dashboard_spa.css
    tests:    test_dashboard_summary, test_core_tasks

    depends on:      platform, execution, inventory, wastage, compliance-checks, activity-log
    depended on by:  (leaf)

    - COMPOSITION SLICE: it aggregates six others. The rule that makes the taxonomy hold is
      that it consumes their services, never queries their tables directly. Today it does
      query directly — _dashboard_event_counts_by_day (:5030) hits EntityEvent and
      _dashboard_execution_counts_by_day (:5052) hits Execution, both bypassing the repos.
      That's the debt this slice exists to name.
    - Reads CRM and Compliant availability while composing the summary.

## crm

    subscription: core (built = core tier; NOT a separate paid add-on)
    layer:        integration
    flag:         crm_enabled — a feature toggle, not a tier gate. True in local.ini.
    reviewed:     2026-08-15 (see .agents/reports/crm/review.md)

    routes:
      - /crm
      - /crm/*
      - /api/crm/*
    backend:  app/features/crm/{routes,services,repositories,models,frontend}/
              crm_service.py (1337), xero_api_client (590), xero_sync_service (406),
              xero_oauth_service (267), xero_invoice_repo (762)
    models:   CrmNote, CrmTask, ProductMapping, SalesTraceabilityConfig, XeroContact,
              XeroInvoice, XeroInvoiceLineItem, XeroOAuthToken, XeroSyncJob, XeroTenant
    tests:    test_crm, e2e/test_crm_flow

    depends on:      platform, inventory (product mapping), execution (sales traceability)
    depended on by:  dashboard (flag check only)

    - ALREADY CORRECTLY SLICED. This is the reference layout for the whole carve
      (conventions.md §1). Copy this shape; do not copy backend.py's.
    - Talks to a real external API. Xero calls need token refresh (xero_oauth_service) and
      have their own sync-job table for retries.

## operational-cases

    subscription: core
    layer:        domain coordination
    flag:         operational_cases_enabled (ordinary use; history routes stay mounted)
    reviewed:     never

    routes:
      - /core/cases
      - /core/cases/new
      - /core/cases/<case_id>
      - /core/cases/static/<path:filename>
      - /api/core/cases
      - /api/core/cases/<case_id>
      - /api/core/cases/<case_id>/events
      - /api/core/cases/<case_id>/refresh-source
      - /api/core/cases/<case_id>/transitions
      - /api/core/cases/from-finding
      - /api/core/cases/history/<case_id>
      - /api/core/cases/history/<case_id>/events
      - /api/core/cases/source-status
    backend:  app/features/operational_cases/{routes,services,repositories,adapters,models}/
              app/features/operational_cases/operational_cases_bp.py
    models:   OperationalCase, OperationalCaseEvent, OperationalCaseLink
    frontend: app/features/operational_cases/frontend/{templates,static}/
    tests:    test_operational_cases

    depends on:      platform, identity, compliance-checks, inventory
    depended on by:  dashboard; future planning and automations

    - Owns case state and resolution history. Source facts remain in the originating
      product; adapters capture their current status without moving their records.
    - The blueprint is always mounted so historical cases remain readable when ordinary
      case use is disabled for an organisation.

## process-templates

    subscription: core
    layer:        domain
    flag:         none (exposure is checked against the organisation's profile)
    reviewed:     never

    routes:
      - /core/flows/create/template-catalog
      - /api/core/process-templates
      - /api/core/process-templates/<template_id>
      - /api/core/process-templates/<template_id>/copy
      - /process-templates/static/<path:filename>
    backend:  app/features/process_templates/{catalog,routes,services}/
              app/features/process_templates/process_templates_bp.py
    frontend: app/features/process_templates/frontend/{templates,static}/
    tests:    test_process_templates, e2e/process_templates/test_process_templates_flow

    depends on:      platform, identity, process-design
    depended on by:  onboarding and new workflow creation

    - Templates are copied into a producer's own workflow; the catalogue source remains
      separate from the resulting process.

## compliant-platform

    subscription: compliant
    layer:        platform (within the Compliant product; does not import industry identifiers)
    flag:         compliant_enabled
    reviewed:     2026-08-22 (see .agents/reports/compliant-platform/review.md)

    routes:
      - /compliant
      - /compliant/tools
      - /compliant/static/<path:filename>
      - /api/compliant/overview
      - /api/compliant/profile
      - /api/compliant/records
      - /api/compliant/reports/*
      - /api/compliant/tools
      - /api/compliant/tools/*
    backend:  app/features/compliant/{compliant_bp.py,platform/,models/,routes/,service.py}
    models:   ComplianceProfile, ComplianceRecord, ComplianceReport
    frontend: app/features/compliant/frontend/{templates,static}/
    tests:    tests/test_compliant_routes.py

    depends on:      platform, identity, execution, inventory
    depended on by:  compliant-nz-alcohol; future industry modules

    - Owns the reusable, tenant-scoped evidence ledger, audit snapshot/export surface and
      module registration seam. It does not certify compliance or mutate core activity.
    - Enrolled organisations receive a non-blocking Compliance evidence shelf in every
      Core execution step. Core remains the system of record for uploaded evidence and
      captured prompts; Compliant surfaces that proof for reuse rather than duplicating it.
    - `platform/registry.py` is the only import CoreChecksRunner needs. New modules are
      composed there; Core must not gain framework IDs, regulator URLs or industry rules.
    - The evidence ledger is append-only at the product contract level. Audit packs are
      immutable snapshots, checksummed at generation, so an auditor can distinguish the
      evidence available at that time from the current dashboard.

## compliant-nz-alcohol

    subscription: compliant
    layer:        derived module
    flag:         compliant_enabled
    reviewed:     2026-08-23 (see .agents/reports/compliant-nz-alcohol/review.md)

    routes:
      - /compliant/nz-alcohol*
      - /api/compliant/nz-alcohol/*
      - /api/compliant/np3-audit*
      - /api/compliant/alcohol-products
      - /api/compliant/capture-context
    backend:  app/features/compliant/modules/nz_alcohol/ (catalogue, councils,
              live_evidence, module, np3_audit, workflow_rules)
              app/features/compliant/service.py (module evaluator)
    models:   AlcoholProductProfile
    frontend: NZ Alcohol profile and evidence flows in compliant-platform dashboard
    tests:    tests/test_compliant_catalog.py, tests/test_compliant_routes.py,
              tests/test_whistlebird_np3.py

    depends on:      compliant-platform, inventory, execution, crm (optional sales mapping)
    depended on by:  CoreChecksRunner via the platform composition seam

    - Covers spirits, beer, cider, mead, RTDs and wine with source-versioned Customs,
      NP3/WSMP and selected-council trade-waste packs. It now has NP3 audit controls,
      workflow rules and live evidence. Customs production/wastage LAL is derived from
      Core; removals and lodgements remain on the product plan.
    - Council catalogues provide the applicable authority's source and operational control
      set. Numeric limits, sampling frequency and expiry are deliberately taken from the
      individual consent rather than assumed from a generic bylaw.
    - This is operational evidence status, not a legal certification or automatic regulator
      filing. The customer remains responsible for scope, inputs and submissions.

## shell

    subscription: n/a
    layer:        shell
    flag:         none
    reviewed:     2026-08-15 (see .agents/reports/shell/review.md)

    routes:
      - /
      - /dashboard
      - /landing-diagram
      - /favicon.ico
      - /healthcheck
      - /initialize
      - /complaint
      - /core
      - /core/settings
      - /core/integrations
      - /static/*
      - /ui/shared/<path:filename>
      - /telemetry*
    backend:  app/core/backend/backend.py:789-817 (hub/settings/integrations pages)
              app/core/backend/backend.py:1275-1448 (static serving)
              app/api/app_factory.py
    frontend: app/ui/templates/{landing,session_expired,biz-e-diagram-landing}.html
              app/ui/templates/shared/sidebar-v2.html   <-- THE LIVE SIDEBAR
              app/core/frontend/shared/base_spa.html, page_header.html, primary_card.html
              app/core/frontend/{settings,integrations}/*.html
              app/ui/shared/{sidebar-v2.js,sidebar.css,observability-rum.js}
    tests:    e2e/test_pages_render, e2e/test_smoke, e2e/test_landing_regressions,
              e2e/test_security_headers, e2e/test_settings_flow

    depends on:      platform, identity
    depended on by:  every page-rendering slice (base_spa.html, active_page)

    - The live sidebar is app/ui/templates/shared/sidebar-v2.html. Verify older sidebar
      copies are still unused before removing them during the shell carve.
    - Static serving is FLAT: /core/static/js/<filename> resolves one directory,
      app/core/frontend/js/, with a traversal guard and an extension whitelist. Moving JS
      into slice directories breaks every template reference. See plan §3 (asset registry).
    - Templates set active_page to drive sidebar highlighting; core pages nearly all pass
      active_page="core".

## demo-data

    subscription: n/a (dev only)
    layer:        non-product
    flag:         none — but the route self-gates on config.environment
    reviewed:     2026-08-23 (see .agents/reports/demo-data/review.md)

    routes:
      - /api/core/reset-demo-db
    backend:  app/features/demo_data/           <-- CARVED (Phase 1, first slice out)
                routes/api_routes.py (register_routes seam, mounted on core_bp)
                services/resetdb.py (378)
    frontend: none
    tests:    exercised as fixture infrastructure by test_corechecks,
              test_executions, test_dag_traversal (they import reset_demo_db,
              clear_demo_db, DEMO_USER_EMAIL from services/resetdb.py)

    depends on:      platform, inventory, process-design, execution
    depended on by:  the three test files above — resetdb is NOT dev-only, it is
                     load-bearing test infrastructure

    - This route wipes and reseeds a database. It self-gates on
      config.environment in ("test", "local") and is behind @requires_auth, but has
      no feature flag. Isolating it so production can hard-disable it is the main
      reason this is its own slice.
    - DEMO_USER_EMAIL now has one definition (services/resetdb.py). It was previously
      duplicated in mock_data.py; backend.py imported the mock_data copy while the
      tests imported the resetdb copy.
    - Removed as proven-dead during the carve: app/core/utils/mock_data.py (681 lines,
      of which only the duplicate constant was referenced) and
      app/core/frontend/js/mockData.js (563 lines, referenced by no template or script).
    - Distinct from tests/factories.py — that's the test-fixtures skill's territory.
    - The seeding tests are NOT isolated from each other: a failed run leaves demo rows
      behind and the next run hits unique-constraint violations on re-seed. If you see
      UniqueViolation on uq_inventory_items_org_name_batch or StaleDataError on
      execution_steps, the DB is dirty — that is not your change.

---

## Platform (not a slice)

No routes of its own. **Platform never imports a slice.**

| Concern | Location |
|---|---|
| DB session, Base, engine, scoped-per-request teardown | `app/core/db/` |
| Tenant context → `g.current_org_id`, session security, HTTPS | `app/api/middleware/` |
| `requires_auth`, `requires_org_scope` | `app/core/security/permissions.py` |
| Config loader (`ENVIRONMENT` → `.ini`) | `app/utils/config_loader.py` (477) |
| Observability: structlog JSON, OTel traces/metrics, RUM proxy | `app/observability/` |
| Event writing | `app/core/backend/event_writer.py` |
| Units, quantities, time, phone normalisation | `app/core/utils/`, `app/core/domain/` |
| API response helpers | `app/utils/api_helpers.py` |
| Idempotency | `ApiIdempotencyKey` model |

To be renamed `app/platform/` (plan decision 3) — `/core` is a subscription tier in the URL,
which is a different thing from `core` meaning "shared kernel" in a directory name.

## Cross-cutting invariants

True in every slice; violating one is a bug regardless of where you are.

1. **Every table has `org_id`; every query filters on it.** Explicit `org_id` parameter,
   inline `.filter(Model.org_id == org_id)`. No shared scoping helper exists —
   conventions.md §2.
   *Forward-looking:* the enterprise tier adds multi-site, i.e. a `site_id` dimension
   beneath `org_id`, which means revisiting every one of these filters. New `org_id`
   filtering belongs in a repository method, not inline in a route handler — that's where
   the site dimension will have to be added later.
2. **Every inventory quantity write passes an `InventoryQuantityWriteReason`** —
   conventions.md §5.
3. **SPAs send `X-CSRFToken`.** Flask-WTF CSRF is on.
4. **Repository pattern for data access** — no ORM queries in route handlers (widely
   violated inside `backend.py`; don't add more).
5. **Tenant isolation is tested** — `test_multi_tenant_isolation.py`,
   `e2e/test_tenant_isolation.py`. A new cross-org read path needs a test there.

## Known coverage gaps

The earlier gaps for reconciliation, Source Map, activity-log and process documents now
have dedicated API or E2E coverage. Their slice blocks name the current suites. Review
coverage against each changed route when carving a slice; the index does not claim
exhaustive coverage.

## Maintaining this file

- Update the affected slice block in the same MR that moves or adds a route. A stale index
  is worse than none, because it is trusted.
- `backend.py` line ranges drift with every edit to that file. If a range doesn't match what
  you find, re-locate it and fix the entry.
- Re-verify wholesale after each phase of the slicing plan.
- Route claims use one URL-map path or glob per line under `routes:`. Run
  `ENVIRONMENT=test uv run python scripts/check_feature_index_routes.py` after editing a
  route or this index. CI runs the same check. `backend:` line ranges still require a
  human refresh when code moves.
- The `reviewed:` field's staleness *is* handled: `scripts/feature_index_sweep.py` reconciles
  it against `.agents/reports/<slug>/review.md` (a completed review) and live `review/<slug>`
  worktrees (one in flight) every time `review-feature` or `entrypoint` runs, and writes the
  line itself — never hand-edit `reviewed:`. See the field's own description above for the
  three states it can hold.

### Staff site roles (7.1g foundation, activation closed)

- Model/migration: `org_role.py`, `org_role_site.py`, `staff_site_roles_001.py`.
- Admin configuration: `staff_site_roles.py`, `/org/roles`, existing People role editor.
- Authorization: `staff_site_scope.py`, `staff_site_policy.py`, static endpoint registry.
- Existing all-site access preserved; selected assignment and every sensitive handler
  remain closed. Activation audit: `docs/staff-site-role-foundations.md`.
