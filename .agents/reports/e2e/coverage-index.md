# E2E coverage index — page & flow status

Living status of what the Playwright suite actually exercises, page by page and flow by
flow. Updated as coverage is built. Legend:

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
| Inventory add CSV | `/core/inventory/add/csv` | 🔵 render |
| Inventory add barcode | `/core/inventory/add/barcode` | 🔵 render |
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
| CSV upload | 🔵 render only (page loads; upload flow deferred — file-drop UI) |
| Barcode add | 🔵 render only |
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
| Customer / invoice CRUD | 🔵 deferred — customers are Xero-sourced; needs a stubbed tenant |
| **Cross-cutting** | | |
| Security headers, cookie flags, CSRF rejection | ✅ | test_security_headers |
| 21 authenticated pages render clean | ✅ | test_pages_render |

## Known deferred (with reason, not faked)

- **CSV / barcode inventory add** — file-drop and hardware-scanner UIs; the add path is
  covered via manual. Worth a follow-up with a fixture CSV.
- **CRM customer / invoice CRUD** — customers are sourced from Xero sync, not a create
  endpoint; needs a stubbed Xero at the HTTP layer (a test must never touch a real
  tenant). Tracked in the spec.
- **Full process-wizard click-through** — the wizard is many SPA fragments. Creation is
  driven through the real browser session's API (exercising auth, CSRF, org-scope, and
  the business logic) and verified in the UI; clicking every fragment is a higher-
  maintenance follow-up with lower marginal value.
