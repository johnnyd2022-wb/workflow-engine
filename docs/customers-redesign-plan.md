# Customers redesign — 18 October 2026

## Selected design — 19 October 2026

The founder selected **Style 1: Directory**. It is now the only implementation: full-width customer rows and an accessible preview drawer at every width. The temporary chooser, URL/session style selection, Desk and Contact book markup, grouped render helper, losing CSS and concept-only tests are removed. Old preview URLs and saved choices have no effect.

Desk was not selected; its persistent split and closed/reopened layout states are retired. Contact book was not selected; its readiness card groups are retired. Their original trade-offs and research remain below as the design history. Search, filters, sorting, pagination, full-record links, contact preview, customer creation and Xero flows remain.

The responsive matrix now tests the chosen directory at 390, 1024, 1440 and 1920 pixels, including ignored old choices, contact access, the drawer, overlap/overflow and dark contrast. Desk-only tests are deleted with the structure they protected; the original four behavior tests and one real boosted-return/filter regression remain.


## Purpose and scope

Find the right customer and reach them, with trustworthy contact details. This pass covers `/crm/customers`; customer records, invoice calculations, Xero integration contracts and permissions stay in their existing flows.

The source audit checked remote main `d1890a70` and all open MRs. Only Suppliers !537 and Batches !533 were open. Home, Production, Inventory, Trace, Compliance, Sales overview, Settings, Workflows, the editor, Planner, production board, Contracts and Stocktake already have merged design work. Customers is the next primary destination without a page-design plan. Sales tasks, Batch matching and customer detail remain candidates for separate passes; this MR does not expand into them.

## What is wrong today

Observed in `customers-design/00-before` (all nine PNGs inspected):

- The disconnected state repeats Connect Xero in the action header and a large banner; the filtered-empty state offers it again although connection cannot clear a search.
- Search, a full-width status select and a small missing-details button occupy three rows on a desktop. At phone width these controls and the connection banner push the first customer near the bottom of the screen.
- Six table columns show status and sync metadata alongside contact details. On the phone only names fit; phone/email require sideways table movement.
- In dark mode the table header remains a light strip with pale text.
- The source binds navigation to a table row's click without a link or keyboard target. Customer names should be real links. This is an accessibility repair in the same page scope.

The baseline uses the same fictional 24-contact directory as the concepts, including missing contacts, archived records, local-only records and a failed send. The Home and Suppliers sibling screenshots establish the existing shell, cards, spacing and accent.

## What other products do

Primary sources read on 18 October 2026. These are structural patterns, not palette or typeface references.

| Kind / source | Pattern observed | What it changes here |
|---|---|---|
| Comparable: [Pipedrive list view](https://support.pipedrive.com/en/article/list-view) | Linear contact directory with focused filters; basic contact information in a hovercard | Directory makes scanning names and reaching contact details the main job; sync metadata moves to preview. Use an explicit accessible preview instead of hover-only disclosure. |
| Comparable: [HubSpot record preview](https://knowledge.hubspot.com/records/preview-a-record) | Inspect a record without leaving the index | Desk puts directory and selected contact beside one another on a wide screen; all styles retain Open customer for full activity. |
| Comparable: [Attio views](https://attio.com/help/reference/managing-your-data/views) | Table and kanban views give different ways to organize the same records | Contact book groups contacts by data completeness; it does not invent deal stages or drag-and-drop transitions. |
| Craft reference: [Linear board layout](https://linear.app/docs/board-layout) | Groups change scanning structure while filters and ordering keep their meaning | Contact book shows separate missing-details and ready-to-reach sections with counts explicitly limited to this result page. |
| Craft reference: [Notion views, filters and groups](https://www.notion.com/help/views-filters-and-sorts) | Different views of one database share underlying records; layout can change without changing data | One customer component, API query and form serve all three concepts. View selection never alters the dataset. |
| Pattern: [Carbon data table](https://www.carbondesignsystem.com/building-blocks/core/components/data-table/guidelines) | Toolbar groups search and filters; supplementary information belongs in expansion or a panel; pagination stays below results | One compact toolbar, explicit actions, four meaningful columns, contact preview, unchanged server pagination. |

The comparable sources do not establish that readiness grouping is the right model for this business. That grouping is an explicit design hypothesis to compare, based on existing phone/email fields. No new CRM scoring, global completeness total or sales pipeline is inferred.

## Three directions considered

| | Style 1: Directory | Style 2: Desk | Style 3: Contact book |
|---|---|---|---|
| Idea | Full-width rows: name, contact, last contact | A compact directory beside a persistent contact preview | Spacious cards grouped by missing / complete contact details |
| Taken from | Pipedrive, Carbon | HubSpot preview, Pipedrive basic-contact disclosure | Attio alternative views, Linear grouping, Notion |
| Best at | Finding and comparing customers quickly | Calling through a directory without losing your place | Seeing contact-data gaps and reading one business at a time |
| Gives up | Preview requires a click | Less row information while the panel is visible | Fewer customers fit on the first screen |

All three keep search, status, missing details, name and sync ordering, pagination, source/failure badges, new customer, existing full-record links and permission-aware Xero actions. One quiet connection row replaces repeated banners. A contact preview exposes email/phone, activity source and sync metadata; it becomes a drawer on smaller screens. Contact book groups only the loaded result page and says so. No whole-directory metric is computed from a partial page.

## Not in this change

No backend API, invoice, stock allocation, revenue, Xero synchronization policy, detail-page layout, role or subscription changes. No new integrations or external calls. Existing create/customer-edit/Xero warning behavior from !527/!538/!539 must remain covered. Shared globally loaded CRM assets are a separate UX-overhaul item; this change adds its own stylesheet and script inside the swapped content.

## Checks

Before and three complete screenshot passes: each style at 390, 1024, 1440 and 1920 pixels; dark, preview, create/save, filtered result and no matches, archived and missing filters, quiet and empty directory, intentional error/retry, boosted round trip. Additional loading and long-contact states are included after the first review. Every PNG is inspected; expected negative-state error logging is separated from clean runs.

New browser coverage must check filters/order/pagination, accessible links and preview focus, error versus empty, old navigation and the three structures at all widths. Preserve the existing contact-sync UI and API tests; run shared layout/render/boosted suites, Ruff, node syntax and Semgrep. Independent test and template/script reviews gate publication.

Direction: **Style 1 selected by the founder**. The comparison history below is retained; production code contains only Directory.

## Screenshot review log

- `00-before`: nine baseline/sibling images, all inspected.
- `01`: 30 images inspected. Phone header/temporary chooser consumed too much of the first screen; Desk was not yet split at laptop width. The status selector's accessible name included option text, which stopped the interaction scenario. Fixed the header/chooser spacing, the 900px Desk breakpoint and the explicit control label.
- `02`: all 63 images captured without scenario or console failures and inspected. This was **not** a clean design pass: independent review found closing Desk left its column empty, and resizing its open preview to phone needed focus transfer. Inspection also found a URL-selected design was not remembered on an in-app round trip. The phone header still wrapped the action below its title; tightened its layout. Added loading/long-contact states rather than shrinking the scenarios.
- These Desk close/resize defects have regression evidence: all three new cases failed before the fixes. The URL choice now persists; all three designs are checked by leaving via Analytics, returning and searching a real server-backed directory. The test waits for the boosted page's initial network work before typing; a provisional earlier failure from typing before initialization was a test-readiness issue, not a proven shared-runtime bug.
- Alpine calls its component `init()` automatically; removed the duplicate explicit `x-init` invocation. Shared initialization code and the customer detail page are unchanged.
- `03`: 68 images captured, all seven scenarios passed with no console errors, all images inspected. Directory/Desk/Contact book at all four widths, dark, filters, no matches, quiet/empty, loading, error/retry, preview, long contacts, create/save, boosted return and Desk close/reopen/resize now produce an empty defect list. The private screenshot organisation was purged afterwards. At exploration submission all three remained in the draft MR awaiting the founder's choice; Directory was subsequently selected as recorded above.
- `04` (supplemental, unchanged final code): 12 further images cover a quiet directory at laptop, phone and dark, plus empty phone, for every style. All scenarios and console checks passed; all 12 images inspected with no further defects. Recreated only the private synthetic fixture, then purged it again. These extend coverage without claiming a fourth implementation iteration.

Exploration verification: 59 page/contact cases and 272 shared layout/render/boosted/CRM/navigation cases passed. Independent test grade valid and HTML/JS/CSS review clean. App Semgrep auto: 214 rules, zero findings. The screenshot helper's separate 290-rule scan reported two unchanged trusted-CLI patterns (dynamic model imports and its existing fixed-host GitLab upload); baseline-aware comparison against origin/main reports zero new findings. No scanner rule or assertion was weakened.


## Selected Directory finalization

After the founder selected Style 1, removed the chooser and both rejected layouts, their helpers/selectors, style URL/session state and wide-screen Desk region/resize handling. Preview is consistently a modal drawer. Kept original customer form, server queries/pagination, links, contact access, permissions and Xero contracts.

Final evidence: `customers-style1-final/01`, 37 PNGs covering busy/quiet all four widths in both themes, drawer desktop/phone, long contacts, archived/missing/search/no matches, loading/empty/error/retry, create/save and boosted round trip. All seven scenarios and console checks passed; every PNG inspected, empty defect list, synthetic fixture purged. All images uploaded into the final MR description.

Tests now retain four unchanged behavior cases, four Directory width/drawer/overlap/dark cases (also proving old preview URLs/stored choices are ignored), and one real boosted return/filter case. Retired Desk-only region/resize cases with that implementation. Independent mutation found document-only overflow could miss the SPA scroll container; retained it and added the actual main-scroll-width assertion. Verified red 7.25s / restored green 8.19s. Independent final test grade valid; HTML/JS/CSS clean. Final results and the explicitly reported combined-invocation fixture-discovery error are in the page-design report.
