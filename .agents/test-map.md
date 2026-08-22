# Core-flow test map

Owned by the **test-author** skill. This is a *flow-based* coverage inventory — the core
user journeys through the app, the test files that prove them, and an honest status per
row. It is deliberately not line-coverage: the question is "would a human walking this flow
hit an untested path", not "what percent of lines executed".

`scripts/test_map_check.py` keeps it structurally honest — it flags rows whose test file no
longer exists and `tests/test_*.py` files that appear in no row. It cannot judge whether a
row's **status** is truthful; that is test-author's job to keep current as it writes, and
test-evaluator's to catch when a test claims more than it proves.

last_synced: 2026-08-22
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
| 4 | Password policy + change-password | auth_routes (`/password-policy-check`,`/change-password`) | test_auth_password_session.py | covered | Batch 7: policy flags weak / accepts strong; change-password success (new pw logs in, old rejected), wrong-current 400, confirm-mismatch 400, same-as-current 400 |
| 5 | Session timeout + safe return-to | auth_routes (`/session-timeout`), middleware | test_auth_password_session.py, test_safe_flow_return_to.py | covered | Batch 7: GET returns bounds; PUT valid accepted, below-min 400, missing 400. Return-to open-redirect guard in test_safe_flow_return_to.py |

## Organisation & tenancy

| # | Flow | App area | Test file(s) | Status | Notes |
|---|---|---|---|---|---|
| 6 | Org read / patch settings | `app/api/routes/org_routes.py` (`GET/PATCH ""`) | test_org_routes.py | covered | Batch 5: GET returns org; unauthenticated GET → 302 login redirect; PATCH name as admin persists; PATCH as member → 403 |
| 7 | Org membership (list/add/remove users) | org_routes (`/users`, `/users/<id>`) | test_org_routes.py | covered | Batch 5: list includes members; create as admin (201) / member forbidden (403) / duplicate email (400); delete member (200) / self (400) / unknown (404) |
| 8 | **Tenant isolation — org A cannot read/write org B** | every `org_id`-scoped repository | test_multi_tenant_isolation.py | covered | Batch 2: process/execution/inventory get+list+delete each proven org-scoped, hostile-org case AND same-org control. Built ProcessFactory/ExecutionFactory + a `world` fixture on `two_org_two_user`. Wastage repo → Batch 3. (`test_multi_tenant_api.py` remains a manual `main()` script, kept as a manual tool) |

## Process, DAG & execution

| # | Flow | App area | Test file(s) | Status | Notes |
|---|---|---|---|---|---|
| 9 | Process CRUD + steps (add/reorder/delete) | core_bp `/api/core/processes*` | test_executions.py, test_corechecks.py, test_multi_tenant_isolation.py, test_process_design.py, tests/e2e/test_process_steps_flow.py | covered | CRUD in test_executions/corechecks; org-isolation of get/list/delete added in Batch 2. review/process-design audit (this batch): test_process_design.py fills the fast-unit-test validation/error-branch gap create_process/update_process/delete_process/get_process/add_step/update_step/delete_step/reorder_steps had zero unit coverage of (400/404/409 branches, no-op-update-writes-no-version, IntegrityError→409, reorder payload validation) plus `_next_step_position` and `process_docs_validation.py`'s MIME-detection/step-ownership branches; e2e suite (test_process_steps_flow.py) already covers the reorder endpoint end-to-end including its two documented gaps (missing audit trail, off-grid-position 500 not 400) |
| 10 | DAG traversal | `app/core/backend/dagtraversal.py` | test_dag_traversal.py | covered | 29 tests, cycles + ordering |
| 11 | Execution lifecycle (create → complete step) | core_bp `/api/core/executions*` | test_executions.py, test_complete_step_payload.py | covered | Batch 4 re-assessment: create-materialises-steps, in-order advancement, full completion, out-of-order rejected, double-completion rejected, step-failure does not advance, wrong-org → None — all in test_executions.py (45 tests) |
| 12 | ~~Idempotency (`ApiIdempotencyKey`) on executions~~ | n/a | test_wastage.py (the real user) | covered | **Gap-analysis correction (Batch 4):** there is no execution idempotency-key mechanism — `ApiIdempotencyKey` is used only by the wastage route (row 16, covered in Batch 3). create_execution has no dedup; execution replay-safety is the `complete_step` state guard in row 11. No new test owed |
| 13 | Execution lineage (parent→child) | `workflow_execution_lineage`, reconciliation_service | test_dag_traversal.py (helpers) | partial | traversal helpers touch it; lineage-record assertions absent |
| 29 | Industry process template catalogue: scratch/template chooser, capability-gated catalogue browse, copy-into-tenant, sample_only WIP override | `app/features/process_templates/*`, `app/core/backend/backend.py` (`flows_create_start_chooser`, the `sample_only` block in `complete_step`) | test_process_templates.py, tests/e2e/process_templates/ | covered | **new-feature (2026-08-22):** `none → covered`. test_process_templates.py (29 tests): capability/module policy resolution incl. a synthetic second-module registration proving the seam needs no route/service change (AC4), the chooser's new `/core/flows/create/start` route leaving the existing `/core/flows/create` route provably unmodified, catalogue list/detail/copy API (family filter, 404 on a real-but-unpermitted template id, advisory string), tenant isolation of a copied process (repository-level cross-org probe), execution lineage through a copied template, the `sample_only` output-type override with a control case proving the mechanism it replaces (`is_terminal_step`) still governs when the flag is absent, the wizard-summary resume, and both new structured-log lines. tests/e2e/process_templates/ (8 tests): the same flows through a real browser — found and fixed two real bugs neither unit tests nor manual review had caught (static-asset route's Flask endpoint name colliding with `tenant_context.py`'s `.static`-suffix public-endpoint convention, and a CSS `display` rule defeating the `[hidden]` attribute on the preview modal), both `.agents/reports/process_templates/e2e-playwright.md`. |
| 28 | Traceability / sourcemap (forward/backward trace, on-demand current+temporal trace, sourcemap objects index) | `app/core/backend/backend.py` (`trace_raw_material`, `trace_inventory_backward`, `sourcemap_objects`, `sourcemap_trace`), `app/core/backend/temporal_dag_tracer.py`, `app/core/frontend/sourcemap/*` | test_traceability.py, tests/e2e/traceability/ | covered | **review-feature (2026-08-09):** `none → covered` — this slice had zero test references anywhere before this review (`.agents/reports/traceability/baseline.md`). security-audit found and this review fixed 4 findings: F1 a cross-tenant entity-state leak (`TemporalDAGTracer._snapshot_at` had no `org_id` filter — another org's item state was readable via `POST /api/core/sourcemap/trace`'s temporal branch given that org's item UUID), F2 `sourcemap_trace`'s current-state (no `as_of`) branch imported a module that doesn't exist anywhere in the repo and always 500'd (dead, unreachable from the frontend today), F3/F4 unhandled `int()` parsing on `page`/`limit`/`depth` (500 instead of 400). test_traceability.py: F1-F4 regressions plus direct `TemporalDAGTracer` unit coverage (0%→94% on temporal_dag_tracer.py — BFS edge-building, as_of cutoff, cross-org edge exclusion, timeline ordering) and `/api/core/sourcemap/objects` org-scoping (AC18). tests/e2e/traceability/ (19 tests): page load, forward/backward trace rendering (incl. AC7's traced-item-includes-itself), view-switch/wastage-toggle no-refetch, the mandatory cross-tenant probe for all three trace routes (AC2/AC6/AC9 — AC9 is F1's regression, a real two-org browser session), and unhappy paths (non-UUID→400, nonexistent-UUID→404, empty search, no-history item). |

## Evidence

| # | Flow | App area | Test file(s) | Status | Notes |
|---|---|---|---|---|---|
| 27 | Evidence upload/list/download/delete/config | `app/core/backend/evidence/*` | test_evidence.py | covered | **test-author (review-execution, 2026-08-02):** `none → covered`. Route coverage raised from a single uploaded_by regression test to the full surface: config, list (happy/empty/missing-param/invalid-format/org-scoped), download (happy/404-nonexistent/404-cross-org), delete (happy incl. file removal/idempotent-on-missing/cross-org), and upload's unhappy paths (oversized, empty, disallowed MIME via magic-byte sniffing including the "sniffing overrides a lying client Content-Type" property, missing file, invalid execution_id/step_id format, execution not found) plus the three post-commit failure/orphan-cleanup branches in `upload_evidence_from_temp` (checksum-verify failure, `finalize_from_temp` failure, `update_status`-to-ACTIVE failure — each via monkeypatch, each asserted to leave no DB row and no file on disk). Added pure unit tests for `evidence_storage.py` (`is_safe_filename`, `extension_from_mime`, checksum roundtrip, `finalize_from_temp`, path-traversal containment in `read_file_path`, `delete_file` idempotency) and `evidence_validation.py` (`detect_mime_from_path`, `validate_upload_request`) needing no DB. **Finding surfaced, not fixed here (test-only stage):** AC17 states DELETE should 404 for evidence outside the caller's org, but `delete_evidence`'s not-found and cross-org cases share the same idempotent-200 code path (no org-specific branch) — tested and documented as the code's actual behavior in `TestEvidenceDelete::test_delete_cross_org_does_not_remove_the_record`; the record's survival (not the status code) is what's asserted. Route-level org_id-missing/malformed defensive branches (`evidence_routes.py`, reachable only if `g.org_id` were absent post-auth) remain unexercised — low-value, same shape across all four routes. |

## Inventory

| # | Flow | App area | Test file(s) | Status | Notes |
|---|---|---|---|---|---|
| 14 | **Quantity-write guard** (every `InventoryQuantityWriteReason`) | `app/core/domain/inventory_quantity_guard.py` | test_inventory_quantity_guard.py | covered | Batch 1: direct write rejected, create/add/set repository paths accepted, nested-allow rejected, guard re-arms. **Found + fixed a real bug**: `set_inventory_item_quantity` flushed its event outside the allow block, so `POST /api/core/inventory/<id>/adjust` raised on every call |
| 15 | Inventory read / add / out-of-stock / update / delete | core_bp `/api/core/inventory*` | test_corechecks.py, test_inventory.py, test_inventory_repo.py, test_inventory_csv_validation.py | covered | **test-author (review-feature inventory audit, 2026-07-29):** `none → covered`. `update_inventory_item`/`delete_inventory_item` repo mutations (both quantity/no-quantity branches, tombstone-before-row-gone) added in test_inventory_repo.py; `_validate_row`/`_parse_date`/`_sanitize`/`_unit_to_canonical` CSV pure helpers added in test_inventory_csv_validation.py (no DB needed); F3 huge-exponent quantity added for the PUT route (create-only before); AC8 out-of-stock "exactly" now has nonzero + non-raw-material decoys (tests/e2e/test_inventory_flow.py); AC27 units-dropdown now asserts full equality with `CONVERSION_FACTORS`, not just membership |
| 16 | Wastage entry + batch-hash idempotency | core_bp `/api/core/inventory/wastage` | test_wastage.py, test_inventory_wastage_quantity.py | covered | Batch 3: records+deducts, idempotent replay does not double-deduct, key reuse with a different payload → 409, wastage rows org-scoped. **test-author (2026-07-29):** added the AC14 three-way atomicity regression (forces a mid-batch failure via monkeypatch and proves item quantity + wastage row + movement row all roll back together, including the already-staged first entry — the test-evaluator's top blocking finding); AC16 unit-conversion + movement_metadata (converted_from_unit/canonical_unit) happy path and incompatible-unit 400; AC12/AC13 batch-size cap and duplicate-item-in-batch; AC17 invalid idempotency-key forms (empty/non-string/>128 chars); pure parsing/hash edge branches (negative-zero, out-of-range magnitude, hash order-stability) in test_inventory_wastage_quantity.py |
| 17 | Unit conversion | `app/core/utils/unit_conversion.py` | test_unit_conversion.py, tests/js/ | covered | Batch 6: server-side compatibility rules + float/decimal conversion + storage-aligned quantization + refusals; JS side already covered |
| 25 | CSV bulk upload (validate preview → commit, dup-batch skip, audit history) | `app/core/backend/inventory_upload_routes.py` | test_inventory_csv_validation.py, tests/e2e/test_inventory_csv_flow.py | covered | **test-author (2026-07-29):** pure helper unit tests (no DB) for the shared `_validate_row`/`_parse_date`/`_sanitize`/`_unit_to_canonical`/`_parse_quantity` used by both preview and commit (AC20/AC21/AC23); e2e file strengthened per test-evaluator round 2 — missing-column check now covers all three required columns (was Unit-only), over-max-rows commit now proves zero rows written, duplicate-batch-skip now asserts the colliding row's final count/quantity is unchanged, and AC25's acting-user requirement is proven at the DB level in tests/test_inventory.py (`test_csv_commit_records_acting_user_in_audit_history`) since the list API deliberately redacts `user_id` from audit-history entries |
| 26 | Untracked-item reconciliation (Path A addition, Path B via-execution, matching-untracked) | `app/core/backend/reconciliation_routes.py` | test_reconciliation_routes.py, tests/e2e/test_inventory_flow.py | covered | **test-author (2026-07-29):** `partial → covered`. Added the AC29/AC30 400 request-validation paths (malformed process_id, missing name/quantity/unit, invalid untracked_item_id) route-level in test_reconciliation_routes.py; strengthened matching-untracked to require differently-named/unitted decoys stay absent, and via-addition's missing-fields branch to prove no row was created (not just a 400), per test-evaluator round 2 |

## Dilution calculator

| # | Flow | App area | Test file(s) | Status | Notes |
|---|---|---|---|---|---|
| 24 | Solve dilution (a,b,c,d identity + water-to-add) — happy path, validation, determinism | `app/features/dilution_calculator/services/dilution_service.py`, `routes/api_routes.py`, `routes/page_routes.py` | test_dilution_calculator.py, tests/e2e/test_dilution_calculator_flow.py | covered (100%) | review-feature 2026-08-21: 39 unit/service tests (100% line coverage — closed the 4 gaps found by coverage check: ABV=100 given-value boundary, non-dict payload direct-call guard, post-solve starting_abv>100 overshoot, post-solve starting_volume_ml non-positive result) + 13 E2E tests (added AC5's ABV-branch + divisor-guard UI paths, AC4 range/positivity/required-field UI paths, AC3 round-trip via UI for all 4 solve directions). Stateless — no `org_id` scoping to test (no tenant data read or written; cross-tenant probe does not apply); blueprint always registered (no feature flag). Nested-blueprint feature-tag mapping regression covered separately in test_observability_context.py (row 23) |

## CRM & Xero (feature flag `crm_enabled`)

| # | Flow | App area | Test file(s) | Status | Notes |
|---|---|---|---|---|---|
| 18 | Customers / invoices / notes / tasks | `app/features/crm/routes/api_routes.py` | test_crm.py, e2e/test_crm_flow.py | partial | review-feature 2026-08-15: 60 unit + 9 e2e tests. Added tenant-ownership check + regression test for notes (was missing, unlike tasks), access_denied observability on all 14 org-scoped lookups, cross-tenant e2e probes for notes/tasks/product-mappings, `xero_api_client.py` pure-helper coverage (0%→covered: status/scope/PDF/error-message parsing). Still partial: `xero_api_client.py`'s live-network paths (get_all_contacts/create_invoice/etc.) need a stubbed Xero HTTP layer, not attempted here (34% covered). **findings-sweep 2026-08-16:** closed the `create_invoice` half of that gap — `TestCRMInvoiceCreation` (4 tests) stubs `XeroAPIClient.create_invoice`/`get_all_contacts`/`get_all_invoices`, covering happy path, missing-line-items 400, contact-missing-xero-id rejection, and the cross-tenant case (org B cannot invoice org A's customer, and a rejected attempt leaves no `XeroInvoice` row against org A). `get_all_contacts`/`get_all_invoices` sync paths remain unstubbed. |
| 19 | Analytics (sales, churn, rankings) | crm api_routes `/api/crm/analytics/*` | test_crm.py | partial | some analytics endpoints uncovered — unchanged by 2026-08-15 review, out of scope (no findings there) |

## Dashboard & cross-cutting

| # | Flow | App area | Test file(s) | Status | Notes |
|---|---|---|---|---|---|
| 20 | Dashboard summary | core_bp `/core/dashboard` | test_dashboard_summary.py | covered | Batch 6 re-assessment: `test_dashboard_operations_summary_org_isolated` already proves cross-org isolation; task/compliance/action-board summaries covered too. Original "no cross-org test" note was wrong |
| 21 | Core system checks | `app/core/backend/corechecks.py` | test_corechecks.py | covered | 23 tests |
| 22 | Frontend asset/guards (execution modal, batches) | core frontend JS/templates | test_execution_modal_frontend_assets.py, test_batches_refactor_frontend_guards.py, test_execution_shared_utils_js.py | covered | asset-presence + guard tests |
| 23 | Observability (logging/tracing/telemetry ingress/CLI) | `app/observability/*` | test_observability_*.py (10 files) | covered | broad; owned jointly with observability skill |

## Known highest-value gaps (test-author works these first)

Rows 6/7/8/12/14/16, listed here in earlier revisions, are now `covered` (or, for row 12,
corrected away — see its Notes) per the table above; findings-sweep found this section had
gone stale against its own table (2026-08-16) and `scripts/test_map_check.py` now checks
for the same drift going forward. Current gaps, in priority order:

1. **Row 18** — CRM/Xero `partial`: `xero_api_client.py`'s live-network paths
   (`get_all_contacts`/`create_invoice`/etc.) need a stubbed Xero HTTP layer; not attempted
   yet (34% covered).
2. **Row 13** — execution lineage `partial`: traversal helpers touch
   `workflow_execution_lineage`, but lineage-record assertions are absent.
3. **Row 19** — CRM analytics `partial`: some `/api/crm/analytics/*` endpoints uncovered.

## Not in this map (owned elsewhere)

- Browser / end-to-end journeys → `e2e-playwright` (`.agents/specs/playwright-e2e.md`).
- The 2FA live-server suites' *gating* (when they skip vs run) → `suite-warden`.
- Whether a listed test is a valid claim vs gamed → `test-evaluator`.
