# Mobile page copy inventory

The work-board PostgreSQL database (`bize_dev`, schema `work`) now has a searchable
index of page copy. This is the starting map for reducing text density on phones.
It tracks the desktop wording, proposed mobile treatment, optional short wording,
and review state for each page, container and text entry. The index holds source
copy only; it contains no tenant records.

## Snapshot and coverage

Source: `origin/main` at `d117eb32864c4f97a13a937c5fad0751f6d02556`.

| Item | Count |
| --- | ---: |
| HTML templates scanned | 142 |
| Directly mapped to a route | 90 |
| Standalone or base templates needing route review | 11 |
| Shared fragments and layouts | 41 |
| Text entries (visible text, labels, placeholders, dynamic bindings) | 3,928 |
| Container groups | 865 |
| Include/inheritance links | 157 |

The source scanner records visible text, `aria-label`, `placeholder`, `title`,
`alt`, `x-text` and `x-html`. Text generated solely in JavaScript, API responses,
or database values is marked as a dynamic gap until the rendered page is checked
in a browser. Route patterns come from static route decorators and
`add_url_rule`; indirect render helpers are marked `page_route_unmapped`.
Shared fragments have their own rows and links to templates that include them.
Admin paths are on the separate admin host, so their paths are relative to that
host. One row from `/crm` is already marked `proposed`: collapse the credit-note
introduction behind a short phone summary while keeping its full explanation
available on expansion.

The `work.mobile_copy_containers` table is the main review queue. Its
`mobile_treatment` field accepts a human choice such as `keep`, `shorten`,
`collapse`, `hint` or `hide`; `mobile_text` holds the proposed short copy and
`review_state` tracks work from `unreviewed` through `proposed`, `implemented`
and `verified`. Automated suggestions are triage only. A long form can have
many short labels, and legal or safety copy must stay accessible even if it is
long.

`work.mobile_copy_page_progress` groups those decisions by page, so the next
page can be selected by unreviewed containers and visible words. The first
page changes are in !666 (Sales overview, stacked on !664), !667 (Sales
settings), !668 (Sales excise estimate), and !669 (Go live).

## First pages to review on a phone

| Route | Main issue to inspect | Initial treatment to test |
| --- | --- | --- |
| `/crm` | Credit-note introduction and the overview's many cards | Keep the decision prompt only when needed; shorten the introduction on phone and provide full context through disclosure. |
| `/crm/configuration` | Matching and sync explanations in forms | Put the operational choice first; move examples and edge cases into help disclosures. |
| `/crm/excise` | A dense estimate report with explanatory copy | Keep the amount, period and filing link visible; collapse calculation details below them. |
| `/core` | Start-process guidance and several status panels | Keep the next action and active batch state visible; shorten process education in the form. |
| `/settings` | Security setup and records-export explanation | Keep required security steps fully readable; split supporting explanation into steps. |
| `/core/go-live` | Long onboarding steps | Show one short action summary per step, with examples on expansion. |
| `/compliant/nz-alcohol/configuration` | Dense registration and programme choices | Keep legal obligations and selected programme visible; use progressive explanation for alternatives. |
| `/terms`, `/privacy` | Full legal documents | Keep the complete text available; improve phone navigation by section, without hiding the substance. |

## Querying the index

Page-by-page container text, including the review fields:

```sql
SELECT p.route_patterns, p.template_name, c.container_key,
       c.word_count, c.desktop_text, c.suggested_mobile_treatment,
       c.mobile_treatment, c.mobile_text, c.review_state
FROM work.mobile_copy_pages p
JOIN work.mobile_copy_containers c USING (page_key)
WHERE p.route_patterns LIKE '%/crm%'
ORDER BY p.route_patterns, c.word_count DESC;
```

Search a phrase across all indexed text:

```sql
SELECT p.route_patterns, t.page_key, t.container_key, t.source_line, t.desktop_text
FROM work.mobile_copy_text t
JOIN work.mobile_copy_pages p USING (page_key)
WHERE to_tsvector('english', t.desktop_text || ' ' || coalesce(t.mobile_text, ''))
      @@ plainto_tsquery('english', 'credit note')
ORDER BY p.route_patterns, t.source_line;
```

Find shared fragments that contribute to a page:

```sql
SELECT p.template_name AS page, r.relation, shared.template_name AS shared_template
FROM work.mobile_copy_relations r
JOIN work.mobile_copy_pages p ON p.page_key = r.page_key
JOIN work.mobile_copy_pages shared ON shared.page_key = r.included_page_key
WHERE p.route_patterns LIKE '%/crm%';
```

Find the next routed pages with the most unreviewed visible text:

```sql
SELECT route_patterns, template_name, unreviewed, visible_words,
       proposed, implemented, verified
FROM work.mobile_copy_page_progress
WHERE page_kind = 'routed'
ORDER BY unreviewed DESC, visible_words DESC;
```

## Refreshing the map

The schema is in `scripts/mobile_copy_work_schema.sql`. After applying it to
the work-board database, run:

```bash
python scripts/mobile_copy_inventory.py --output /tmp/mobile-copy-inventory
python scripts/mobile_copy_work_load.py /tmp/mobile-copy-inventory
```

The loader uses the same local PostgreSQL container and role as `wb`, and
preserves reviewer-entered `mobile_treatment`, `mobile_text` and `review_state`
on matching rows. Changed source rows retain their old snapshot until they are
reconciled; filter by `source_commit` when comparing runs. The source line and
container key identify rows, so a structural template edit may create a new
row that needs a fresh review.

## Page list

The table below lists every scanned template. The database contains the text
of each container and the source line for every entry.

| Route | Template | Kind | Containers | Visible words | Long passages | Dynamic bindings |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| / | `landing.html` | routed | 27 | 459 | 6 | 0 |
| /api/compliant/reports/<report_id> | `compliant/audit_pack.html` | routed | 2 | 72 | 0 | 0 |
| /attention | `admin/attention.html` | routed | 4 | 57 | 0 | 0 |
| /auth/google/callback<br>/auth/google/challenge | `google_sign_in.html` | routed | 3 | 31 | 0 | 0 |
| /auth/google/callback<br>/sign-in | `admin/sign_in.html` | routed | 3 | 20 | 0 | 0 |
| /compliant | `compliant/home.html` | routed | 13 | 68 | 0 | 0 |
| /compliant/nz-alcohol | `compliant/dashboard.html` | routed | 8 | 53 | 0 | 0 |
| /compliant/nz-alcohol/configuration | `compliant/configuration.html` | routed | 12 | 233 | 1 | 0 |
| /compliant/nz-alcohol/customs | `compliant/customs.html` | routed | 3 | 16 | 0 | 0 |
| /compliant/nz-alcohol/customs/records | `compliant/customs_records.html` | routed | 1 | 4 | 0 | 0 |
| /compliant/nz-alcohol/customs/records/<control_id> | `compliant/customs_record_check.html` | routed | 0 | 0 | 0 | 0 |
| /compliant/nz-alcohol/customs/settings | `compliant/customs_settings.html` | routed | 11 | 174 | 2 | 0 |
| /compliant/nz-alcohol/customs/stock | `compliant/customs_stock.html` | routed | 9 | 123 | 3 | 0 |
| /compliant/nz-alcohol/customs/transfers | `compliant/customs_transfers.html` | routed | 5 | 99 | 1 | 0 |
| /compliant/nz-alcohol/food-registrations | `compliant/food_registrations.html` | routed | 7 | 68 | 0 | 0 |
| /compliant/nz-alcohol/food-safety | `compliant/np3_audit.html` | routed | 3 | 21 | 0 | 0 |
| /compliant/nz-alcohol/food-safety/checks | `compliant/np3_checks.html` | routed | 1 | 5 | 0 | 0 |
| /compliant/nz-alcohol/licensing | `compliant/licensing.html` | routed | 11 | 176 | 0 | 0 |
| /compliant/nz-alcohol/np3-audit/check/<control_id> | `compliant/np3_check.html` | routed | 3 | 8 | 0 | 0 |
| /compliant/nz-alcohol/premises | `compliant/premises.html` | routed | 5 | 115 | 0 | 0 |
| /compliant/tools | `compliant/tools.html` | routed | 3 | 57 | 1 | 0 |
| /core<br>/core/executions/live<br>/core/inventory/live | `core/core2.html` | routed | 51 | 673 | 2 | 0 |
| /core/cases | `operational_cases/queue.html` | routed | 2 | 42 | 0 | 0 |
| /core/cases/<case_id> | `operational_cases/detail.html` | routed | 7 | 34 | 0 | 0 |
| /core/cases/new | `operational_cases/new.html` | routed | 2 | 27 | 0 | 0 |
| /core/contracts | `contracts/home.html` | routed | 14 | 206 | 0 | 0 |
| /core/contracts/<uuid:order_id> | `contracts/order.html` | routed | 11 | 141 | 2 | 0 |
| /core/contracts/<uuid:order_id>/portal-sharing | `contracts/sharing.html` | routed | 13 | 295 | 3 | 0 |
| /core/contracts/materials | `contracts/materials.html` | routed | 4 | 96 | 1 | 0 |
| /core/dashboard | `dashboard/dashboard.html` | routed | 25 | 207 | 0 | 0 |
| /core/executions/<execution_id>/steps/<execution_step_id>/record | `processes/execution-step-record.html` | routed | 3 | 77 | 0 | 0 |
| /core/flows | `processes/flows2.html` | routed | 9 | 70 | 0 | 0 |
| /core/flows/batches/start | `processes/batch-start.html` | routed | 1 | 7 | 0 | 0 |
| /core/flows/create/evidence-and-prompts | `processes/process-flow-evidence-and-prompts.html` | routed | 2 | 53 | 1 | 0 |
| /core/flows/create/inputs | `processes/process-flow-inputs.html` | routed | 1 | 28 | 1 | 0 |
| /core/flows/create/next-steps | `processes/process-flow-next-steps.html` | routed | 6 | 103 | 2 | 0 |
| /core/flows/create/outputs | `processes/process-flow-outputs.html` | routed | 2 | 55 | 2 | 0 |
| /core/flows/create/process-overview | `processes/process-flow-process-overview.html` | routed | 4 | 82 | 2 | 0 |
| /core/flows/create/start | `processes/flow-create-chooser.html` | routed | 3 | 47 | 0 | 0 |
| /core/flows/create/step-name | `processes/process-flow-step-name.html` | routed | 2 | 50 | 2 | 0 |
| /core/flows/create/summary | `processes/process-flow-summary.html` | routed | 3 | 61 | 1 | 0 |
| /core/flows/create/template-catalog | `process_templates/template-catalog.html` | routed | 4 | 73 | 0 | 0 |
| /core/getting-started | `getting_started/getting_started.html` | routed | 4 | 52 | 1 | 0 |
| /core/go-live | `go_live/go_live.html` | routed | 6 | 196 | 5 | 0 |
| /core/integrations | `integrations/integrations.html` | routed | 6 | 119 | 0 | 9 |
| /core/inventory/add | `inventory/add.html` | routed | 2 | 47 | 0 | 0 |
| /core/inventory/add/barcode | `inventory/add_barcode.html` | routed | 8 | 112 | 0 | 0 |
| /core/inventory/add/csv | `inventory/add_csv.html` | routed | 5 | 67 | 0 | 0 |
| /core/inventory/add/manual | `inventory/add_manual.html` | routed | 7 | 76 | 0 | 0 |
| /core/inventory/dispose | `inventory/dispose.html` | routed | 4 | 63 | 1 | 0 |
| /core/inventory/dispose/confirm | `inventory/dispose_confirm.html` | routed | 4 | 92 | 1 | 0 |
| /core/inventory/view | `inventory/view.html` | routed | 8 | 66 | 0 | 0 |
| /core/notifications | `notifications/notifications.html` | routed | 2 | 20 | 0 | 0 |
| /core/people | `people/people.html` | routed | 10 | 157 | 2 | 0 |
| /core/planner | `planning/demand.html` | routed | 10 | 102 | 0 | 0 |
| /core/planner/board | `planning/board.html` | routed | 15 | 146 | 0 | 0 |
| /core/processes | `processes/list.html` | routed | 5 | 55 | 0 | 0 |
| /core/record | `record_step/record_step.html` | routed | 3 | 44 | 0 | 0 |
| /core/settings<br>/settings<br>/workflow-engine/settings | `settings/settings.html` | routed | 24 | 391 | 2 | 0 |
| /core/site-transfers | `site_transfers/transfers.html` | routed | 4 | 28 | 0 | 0 |
| /core/site-transfers/<transfer_id>/docket | `site_transfers/docket.html` | routed | 5 | 51 | 0 | 0 |
| /core/sites | `sites/sites.html` | routed | 6 | 61 | 0 | 0 |
| /core/sourcemap | `sourcemap/sourcemap.html` | routed | 7 | 92 | 0 | 0 |
| /core/stocktake | `stocktake/stocktake.html` | routed | 11 | 125 | 0 | 0 |
| /core/suppliers | `suppliers/suppliers.html` | routed | 4 | 27 | 0 | 0 |
| /core/tasks/configuration | `tasks/configuration.html` | routed | 7 | 100 | 1 | 7 |
| /crm | `crm/overview.html` | routed | 33 | 285 | 1 | 72 |
| /crm/analytics | `crm/analytics.html` | routed | 18 | 251 | 0 | 45 |
| /crm/configuration | `crm/configuration.html` | routed | 21 | 461 | 1 | 37 |
| /crm/customers | `crm/customers.html` | routed | 8 | 152 | 0 | 25 |
| /crm/customers/<contact_id> | `crm/customer_detail.html` | routed | 42 | 399 | 0 | 93 |
| /crm/excise | `crm/excise.html` | routed | 8 | 207 | 1 | 26 |
| /crm/matching | `crm/matching.html` | routed | 8 | 122 | 0 | 23 |
| /crm/tasks | `crm/tasks.html` | routed | 33 | 122 | 0 | 42 |
| /crm/xero/select-tenant | `crm/select_tenant.html` | routed | 3 | 24 | 0 | 0 |
| /demo | `admin/demo.html` | routed | 3 | 47 | 1 | 0 |
| /invite/<token> | `invite.html` | routed | 4 | 106 | 1 | 0 |
| /organisations | `admin/organisations.html` | routed | 7 | 58 | 0 | 0 |
| /organisations/<org_id> | `admin/organisation.html` | routed | 26 | 175 | 0 | 0 |
| /organisations/<org_id>/audit | `admin/audit.html` | routed | 3 | 42 | 0 | 0 |
| /organisations/<org_id>/users/<user_id> | `admin/person.html` | routed | 12 | 276 | 1 | 0 |
| /people | `admin/people.html` | routed | 4 | 36 | 0 | 0 |
| /portal | `portal/home.html` | routed | 3 | 12 | 0 | 0 |
| /portal/invite | `portal/invite.html` | routed | 2 | 27 | 0 | 0 |
| /portal/login | `portal/login.html` | routed | 2 | 31 | 0 | 0 |
| /portal/orders/<uuid:order_id> | `portal/order.html` | routed | 15 | 211 | 0 | 0 |
| /pricing | `legal/pricing.html` | routed | 2 | 94 | 1 | 0 |
| /privacy | `legal/privacy.html` | routed | 1 | 515 | 9 | 0 |
| /system | `admin/system.html` | routed | 5 | 39 | 0 | 0 |
| /terms | `legal/terms.html` | routed | 1 | 596 | 10 | 0 |
| — | `admin/base.html` | page_route_unmapped | 3 | 16 | 0 | 0 |
| — | `admin/error.html` | page_route_unmapped | 1 | 6 | 0 | 0 |
| — | `biz-e-diagram-landing.html` | page_route_unmapped | 1 | 13 | 0 | 0 |
| — | `errors/error.html` | page_route_unmapped | 2 | 34 | 0 | 0 |
| — | `legal/_page.html` | page_route_unmapped | 2 | 20 | 0 | 0 |
| — | `portal/base.html` | page_route_unmapped | 3 | 18 | 0 | 0 |
| — | `processes/execution-step-page.html` | page_route_unmapped | 0 | 0 | 0 | 0 |
| — | `processes/process-flow-spa.html` | page_route_unmapped | 6 | 151 | 1 | 0 |
| — | `session_expired.html` | page_route_unmapped | 2 | 24 | 0 | 0 |
| — | `shared/base_spa.html` | page_route_unmapped | 4 | 55 | 0 | 3 |
| — | `tasks/tasks.html` | page_route_unmapped | 0 | 0 | 0 | 0 |
| — | `app/ui/shared/account-info.html` | shared | 1 | 7 | 0 | 0 |
| — | `app/ui/shared/sidebar-v2.html` | shared | 2 | 13 | 0 | 0 |
| — | `compliant/_customs_header.html` | shared | 2 | 11 | 0 | 0 |
| — | `compliant/_np3_header.html` | shared | 2 | 26 | 0 | 0 |
| — | `compliant/_verification_panel.html` | shared | 4 | 129 | 1 | 0 |
| — | `components/header.html` | shared | 0 | 0 | 0 | 0 |
| — | `components/sidebar.html` | shared | 4 | 18 | 0 | 0 |
| — | `contracts/_line_fields.html` | shared | 1 | 21 | 0 | 0 |
| — | `crm/_crm_banner.html` | shared | 0 | 0 | 0 | 0 |
| — | `google_account_settings.html` | shared | 5 | 61 | 0 | 0 |
| — | `processes/batch-start-fragment.html` | shared | 6 | 61 | 0 | 0 |
| — | `processes/batch-start-scripts.html` | shared | 0 | 0 | 0 | 0 |
| — | `processes/create-process-modal.html` | shared | 4 | 197 | 2 | 0 |
| — | `processes/create-process-step-content-styles.html` | shared | 0 | 0 | 0 | 0 |
| — | `processes/create-process-step-content.html` | shared | 11 | 386 | 2 | 0 |
| — | `processes/execution-step-fragment.html` | shared | 1 | 8 | 0 | 0 |
| — | `processes/flows2-modals.html` | shared | 5 | 66 | 0 | 0 |
| — | `processes/process-wizard-carried-step-fields.html` | shared | 0 | 0 | 0 | 0 |
| — | `processes/process-wizard-fragment-indicators.html` | shared | 1 | 4 | 0 | 0 |
| — | `processes/process-wizard-fragment-post-creation.html` | shared | 1 | 16 | 0 | 0 |
| — | `processes/process-wizard-fragment-shared-top.html` | shared | 1 | 37 | 0 | 0 |
| — | `processes/process-wizard-fragment-step1.html` | shared | 1 | 45 | 0 | 0 |
| — | `processes/process-wizard-fragment-step2.html` | shared | 4 | 117 | 1 | 0 |
| — | `processes/process-wizard-fragment-step3.html` | shared | 2 | 63 | 1 | 0 |
| — | `processes/process-wizard-fragment-step4.html` | shared | 7 | 114 | 0 | 0 |
| — | `processes/process-wizard-more-information-macro.html` | shared | 2 | 5 | 0 | 0 |
| — | `processes/process-wizard-sticky-bar.html` | shared | 1 | 13 | 0 | 0 |
| — | `shared/back_link.html` | shared | 1 | 1 | 0 | 0 |
| — | `shared/breadcrumbs.html` | shared | 1 | 0 | 0 | 0 |
| — | `shared/delete-doc-confirm-modal.html` | shared | 1 | 14 | 0 | 0 |
| — | `shared/execution-modal.html` | shared | 11 | 78 | 0 | 0 |
| — | `shared/execution_modal_stack_scripts.html` | shared | 0 | 0 | 0 | 0 |
| — | `shared/page_header.html` | shared | 0 | 0 | 0 | 0 |
| — | `shared/primary_card.html` | shared | 0 | 0 | 0 | 0 |
| — | `shared/section_tabs.html` | shared | 1 | 0 | 0 | 0 |
| — | `shared/sidebar-v2.html` | shared | 2 | 13 | 0 | 0 |
| — | `shared/spa-fixed-action-bar.html` | shared | 1 | 0 | 0 | 0 |
| — | `shared/system-findings-banner.html` | shared | 6 | 19 | 0 | 0 |
| — | `shared/workspace_links.html` | shared | 1 | 0 | 0 | 0 |
| — | `tasks/_board.html` | shared | 9 | 106 | 0 | 20 |
| — | `tastings/index.html` | shared | 5 | 163 | 0 | 0 |
