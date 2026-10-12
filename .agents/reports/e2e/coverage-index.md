# E2E coverage index — page & flow status

Living status of what the Playwright suite actually exercises, page by page and flow by
flow. This markdown is the human-readable view; the **deterministic source of truth** is
`scripts/e2e_coverage.py` (`--json` for machine output, `--check` to gate on gaps), which
matches the real `app.url_map` against the route literals in `tests/e2e/*.py`. Run it
before writing tests rather than re-deriving this by hand. Legend:

- ✅ **flow** — a real action is driven and its outcome asserted (create/edit/delete/run)
- 🟡 **partial** — some actions covered, others not
- 🔵 **render** — page loads and is checked clean (no JS/console/render errors), but its
  in-page actions are not exercised
- ❌ **none**

## Pages

| Page | Route | Status |
|---|---|---|
| Landing / login / signup | `/` | ✅ flow |
| Dashboard | `/core/dashboard` | 🔵 render |
| Processes list | `/core/processes` | ✅ flow (see Workflows) |
| Flows workspace | `/core/flows` | 🔵 render |
| Process create wizard | `/core/flows/create` | ✅ flow (create via session API + UI verify) |
| Executions live | `/core/executions/live` | 🔵 render |
| Inventory view | `/core/inventory/view` | 🟡 partial |
| Inventory add (hub) | `/core/inventory/add` | 🔵 render |
| Inventory add manual | `/core/inventory/add/manual` | ✅ flow (create + unhappy) |
| Inventory add CSV | `/core/inventory/add/csv` | ✅ flow (file input, Browse chooser and drop → review → add, and skip) |
| Inventory add barcode | `/core/inventory/add/barcode` | 🟡 partial (typed code → lookup → add, Enter → form; camera scan not driven) |
| Inventory dispose | `/core/inventory/dispose` | 🟡 partial (dispose flow via session API) |
| Notifications | `/core/notifications` | 🔵 render |
| Settings | `/core/settings` | ✅ flow (change + persist) |
| Integrations | `/core/integrations` | 🔵 render |
| CRM home / customers / tasks / analytics / config | `/crm/*` | 🟡 partial |

## Flows / CRUD

| Flow | Status | Test |
|---|---|---|
| **Auth** | | |
| Signup → org + user created → signed in | ✅ | test_auth_flows |
| Login happy / wrong password (no session) | ✅ | test_auth_flows, test_smoke |
| Logout ends session | ✅ | test_auth_flows |
| 2FA enroll → enable → verify → disable | ✅ | test_auth_flows |
| Change password (old invalidated) | ✅ | test_auth_flows |
| **Workflows / Processes (the spine)** | | |
| Create process | ✅ | test_workflow_flow |
| Read / list shows created process | ✅ | test_workflow_flow |
| Update process (rename) | ✅ | test_workflow_flow |
| Add steps to a process | ✅ | test_workflow_flow |
| Delete process | ✅ | test_workflow_flow |
| Run execution → complete a step | ✅ | test_workflow_flow |
| Unhappy: create with no name | ✅ | test_workflow_flow |
| Cross-tenant: org B cannot touch org A's process/execution | ✅ | test_tenant_isolation |
| **Inventory** | | |
| Manual add (create) + zero-qty unhappy | ✅ | test_inventory_flow |
| Edit an item | ✅ | test_inventory_flow |
| Delete an item | ✅ | test_inventory_flow |
| Adjust quantity (with reason) | ✅ | test_inventory_flow |
| Dispose / wastage | ✅ | test_inventory_flow |
| CSV upload (validate → commit, API) | ✅ | test_inventory_csv_flow |
| CSV upload through the page (file input → review card → add / skip) | ✅ | test_inventory_csv_flow |
| Barcode add: typed code → lookup → add | ✅ | test_inventory_flow |
| Barcode scanner-style Enter → capture → form (stops before the add) | ✅ | test_inventory_flow |
| Barcode camera scan | 🔵 not driven (see Known deferred) |
| Cross-tenant read/update/delete/list/aggregate | ✅ | test_tenant_isolation |
| **Settings** | | |
| Change a setting and verify it persists | ✅ | test_settings_flow |
| Session timeout update | ✅ | test_settings_flow |
| **Org / users** | | |
| Add a user to the org | ✅ | test_org_users_flow |
| Remove a user | ✅ | test_org_users_flow |
| Non-member refused | ✅ | test_org_users_flow |
| **CRM / Xero** | | |
| Pages render clean | ✅ | test_pages_render |
| Xero auth redirect well-formed (state/CSRF) | ✅ | test_crm_flow |
| Customers API auth-gated + org-scoped | ✅ | test_crm_flow |
| Customer / invoice CRUD | 🟡 unit-covered (`tests/test_crm.py::TestCRMInvoiceCreation`); no e2e browser flow yet |
| **Cross-cutting** | | |
| Security headers, cookie flags, CSRF rejection | ✅ | test_security_headers |
| 21 authenticated pages render clean | ✅ | test_pages_render |

## Known deferred (with reason, not faked)

- **Barcode camera scan** — the typed and Enter paths are driven; the camera path is not.
  A headless Chromium can be given a fake camera (`--use-fake-device-for-media-stream`), so
  the camera itself is not what blocks this. Decoding is: it needs the browser's native
  `BarcodeDetector`, which Linux Chromium does not have, or the ZXing fallback, which
  `app/core/frontend/js/inventory-barcode-spa.js:647` imports from `cdn.jsdelivr.net`. The
  CSP `script-src` (`app/api/app_factory.py:515`) allows `unpkg.com` and Cloudflare Insights
  but not jsdelivr, so on a browser without `BarcodeDetector` that import looks blocked and a
  scan could never decode (read from the code on 2026-10-13, not reproduced in a browser).
  A test needs a stubbed `BarcodeDetector`; whether the fallback should be vendored or the CSP
  widened is a product and security call.
- **CRM customer / invoice CRUD (e2e)** — customers are sourced from Xero sync, not a
  create endpoint, so the only write path is invoice creation. Now covered at the
  unit/service level (`tests/test_crm.py::TestCRMInvoiceCreation`, stubbing
  `XeroAPIClient.create_invoice` — never touches a real tenant), including the
  cross-tenant case. A browser-driven e2e flow through `test_crm_flow.py` remains
  deferred; this row tracks that narrower gap now.
- **Full process-wizard click-through** — the wizard is many SPA fragments. Creation is
  driven through the real browser session's API (exercising auth, CSRF, org-scope, and
  the business logic) and verified in the UI; clicking every fragment is a higher-
  maintenance follow-up with lower marginal value. wont-fix, already resolved by a
  deliberate scope decision, not an oversight (reviewed 2026-08-25 by findings-sweep) —
  re-litigating it is outside findings-sweep's remit; a human can promote it if
  priorities change.
