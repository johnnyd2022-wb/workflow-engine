# Mobile page audit index

All navigable page destinations below are **done** at 320 × 844 and 390 × 844. The route tests also passed at 768 × 844. `Done` means Playwright reached the intended page, checked for document overflow and browser errors, saved screenshots, and the screenshot contact sheets were reviewed. Seeded detail pages and the customer portal were exercised with test data. The complete method and acceptance criteria are in the [plan](mobile-page-audit-plan.md).

Screenshot contact sheets: [public and Production](mobile-page-audit/public-production-390.jpg), [Sales and Compliance](mobile-page-audit/sales-compliance-390.jpg), [detail and portal flows](mobile-page-audit/detail-flows-390.jpg), and [320 px view](mobile-page-audit/phone-320-320.jpg). Full-page screenshots were retained in the local test run at `/tmp/mobile-page-audit/screenshots`; the contact sheets are committed as review evidence.

## Public and account pages

| Route | State | Status |
|---|---|---|
| `/` | public | done |
| `/landing-diagram` | public | done |
| `/pricing` | public | done |
| `/privacy` | public | done |
| `/terms` | public | done |
| `/portal/login` | public | done |
| `/portal/invite` | public | done |

## Production pages

| Route | State | Status |
|---|---|---|
| `/core` | authenticated NZ Alcohol test org | done |
| `/core/dashboard` | authenticated NZ Alcohol test org | done |
| `/core/getting-started` | authenticated NZ Alcohol test org | done |
| `/core/go-live` | authenticated NZ Alcohol test org | done |
| `/core/processes` | authenticated NZ Alcohol test org | done |
| `/core/flows` | authenticated NZ Alcohol test org | done |
| `/core/flows/create/process-overview` | authenticated NZ Alcohol test org | done |
| `/core/flows/create/start` | authenticated NZ Alcohol test org | done |
| `/core/flows/create/template-catalog` | authenticated NZ Alcohol test org | done |
| `/core/inventory/view` | authenticated NZ Alcohol test org | done |
| `/core/inventory/live` | authenticated NZ Alcohol test org | done |
| `/core/inventory/add` | authenticated NZ Alcohol test org | done |
| `/core/inventory/add/manual` | authenticated NZ Alcohol test org | done |
| `/core/inventory/add/csv` | authenticated NZ Alcohol test org | done |
| `/core/inventory/add/barcode` | authenticated NZ Alcohol test org | done |
| `/core/inventory/dispose` | authenticated NZ Alcohol test org | done |
| `/core/executions/live` | authenticated NZ Alcohol test org | done |
| `/core/notifications` | authenticated NZ Alcohol test org | done |
| `/core/record` | authenticated NZ Alcohol test org | done |
| `/core/people` | authenticated NZ Alcohol test org | done |
| `/core/planner` | authenticated NZ Alcohol test org | done |
| `/core/planner/board` | authenticated NZ Alcohol test org | done |
| `/core/settings` | authenticated NZ Alcohol test org | done |
| `/core/integrations` | authenticated NZ Alcohol test org | done |
| `/core/sites` | authenticated NZ Alcohol test org | done |
| `/core/site-transfers` | authenticated NZ Alcohol test org | done |
| `/core/stocktake` | authenticated NZ Alcohol test org | done |
| `/core/suppliers` | authenticated NZ Alcohol test org | done |
| `/core/sourcemap` | authenticated NZ Alcohol test org | done |
| `/core/tasks/configuration` | authenticated NZ Alcohol test org | done |
| `/core/cases` | authenticated NZ Alcohol test org | done |
| `/core/cases/new` | authenticated NZ Alcohol test org | done |
| `/core/contracts` | authenticated NZ Alcohol test org | done |
| `/core/contracts/materials` | authenticated NZ Alcohol test org | done |

## Sales pages

| Route | State | Status |
|---|---|---|
| `/crm` | authenticated NZ Alcohol test org | done |
| `/crm/customers` | authenticated NZ Alcohol test org | done |
| `/crm/tasks` | authenticated NZ Alcohol test org | done |
| `/crm/analytics` | authenticated NZ Alcohol test org | done |
| `/crm/configuration` | authenticated NZ Alcohol test org | done |
| `/crm/matching` | authenticated NZ Alcohol test org | done |
| `/crm/excise` | authenticated NZ Alcohol test org | done |

## Compliance pages

| Route | State | Status |
|---|---|---|
| `/compliant` | authenticated NZ Alcohol test org | done |
| `/compliant/nz-alcohol` | authenticated NZ Alcohol test org | done |
| `/compliant/nz-alcohol/configuration` | authenticated NZ Alcohol test org | done |
| `/compliant/nz-alcohol/customs` | authenticated NZ Alcohol test org | done |
| `/compliant/nz-alcohol/customs/records` | authenticated NZ Alcohol test org | done |
| `/compliant/nz-alcohol/customs/settings` | authenticated NZ Alcohol test org | done |
| `/compliant/nz-alcohol/customs/stock` | authenticated NZ Alcohol test org | done |
| `/compliant/nz-alcohol/customs/transfers` | authenticated NZ Alcohol test org | done |
| `/compliant/nz-alcohol/food-registrations` | authenticated NZ Alcohol test org | done |
| `/compliant/nz-alcohol/food-safety` | authenticated NZ Alcohol test org | done |
| `/compliant/nz-alcohol/food-safety/checks` | authenticated NZ Alcohol test org | done |
| `/compliant/nz-alcohol/licensing` | authenticated NZ Alcohol test org | done |
| `/compliant/nz-alcohol/premises` | authenticated NZ Alcohol test org | done |
| `/compliant/tools` | authenticated NZ Alcohol test org | done |

## Seeded and transient pages

| Route | State | Status |
|---|---|---|
| `/core/inventory/dispose/confirm` | seeded inventory item | done |
| `/core/flows/create/step-name` | seeded workflow | done |
| `/core/flows/create/inputs` | seeded workflow | done |
| `/core/flows/create/outputs` | seeded workflow | done |
| `/core/flows/create/evidence-and-prompts` | seeded workflow | done |
| `/core/flows/create/summary` | seeded workflow | done |
| `/core/flows/create/next-steps` | seeded workflow | done |
| `/core/flows/batches/start` | draft batch and step | done |
| `/core/executions/<execution_id>/steps/<step_id>/record` | completed execution step | done |
| `/core/contracts/<order_id>` | seeded contract order | done |
| `/core/contracts/<order_id>/portal-sharing` | seeded contract order | done |
| `/core/cases/<case_id>` | seeded case | done |
| `/crm/customers/<contact_id>` | seeded customer | done |
| `/compliant/nz-alcohol/customs/records/<control_id>` | valid Customs check | done |
| `/compliant/nz-alcohol/np3-audit/check/<control_id>` | valid NP3 check | done |
| `/core/site-transfers/<transfer_id>/docket` | dispatched transfer | done |
| `/portal` | signed-in portal customer | done |
| `/portal/orders/<order_id>` | published portal order | done |
| `/portal/invite` | valid portal invitation | done |
| `/invite/<token>` | valid staff invitation | done |
| `/crm/xero/select-tenant` | pending multi-tenant OAuth session | done |
| `/auth/google/challenge` | pending Google 2FA session | done |

## Alias and non-page routes

The following GET routes are redirects or service endpoints, so the destination page is indexed instead: `/dashboard`, `/settings`, `/complaint`, `/compliant/nz-alcohol/evidence`, `/compliant/nz-alcohol/np3-audit`, `/core/flows/create`, `/core/flows/create/step/<step>`, `/core/flows/executions/step`, `/core/tasks`, and `/crm/tastings`. `/core/site-transfers/<id>/docket` is HTML and was included above. JSON APIs, downloads, static assets, telemetry, OAuth callbacks, and fragments are not pages.

## Findings and changes

- Replaced unreadably scaled process-diagram labels with a vertical phone story; desktop keeps the existing diagram.
- Fixed CSP-safe Alpine expressions on Sales Analytics and customer invoice pagination, which otherwise caused browser errors when those pages mounted.
- Formatted the case detail UTC deadline for people rather than showing a raw timestamp.
- Styled the transfer docket print button as a touch-sized action.
- No horizontal overflow was found on the remaining page routes at 320, 390, or 768 px. Shared page cards, workspace tabs, bottom navigation, forms, and portal surfaces were visually consistent in screenshots.

## Verification

- `MOBILE_AUDIT_WIDTH=320 MOBILE_AUDIT_SCREENSHOTS=/tmp/mobile-page-audit/screenshots uv run pytest tests/e2e/test_mobile_page_audit.py tests/e2e/test_contract_portal.py` — 69 passed.
- `MOBILE_AUDIT_WIDTH=768 MOBILE_AUDIT_SCREENSHOTS=/tmp/mobile-page-audit/screenshots uv run pytest tests/e2e/test_mobile_page_audit.py` — 67 passed.
- Populated Sales Analytics regression — 26 passed.
- Final 390 px page, portal, and transfer-docket rerun — 73 passed.

## Coverage limits

The route audit proves layout and browser health for each page at the tested widths. It does not prove every possible populated table, permission combination, or long translated string. The existing feature suites cover those flows separately; the populated Sales Analytics, customer profile, contract portal, workflow and stock-transfer paths were specifically checked here.
