# Feature Index

**What this is:** the cached map of what this app does and where each capability lives, so a
session can scope work to one slice instead of treating `core` as a single 5763-line feature.
Read the slice you're touching plus its `depended on by` line before you start.

14 slices + platform. Three — **crm**, **dilution-calculator** and **demo-data** — have the
target directory layout under `app/features/`; the other eleven are still inside `core_bp`.

Each slice block carries a `reviewed:` line, one of three states: a **date** (last
`review-feature` audit, linking to the `.agents/reports/<slug>/review.md` that proves it),
**`in progress (review/<slug> @ <worktree path>, started <date>)`** (a review is running
right now in its own worktree and hasn't produced `review.md` yet), or **`never`**. This is
what `entrypoint` and `review-feature` sort their picklist by (never-reviewed and
longest-stale first, most-recently-reviewed at the bottom, in-progress ones excluded
entirely — offering one back would start a second review colliding with the first). Don't
hand-edit this field: `scripts/feature_index_sweep.py` derives and writes it every run.

**This describes the code as it is today, not the target.** The carve
(`.agents/plans/feature-slicing-plan.md`) is in progress: Phase 1 has moved demo-data.
Line ranges into `app/core/backend/backend.py` are load-bearing and shift every time a slice
leaves that file — treat a miss as a signal to re-locate and update this file, not as licence
to guess.

Last verified: 2026-07-28, `backend.py` @ 5763 lines (demo-data carved out).

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
| **core** | built — **every slice in this file** | Production control: processes, executions, inventory, traceability, CRM, dashboard. |
| **compliant** | not built | Sits on top of core. Industry-specific compliance modules capturing everything needed for *live* compliance, automating compliance and audit requirements. **Vanta for physical manufacturing.** |
| **enterprise** | not built | Core + compliant, plus multi-site, plus customer-facing logins so contract manufacturers' customers see live status and data about their own products. |

**Everything in the codebase today is core tier, CRM included.** `crm_enabled` is a feature
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
| disposal, waste, writing stock off | wastage |
| untracked stock, matching, "the numbers don't line up" | reconciliation |
| expired materials, findings, system status, notifications, compliance | compliance-checks |
| where did this come from, lineage, trace, sourcemap | traceability |
| history, audit trail, who changed what, activity feed | activity-log |
| dashboard, summary, metrics, action board | dashboard |
| customers, Xero, invoices, sync | crm |
| dilution, ABV, proofing down, water to add | dilution-calculator |
| sidebar, nav, landing page, static assets, settings page | shell |
| demo data, reset db, seeding | demo-data |

---

## identity

    subscription: core (foundational — never gated)
    layer:        platform
    flag:         none
    reviewed:     2026-07-26 (as auth + org, pre-identity-slice — see .agents/reports/{auth,org}/review.md)

    routes:   /auth/* (login, logout, signup, 2FA setup/verify, backup codes, password)
              /org/*  (org management, members)
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
      backend.py:16 and app_factory.py:71. Moving it is a wider change than it looks.
    - 30 of the suite's skips are the live_server 2FA suites. See the suite-warden skill.

## process-design

    subscription: core
    layer:        domain
    flag:         none
    reviewed:     2026-08-03 (see .agents/reports/process-design/review.md)

    routes:   /core/processes, /core/flows/create/* (8 wizard pages)
              /api/core/processes [GET POST], /api/core/processes/<id> [GET PUT DELETE]
              /api/core/processes/<id>/steps [POST], /steps/<sid> [PUT DELETE]
              /api/core/processes/<id>/steps/reorder [POST]
              /api/core/process-docs/* (config, upload, inline, <step_id>, download, DELETE)
    backend:  app/core/backend/backend.py:1201-1694 (processes+steps API)
              app/core/backend/backend.py:855-1022 (wizard pages)
              app/core/backend/backend.py:139-424 (flow-wizard session state + guards)
              app/core/backend/process_docs/ (routes 221, service 343, validation 180, storage 125)
    models:   Process, ProcessVersion, Step, ProcessStepDocument
    repos:    process_repo, process_step_document_repo
    frontend: frontend/processes/process-flow-*.html, process-wizard-*.html
              js/create-process-modal.js (6765 — largest file in repo), js/process-flow-spa.js,
              js/process-flow-next-steps-steps.js, js/flows2-steps.js
    storage:  app/core/process_docs_storage/<org_id>/<process_id>/<step_id>/ (on disk)
    tests:    test_safe_flow_return_to, e2e/test_workflow_flow
              GAP: no dedicated process-docs test

    depends on:      platform, inventory (steps reference item types)
    depended on by:  execution, traceability, dashboard

    - The wizard keeps state in the Flask session (_flow_state_* helpers, backend.py:333-424)
      with a step-order guard. Wizard changes must keep _maybe_enforce_flow_wizard_step honest.
    - _safe_flow_return_to (backend.py:145) is an open-redirect guard whose ALLOWED_PREFIX
      must stay in sync with batch-start-scripts.html. It has its own test file.
    - flows2-*.js straddles this slice and execution — the least clean boundary in the app.

## execution

    subscription: core
    layer:        domain
    flag:         none
    reviewed:     2026-08-02 (review-feature; 6 real defects found and fixed — see
                  .agents/reports/execution/review.md)

    routes:   /core/flows, /core/flows/executions/step, /core/flows/batches/start
              /core/executions/live
              /api/core/executions [GET POST], /api/core/executions/<id> [GET]
              /api/core/executions/<id>/with-process
              /api/core/executions/<id>/steps/<sid>/complete [POST]
              /api/core/execution-metadata
              /api/core/evidence/* (config, upload, <id>/download, list, DELETE)
    backend:  app/core/backend/backend.py:1695-2601 (executions API; complete_step is 1985-2600)
              app/core/backend/backend.py:4016-4099 (execution metadata)
              app/core/backend/dagtraversal.py (850)
              app/core/backend/complete_step_payload.py (95)
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

    - complete_step is 615 lines and the highest-risk function in the app: it consumes
      inventory, produces outputs, writes movements, emits events and enforces idempotency
      in one transaction. Read all of it before changing any of it.
    - Incoming execution_data is stripped of audit/trace keys (_strip_incoming_execution_trace_keys,
      backend.py:472) then re-derived from the session. Any other persistence path must do
      the same — the contract is documented at backend.py:554.
    - workflow_execution_lineage records parent/child execution relationships.

## inventory

    subscription: core
    layer:        domain
    flag:         none
    reviewed:     2026-07-29 (MR !133 open, not yet merged — see .agents/reports/inventory/review.md)

    routes:   /core/inventory/{add,add/manual,add/csv,add/barcode,view,live}
              /api/core/inventory [GET POST], /api/core/inventory/<id> [PUT DELETE]
              /api/core/inventory/<id>/adjust [POST]
              /api/core/inventory/out-of-stock
              /api/core/inventory/{barcode/<code>,csv-validate,csv-commit,decode-barcode}
              /api/core/config/units
    backend:  app/core/backend/backend.py:2602-3013 (list/read), :3468-3824 (CRUD+adjust)
              app/core/backend/backend.py:3406-3467 (out-of-stock)
              app/core/backend/inventory_upload_routes.py (396)
              app/core/utils/{unit_conversion,inventory_quantity}.py
              app/core/domain/inventory_quantity_guard.py (169)
    models:   InventoryItem, InventoryMovement
    repos:    inventory_repo
    frontend: frontend/inventory/*.html, js/inventory-*.js, js/add-inventory-reconciliation.js
    tests:    test_inventory_quantity_guard, test_unit_conversion, test_multi_tenant_api,
              e2e/test_inventory_flow

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

    routes:   /core/inventory/dispose, /core/inventory/dispose/confirm
              /api/core/inventory/wastage [GET POST]
    backend:  app/core/backend/backend.py:2998-3013 (advisory lock), :3014-3406 (record+list)
              app/core/utils/inventory_wastage_quantity.py (89)
    models:   InventoryWastage
    repos:    wastage_repo
    frontend: frontend/inventory/dispose.html, dispose_confirm.html, css/inventory-dispose.css
    tests:    test_wastage, test_multi_tenant_isolation, e2e/test_inventory_flow

    depends on:      platform, inventory
    depended on by:  compliance-checks, dashboard

    - Idempotency is a Postgres advisory lock keyed on batch hash
      (_pg_advisory_lock_wastage_idempotency, backend.py:2998) — not the ApiIdempotencyKey
      table the rest of the app uses. Two different mechanisms; don't assume one.
    - Separate table and separate compliance meaning from an inventory adjustment. Writing
      stock off is not the same event as correcting a count.

## reconciliation

    subscription: core
    layer:        derived
    flag:         none
    reviewed:     in progress (review/reconciliation @ /home/johnny/.herdr/worktrees/workflow-engine/review-reconciliation, started 2026-08-09)

    routes:   /api/core/inventory/reconcile/matching-untracked [GET]
              /api/core/inventory/reconcile/via-addition [POST]
              /api/core/inventory/reconcile/via-execution [POST]
    backend:  app/core/backend/reconciliation_routes.py (164)
              app/core/backend/reconciliation_service.py (889 — 2nd largest module in core)
    models:   (none of its own — operates on InventoryItem/Execution)
    frontend: js/add-inventory-reconciliation.js, js/map-to-execution-reconciliation.js
    tests:    GAP — no dedicated test file for 1053 lines of logic

    depends on:      platform, inventory, execution
    depended on by:  compliance-checks (untracked-items findings feed this)

    - Already fully behind the register_routes(bp) seam, no backend.py entanglement.
      Cheapest Layer-2 slice to carve, and the biggest untested surface. Worth tests first.
    - _find_producing_step is imported back into backend.py:31 — the one coupling to break.

## compliance-checks

    subscription: core today — and the plug-in point for the unbuilt COMPLIANT tier
    layer:        derived
    flag:         none
    reviewed:     2026-08-02 (review-feature; see .agents/reports/compliance-checks/review.md)

    routes:   /core/notifications
              /api/core/system-findings
              /api/core/inventory/{expired-materials,untracked-items,output-expiry,output-ready-date}
    backend:  app/core/backend/corechecks.py (260 — CoreChecksRunner + registry)
              app/core/backend/checks/{output_ready_date_check (479),output_expiry_check (333),
                untracked_items (265),expired_materials (114)}.py
              app/core/backend/system_status.py (201)
              app/core/domain/{expiry_rules,ready_date_rules,expiry_ready_date_rules}.py
    frontend: frontend/notifications/notifications.html,
              js/system-findings-notifications.js (981), js/system-findings-banner.js (472),
              frontend/shared/system-findings-banner.html
    tests:    test_corechecks, test_finding_history, test_rule_candidates

    depends on:      platform, inventory, execution, wastage
    depended on by:  dashboard (compliance summary), inventory (findings decorate list rows)

    - Checks self-register via CoreChecksRunner._register_builtin_checks (corechecks.py:64);
      register_check (corechecks.py:81) takes a check_id and a fn. Adding a check means
      registering it there, not wiring a new route.
    - TIER-CRITICAL: that registry is the seam the unbuilt COMPLIANT tier plugs into —
      industry-specific compliance modules registering their own checks. Treat the check
      interface as a public contract: findings are data, and the built-in check set is not
      the whole set. Don't bake "these are all the checks" into callers.
    - build_system_status_payload derives an overall health state from check signals and is
      consumed by the dashboard — changing signal shape breaks the dashboard's summary.
    - The commented-out "Compliance" nav entry was meant for this. See plan §1 before
      re-enabling it: the /workflow-engine/* prefix it points at is legacy.

## traceability

    subscription: core
    layer:        derived
    flag:         none (workflow_engine_enabled is NOT this — it's a dead legacy flag)
    reviewed:     2026-08-09 (see .agents/reports/traceability/review.md)

    routes:   /core/sourcemap
              /api/core/inventory/trace/<raw_material_id> [GET]        (forward)
              /api/core/inventory/trace-backward/<item_id> [GET]
              /api/core/sourcemap/objects [GET], /api/core/sourcemap/trace [POST]
    backend:  app/core/backend/backend.py:3825-4015 (trace fwd/back)
              app/core/backend/backend.py:5558-5763 (sourcemap)
              app/core/backend/temporal_dag_tracer.py (179)
    frontend: frontend/sourcemap/sourcemap.html, js/sourcemap.js (2128), css/sourcemap.css
    tests:    GAP — no test touches sourcemap at all

    depends on:      platform, inventory, execution, process-design
    depended on by:  (leaf — nothing reads it)

    - THIS is the "workflow engine" CLAUDE.md describes as a /workflow-engine/* blueprint.
      No such blueprint exists; the code lives in core and keeps its /api/core/* URLs.
      Do not "restore" a /workflow-engine prefix — see plan decision 2.
    - Forward trace (where did this material end up) and backward trace (what went into
      this item) are separate implementations, not one function with a flag.

## activity-log

    subscription: core
    layer:        derived
    flag:         none
    reviewed:     2026-08-09 (see .agents/reports/activity-log/review.md)

    routes:   /api/core/entities/<type>/<id>/story [GET]
              /api/core/entities/<type>/<id>/summary [GET]
              /api/core/entities/activity [GET]
    backend:  app/core/backend/backend.py:4837-5557 (event→human diff rendering, 721 lines)
              app/core/backend/event_writer.py (458) — WRITER, belongs to platform
              app/core/utils/{emit_event,log_action}.py
    models:   EntityEvent, EntityEventSummary, AuditLog
    repos:    audit_repo
    tests:    test_finding_history (partial), GAP: no test for the story/activity endpoints

    depends on:      platform
    depended on by:  dashboard (event counts by day)

    - Split of responsibility: EventWriter is platform (every slice emits events); reading
      the stream back as human-readable history is this slice. Writer down, reader up.
    - _merge_inventory_legacy_audit (backend.py:5327) blends pre-event-sourcing AuditLog
      rows into the modern EntityEvent stream. There are two historical formats in play.
    - ~450 of the 721 lines are diff humanisation (_smart_list_diff_rows, _human_summary,
      _fmt_field_value). Presentation logic in the API layer — a candidate for a service.

## dashboard

    subscription: core
    layer:        derived (composition)
    flag:         none
    reviewed:     2026-08-12 (see .agents/reports/dashboard/review.md)

    routes:   /core/dashboard, /api/core/dashboard/summary [GET], /api/core/metrics [GET]
    backend:  app/core/backend/backend.py:4100-4780 (summary, action board, weekly series)
              app/core/backend/backend.py:4781-4836 (metrics)
    frontend: frontend/dashboard/dashboard.html, js/dashboard.js,
              js/core-active-batches-graph.js (813), css/dashboard_spa.css
    tests:    test_dashboard_summary

    depends on:      platform, execution, inventory, wastage, compliance-checks, activity-log
    depended on by:  (leaf)

    - COMPOSITION SLICE: it aggregates six others. The rule that makes the taxonomy hold is
      that it consumes their services, never queries their tables directly. Today it does
      query directly — _dashboard_event_counts_by_day (:4375) hits EntityEvent and
      _dashboard_execution_counts_by_day (:4395) hits Execution, both bypassing the repos.
      That's the debt this slice exists to name.
    - Reads config.crm_enabled at :4666 — the only feature-flag branch inside core.

## crm

    subscription: core (built = core tier; NOT a separate paid add-on)
    layer:        integration
    flag:         crm_enabled — a feature toggle, not a tier gate. The only flag that
                  actually gates a blueprint (app_factory.py:112). True in local.ini.
    reviewed:     2026-08-15 (see .agents/reports/crm/review.md)

    routes:   /crm/* — pages, api, oauth. Parent blueprint composes crm_api/crm_pages/crm_oauth.
    backend:  app/features/crm/{routes,services,repositories,models,frontend}/
              crm_service.py (1253), xero_api_client (590), xero_sync_service (388),
              xero_oauth_service (267), xero_invoice_repo (728)
    models:   CrmNote, CrmTask, ProductMapping, SalesTraceabilityConfig, XeroContact,
              XeroInvoice, XeroInvoiceLineItem, XeroOAuthToken, XeroSyncJob, XeroTenant
    tests:    test_crm, e2e/test_crm_flow

    depends on:      platform, inventory (product mapping), execution (sales traceability)
    depended on by:  dashboard (flag check only)

    - ALREADY CORRECTLY SLICED. This is the reference layout for the whole carve
      (conventions.md §1). Copy this shape; do not copy backend.py's.
    - Talks to a real external API. Xero calls need token refresh (xero_oauth_service) and
      have their own sync-job table for retries.

## dilution-calculator

    subscription: core
    layer:        domain (stateless — no models, no repos, no tenant data)
    flag:         none — registered unconditionally (app_factory.py:106)
    reviewed:     never

    routes:   /dilution-calculator [GET]                    (page)
              /api/dilution-calculator/solve [POST]         (stateless solve)
    backend:  app/features/dilution_calculator/
                dilution_calculator_bp.py (16 — blueprint factory)
                routes/page_routes.py (13), routes/api_routes.py (31)
                services/dilution_service.py (165)
    models:   none
    repos:    none
    frontend: frontend/templates/dilution_calculator/index.html (209)
    spec:     .agents/specs/dilution_calculator.md
    tests:    test_dilution_calculator

    depends on:      platform (requires_auth, observability) only
    depended on by:  (leaf — nothing reads it)

    - REFERENCE LAYOUT. At 225 lines across bp factory + routes/ + services/, this is the
      cleanest example of the target shape in the repo — better than CRM for seeing the
      pattern at a glance, because it's small enough to read in one sitting.
    - Note what it does NOT have: no models/, no repositories/, no org_id anywhere. A slice
      is allowed to omit the parts it doesn't need. Don't scaffold empty directories.
    - Auth-gated but tenant-agnostic: the solve endpoint touches no tenant data, so
      org-scope rules don't apply. This is the one slice where the org_id invariant is
      genuinely not in play.
    - The service carries a load-bearing physics distinction in its module docstring: the
      ABV/volume identity is exact, while water_to_add_ml uses an approximate
      mixture-density contraction model. Read it before touching the maths.

## shell

    subscription: n/a
    layer:        shell
    flag:         none
    reviewed:     2026-08-15 (see .agents/reports/shell/review.md)

    routes:   /core (hub), /core/dashboard chrome, /core/settings, /core/integrations
              /core/static/{js,css,img,inventory}/<filename>  (4 serving routes)
              /ui/shared/<filename>  (app_factory.py:115 — .js/.css only, auth by allowlist)
              landing, session-expired
    backend:  app/core/backend/backend.py:605-631 (hub/settings/integrations pages)
              app/core/backend/backend.py:1044-1200 (static serving)
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

    - DEAD FILES, safe to delete: app/ui/templates/components/sidebar.html (nothing includes
      it; still links to the retired /workflow-engine/* nav) and app/ui/shared/sidebar-v2.html
      (unreachable — the /ui/shared route serves .js/.css only). Three sidebar files, one real.
    - Static serving is FLAT: /core/static/js/<filename> resolves one directory,
      app/core/frontend/js/, with a traversal guard and an extension whitelist. Moving JS
      into slice directories breaks every template reference. See plan §3 (asset registry).
    - Templates set active_page to drive sidebar highlighting; core pages nearly all pass
      active_page="core".

## demo-data

    subscription: n/a (dev only)
    layer:        non-product
    flag:         none — but the route self-gates on config.environment
    reviewed:     never

    routes:   /api/core/reset-demo-db [POST]
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
| Config loader (`ENVIRONMENT` → `.ini`) | `app/utils/config_loader.py` (435) |
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

Recorded here because the index is where you'd look before scoping work:

| Slice | Gap |
|---|---|
| reconciliation | 1053 lines, no dedicated test file |
| traceability | no test references sourcemap |
| activity-log | story/summary/activity endpoints untested |
| process-design | no process-docs test |

## Maintaining this file

- Update the affected slice block in the same MR that moves or adds a route. A stale index
  is worse than none, because it is trusted.
- `backend.py` line ranges drift with every edit to that file. If a range doesn't match what
  you find, re-locate it and fix the entry.
- Re-verify wholesale after each phase of the slicing plan.
- Staleness automation for `routes:`/`backend:` line ranges is open item 1 in the plan
  (§6) — not built yet. That's a different problem from the one below: this one is about
  the index describing code accurately, not about whether a slice has been reviewed.
- The `reviewed:` field's staleness *is* handled: `scripts/feature_index_sweep.py` reconciles
  it against `.agents/reports/<slug>/review.md` (a completed review) and live `review/<slug>`
  worktrees (one in flight) every time `review-feature` or `entrypoint` runs, and writes the
  line itself — never hand-edit `reviewed:`. See the field's own description above for the
  three states it can hold.
