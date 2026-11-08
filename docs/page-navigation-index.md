# Page navigation index

Every page in the app, checked in a browser (Playwright, 1440×900) on a seeded org:

- **Direct**: a full page load, the baseline.
- **In-app ×2**: reached by an htmx-boosted click, twice. The second visit catches run-once flags, redeclared globals and state left over from the first.
- **Back**: the browser's Back button after leaving it.
- **No errors**: no console error that a full load doesn't also raise.
- **Screenshot**: I read the side-by-side screenshot (direct, second in-app visit, after Back) and the three match.
- **Back arrow**: where the yellow arrow in the top bar goes, and whether that is the logical place up.

Each in-app check means matching a direct load: element count within 10%, at least 80% of the text, the same stylesheets and element ids, no "Loading…" left, nothing left on `<body>`'s Alpine data, and the same back arrow. `tests/e2e/test_boosted_navigation.py` checks the same things on every run.

| # | Page | Path | In-app ×2 | Back | No errors | Screenshot | Back arrow goes to | Arrow makes sense |
|---|---|---|---|---|---|---|---|---|
| 1 | Home | `/core/dashboard` | ✅ | ✅ | ✅ | ✅ | hidden (a tab's own page) | ✅ |
| 2 | Go live | `/core/go-live` | ✅ | ✅ | ✅ | ✅ | `/core/dashboard` | ✅ |
| 3 | Production overview | `/core` | ✅ | ✅ | ✅ | ✅ | hidden (a tab's own page) | ✅ |
| 4 | Cases | `/core/cases` | ✅ | ✅ | ✅ | ✅ | `/core` | ✅ |
| 5 | New case | `/core/cases/new` | ✅ | ✅ | ✅ | ✅ | `/core/cases` | ✅ |
| 6 | Tasks | `/core/tasks` | ✅ | ✅ | ✅ | ✅ | hidden (a tab's own page) | ✅ |
| 7 | Production demand | `/core/planner` | ✅ | ✅ | ✅ | ✅ | hidden (a tab's own page) | ✅ |
| 8 | Production board | `/core/planner/board` | ✅ | ✅ | ✅ | ✅ | `/core/planner` | ✅ |
| 9 | Batches | `/core/executions/live` | ✅ | ✅ | ✅ | ✅ | `/core/processes` | ✅ |
| 10 | Product workflows | `/core/processes` | ✅ | ✅ | ✅ | ✅ | hidden (a tab's own page) | ✅ |
| 11 | Workflow editor | `/core/flows` | ✅ | ✅ | ✅ | ✅ | `/core/processes` | ✅ |
| 12 | Create a workflow | `/core/flows/create/start` | ✅ | ✅ | ✅ | ✅ | `/core/processes` | ✅ |
| 13 | Start from a template | `/core/flows/create/template-catalog` | ✅ | ✅ | ✅ | ✅ | `/core/processes` | ✅ |
| 14 | Inventory | `/core/inventory/view` | ✅ | ✅ | ✅ | ✅ | hidden (a tab's own page) | ✅ |
| 15 | Live inventory | `/core/inventory/live` | ✅ | ✅ | ✅ | ✅ | `/core/inventory/view` | ✅ |
| 16 | Add to inventory | `/core/inventory/add` | ✅ | ✅ | ✅ | ✅ | `/core/inventory/view` | ✅ |
| 17 | Add inventory manually | `/core/inventory/add/manual` | ✅ | ✅ | ✅ | ✅ | `/core/inventory/add` | ✅ |
| 18 | Add inventory by barcode | `/core/inventory/add/barcode` | ✅ | ✅ | ✅ | ✅ | `/core/inventory/add` | ✅ |
| 19 | Add inventory from a file | `/core/inventory/add/csv` | ✅ | ✅ | ✅ | ✅ | `/core/inventory/add` | ✅ |
| 20 | Record disposal | `/core/inventory/dispose` | ✅ | ✅ | ✅ | ✅ | `/core/inventory/view` | ✅ |
| 21 | Stocktake | `/core/stocktake` | ✅ | ✅ | ✅ | ✅ | `/core/inventory/view` | ✅ |
| 22 | Trace and recall | `/core/sourcemap` | ✅ | ✅ | ✅ | ✅ | `/core/inventory/view` | ✅ |
| 23 | Stock transfers | `/core/site-transfers` | ✅ | ✅ | ✅ | ✅ | `/core/inventory/view` | ✅ |
| 24 | Contract orders | `/core/contracts` | ✅ | ✅ | ✅ | ✅ | `/core/planner` | ✅ |
| 25 | Customer materials | `/core/contracts/materials` | ✅ | ✅ | ✅ | ✅ | `/core/contracts` | ✅ |
| 26 | Suppliers | `/core/suppliers` | ✅ | ✅ | ✅ | ✅ | `/core/inventory/view` | ✅ |
| 27 | Compliance | `/compliant` | ✅ | ✅ | ✅ | ✅ | hidden (a tab's own page) | ✅ |
| 28 | NZ alcohol | `/compliant/nz-alcohol` | ✅ | ✅ | ✅ | ✅ | hidden (a tab's own page) | ✅ |
| 29 | NP3 food safety | `/compliant/nz-alcohol/np3-audit` | ✅ | ✅ | ✅ | ✅ | hidden (a tab's own page) | ✅ old link; redirects to the Food safety tab |
| 30 | NP3 food safety | `/compliant/nz-alcohol/food-safety` | ✅ | ✅ | ✅ | ✅ | hidden (a tab's own page) | ✅ |
| 31 | Checks | `/compliant/nz-alcohol/food-safety/checks` | ✅ | ✅ | ✅ | ✅ | `/compliant/nz-alcohol/food-safety` | ✅ |
| 32 | Customs | `/compliant/nz-alcohol/customs` | ✅ | ✅ | ✅ | ✅ | hidden (a tab's own page) | ✅ |
| 33 | Customs stock | `/compliant/nz-alcohol/customs/stock` | ✅ | ✅ | ✅ | ✅ | `/compliant/nz-alcohol/customs` | ✅ |
| 34 | Records for Customs | `/compliant/nz-alcohol/customs/records` | ✅ | ✅ | ✅ | ✅ | `/compliant/nz-alcohol/customs` | ✅ |
| 35 | Customs settings | `/compliant/nz-alcohol/customs/settings` | ✅ | ✅ | ✅ | ✅ | `/compliant/nz-alcohol/customs` | ✅ |
| 36 | Customs | `/compliant/nz-alcohol/evidence` | ✅ | ✅ | ✅ | ✅ | `/compliant/nz-alcohol/customs` | ✅ |
| 37 | Licensing | `/compliant/nz-alcohol/licensing` | ✅ | ✅ | ✅ | ✅ | hidden (a tab's own page) | ✅ a tab's own page (tab hidden until a licence is set) |
| 38 | Premises | `/compliant/nz-alcohol/premises` | ✅ | ✅ | ✅ | ✅ | `/compliant` | ✅ |
| 39 | Food registrations | `/compliant/nz-alcohol/food-registrations` | ✅ | ✅ | ✅ | ✅ | `/compliant/nz-alcohol/food-safety` | ✅ |
| 40 | Tools | `/compliant/tools` | ✅ | ✅ | ✅ | ✅ | `/compliant` | ✅ |
| 41 | Compliance settings | `/compliant/nz-alcohol/configuration` | ✅ | ✅ | ✅ | ✅ | `/compliant` | ✅ |
| 42 | Sales overview | `/crm` | ✅ | ✅ | ✅ | ✅ | hidden (a tab's own page) | ✅ |
| 43 | Customers | `/crm/customers` | ✅ | ✅ | ✅ | ✅ | hidden (a tab's own page) | ✅ |
| 44 | Sales tasks | `/crm/tasks` | ✅ | ✅ | ✅ | ✅ | hidden (a tab's own page) | ✅ |
| 45 | Batch matching | `/crm/matching` | ✅ | ✅ | ✅ | ✅ | `/crm/analytics` | ✅ |
| 46 | Analytics | `/crm/analytics` | ✅ | ✅ | ✅ | ✅ | hidden (a tab's own page) | ✅ |
| 47 | Excise | `/crm/excise` | ✅ | ✅ | ✅ | ✅ | `/crm` | ✅ reached from the Sales overview, so up is Sales |
| 48 | My account | `/core/settings` | ✅ | ✅ | ✅ | ✅ | hidden (a tab's own page) | ✅ |
| 49 | People and roles | `/core/people` | ✅ | ✅ | ✅ | ✅ | `/core/settings` | ✅ lit Production in the sidebar on main; fixed in !562 |
| 50 | Sites | `/core/sites` | ✅ | ✅ | ✅ | ✅ | `/core/settings` | ✅ lit Production in the sidebar on main; fixed in !562 |
| 51 | Integrations | `/core/integrations` | ✅ | ✅ | ✅ | ✅ | `/crm` | ✅ redirects to Sales settings on main; !562 makes it Settings › Integrations, arrow → Settings |
| 52 | Sales settings | `/crm/configuration` | ✅ | ✅ | ✅ | ✅ | `/crm` | ✅ |
| 53 | Notifications | `/core/notifications` | ✅ | ✅ | ✅ | ✅ | `/core/settings` | ✅ lit Production in the sidebar on main; fixed in !562 |
| 54 | Task settings | `/core/tasks/configuration` | ✅ | ✅ | ✅ | ✅ | `/core/settings` | ✅ lit Production in the sidebar on main; fixed in !562 |
| 55 | Records for Customs: a check | `/compliant/nz-alcohol/customs/records/product-mapping` | ✅ | ✅ | ✅ | ✅ | `/compliant/nz-alcohol/customs/records` | ✅ |
| 56 | NP3: a check | `/compliant/nz-alcohol/np3-audit/check/recall-policy` | ✅ | ✅ | ✅ | ✅ | `/compliant/nz-alcohol/food-safety` | ✅ |
| 57 | New workflow | `/core/flows/create` | ✅ | ✅ | ✅ | ✅ | `/core` → lands `/core/dashboard` | ✅ wizard: arrow goes back through history to keep the draft; fallback now Workflows |
| 58 | Add inventory manually | `/core/inventory/add/manual` | ✅ | ✅ | ✅ | ✅ | `/core/inventory/add` | ✅ |
| 59 | Record disposal | `/core/inventory/dispose` | ✅ | ✅ | ✅ | ✅ | `/core/inventory/view` | ✅ |
| 60 | A case | `/core/cases/<id>` | ✅ | ✅ | ✅ | ✅ | `/core/cases` | ✅ |
| 61 | A customer | `/crm/customers/<id>` | ✅ | ✅ | ✅ | ✅ | `/crm/customers` | ✅ |
| 62 | A contract order | `/core/contracts/<id>` | ✅ | ✅ | ✅ | ✅ | `/core/contracts` | ✅ |
| 63 | Portal sharing | `/core/contracts/<id>/portal-sharing` | ✅ | ✅ | ✅ | ✅ | `/core/contracts/<id>` | ✅ |
| 64 | Record a batch step | `/core/executions/<id>/steps/<id>/record` | ✅ | ✅ | ✅ | ✅ | `/core/executions/live` | ✅ was Production overview; now its batch list |
| 65 | Batch step screen | `/core/flows/batches/start?execution_id=<id>&id=<id>` | ✅ | ✅ | ✅ | ✅ | `/core/flows?id=<id>` | ✅ |
| 66 | A workflow | `/core/flows?id=<id>` | ✅ | ✅ | ✅ | ✅ | `/core/processes` | ✅ |

**66 of 66 pages pass every automatic check.**
