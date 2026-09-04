# Core UX and performance review — 4 September 2026

## Scope and method

This review used the rebuilt `whistlebird_test` tenant, rather than empty demo data.
The tenant contains 12 imported product workflows, 138 historical production executions,
948 production links, 67 receipt records, 13 customs records, and 38 stage-two records.
The reviewer signed in through the production-shaped TLS test deployment and inspected the
Dashboard, Core hub, workflow directory, inventory and active-batch surfaces at desktop
(1440 × 1000) and mobile (390 × 844) widths. Screenshots were captured during the review.

The Core first-paint request contract and lazy detail tabs were also inspected in source
and exercised in Playwright. The initial Core view requests the compact
`/api/core/hub/overview` payload; inventory and execution-history data are deferred until
their tabs are opened. This is the appropriate information architecture for a tenant with
real historical data and is retained.

## Findings

| Priority | Finding | Evidence | Decision |
| --- | --- | --- | --- |
| High | The workflow directory is difficult to operate once an organisation has imported or created many workflows. It presents a flat, unfiltered list with legacy names and no result count. | The rebuilt tenant populated the list with 12 imported workflows; the list has no search or filtering affordance. | Add local, instant workflow search, an accurate visible-result count, and empty-search guidance. Keep individual workflow detail on its existing dedicated route. |
| High | Each workflow row contains a `button` inside an enclosing link. Nested interactive elements are invalid HTML and make pointer and keyboard behaviour browser-dependent. | `processes/list.html` renders `a.processes-list-item > button.processes-list-item__history-btn`. | Make the workflow link and History button independent sibling controls, preserving the full-row workflow action and the existing history drawer. |
| Medium | The same object is named “Products” in the directory and “Product workflows” in Core. That makes a repeatable manufacturing process sound like an inventory SKU. | `/core/processes` has title `Products`; Core’s tab and live-batch surfaces say “Product workflows.” | Standardise the directory on **Product workflows** and explain that it is where teams define, start, and review production runs. |
| Medium | Selecting a Core tab changes the query string with `replaceState`, so the browser Back/Forward controls cannot replay a user’s tab navigation. | `setCore2MainTab()` always calls `history.replaceState`. | Push a history entry for a user tab selection, retain replacement for initialisation, and restore the selected tab on `popstate`. |
| Reviewed, no change | The Dashboard is information-dense on mobile: six KPI cards can push the action list down the page, especially where CRM metrics are unavailable. | Mobile review with the real tenant; its dashboard showed 2,727 operator actions and 47 expired-stock findings. | Do not hide metrics based on an inferred business priority in this pass. A future dashboard change should be driven by named operating roles and metric configuration, not a cosmetic collapse that might suppress an important signal. |
| Reviewed, no change | The Core hub has Overview, Inventory and Product-workflows tabs plus dedicated live-inventory and active-batch screens. | Template, request-waterfall tests, and browser review. | Keep this split. Moving the directory or live operational work behind another layer would add navigation without reducing load or cognitive cost. |
| Observability follow-up | Rebuilding the tenant emitted many `tenant_filter.no_context` warnings despite a verified successful import. | Standalone migration session loads the application's tenant-filter listener without request tenant context. | Record as a migration observability issue; do not suppress tenant isolation warnings in a UX change. Address it separately with an explicit scoped migration-session design and regression coverage. |

## Acceptance criteria for this change

1. A user can filter the workflow directory by workflow name and see the visible result
   count without another API call.
2. Workflow navigation and History are separate, keyboard-reachable controls; no button is
   nested in a link.
3. The directory vocabulary consistently says “Product workflows”.
4. Core tab clicks are represented in browser history, and Back/Forward restore the
   matching panel without issuing an unnecessary data request.
5. The existing Core load-waterfall contract remains intact.

## Verification plan

- Add a browser regression covering filtering, independent History opening, and workflow
  navigation.
- Add a browser regression covering Core tab Back/Forward state.
- Run the focused Playwright suite, lint/format checks, the relevant Python unit tests,
  and the repository security scan before review.
