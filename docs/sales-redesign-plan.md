# Sales overview: three directions after !515

Sales (`/crm`) answers **how sales are moving, what is outstanding, and which customer follow-ups need work**. This branch starts from main `ba166c7b`, with !515's shared section head already settled. No shared title, tab or sidebar changes are needed.

## What is wrong today

Observed in the seeded screenshots in `~/.cache/workflow-engine-ui-shots/sales-design/00-before`:

- Add widget occupies its own row beneath the tabs; the first screen has figures and a chart but the follow-ups start below it.
- The dark-theme task cards are white with pale text; chart value labels are almost invisible. On a phone, the six chart values crowd each other.
- The operator filter stretches across the whole card, despite its inline maximum width.
- Each task is clickable but cannot be opened with the keyboard.
- The component has both Alpine's automatic `init` and `x-init="init()"`: overview data is requested twice.
- A failed initial request reveals zero-valued figures after loading ends. A failed request is unavailable data, not a quiet sales month.

## What other products do

| Source | Pattern | What it changes here |
|---|---|---|
| [Pipedrive Insights](https://support.pipedrive.com/en/article/insights-feature) | Reports and goals collected in a dashboard; rearrange and resize reports. | Keep custom widgets, saved layout, locking and resizing; Board keeps figures beside the trend without replacing the underlying data. |
| [HubSpot sales reports](https://knowledge.hubspot.com/reports/create-sales-reports-in-the-sales-analytics-suite) | Reporting by date, owner/team and other filters; save reports to a dashboard. | Revenue review gives the trend its own full-width card, then puts product/customer rankings together before the task board. Date-range and Top N controls remain available. |
| [Salesforce Sales Engagement](https://help.salesforce.com/s/articleView?id=sf.hvs_user_intro.htm&language=en_US&type=5) | A prioritized work queue of calls, emails and tasks, with split workspace views. | Sales desk puts the existing task board first below compact figures. No invented priority score, deal pipeline or new task calculation. |
| [Stripe reports](https://support.stripe.com/questions/stripe-reports?locale=en-GB) | Separate financial summaries from product-specific analytics and detail exports. | Figures are concise entry points to existing invoice details. Revenue and receivables remain distinct, with their definitions and calculations unchanged. |
| [Linear My issues](https://linear.app/docs/my-issues), [display options](https://linear.app/docs/display-options) | Curated work views, list/board presentation and display choices. | Sales desk dedicates a single column to customer work before analysis. The same task data and operator filter serve every concept. |
| [Carbon data tables](https://www.carbondesignsystem.com/building-blocks/core/components/data-table/guidelines) | Expandable rows reveal additional detail in a small space. | Keep product-item expansion, task expansion and invoice sheets; make task expansion keyboard-operable. |
| [Production !515](https://gitlab.com/whistlebird/workflow-engine/-/merge_requests/515) | Board chosen, then header actions chosen, then title/tabs/actions settled through four rounds. | Style 1 is closest: paired cards then a full-width work card, shared tokens, standalone section title, underlined tabs and one solid action at the right. |

Not found: comparative usability studies for these precise layouts in small manufacturing businesses, or evidence that one layout increases sales. The structural choices are informed design judgments, not user-tested results. Vendor sources describe capabilities; they do not establish comparative superiority. No imported palette or typography.

## Three directions to choose from

| | Style 1: Board | Style 2: Revenue review | Style 3: Sales desk |
|---|---|---|---|
| Idea | Figures beside trend; full-width task board; paired rankings | Full-width figures and trend; paired rankings before follow-ups | Compact figures; task board first; all cards in one reading column |
| Taken from | Settled Production !515, Pipedrive | HubSpot, Stripe | Salesforce work queue, Linear |
| Best at | A quick balanced check, matching Production | Reviewing revenue and customer/product contribution | Working customer follow-ups on a laptop |
| Gives up | Less room for chart labels | Tasks appear further down | More scrolling for financial analysis |

All three use !515's existing section header. Add widget stays available beside **Open tasks**, the only filled primary action, at the right of the tab row. This is a deliberate product choice: customer follow-ups are the everyday action; layout configuration is secondary. Narrow layouts inherit the shared main-action-first wrap.

The query `?style=1|2|3` selects the initial preview; the chooser changes the layout without reloading and remembers the selection for this browser tab. It is removed when a winner is selected. A user's saved widget order always wins over the concepts' suggested order. Dragging, resizing, adding or removing a widget persists the user's actual layout as before; concepts do not overwrite storage merely by being previewed. Style 1 pairs its locked default trend with figures; unlocking restores normal sizing control. Style 3 presents cards at full reading width while preserving their stored sizes for the other concepts.

## Not in this change

No API, backend permission, revenue calculation, month-on-month calculation, invoice export, task status behavior or custom-widget configuration changes. No other Sales pages are redesigned. Existing API list limits stay in place. The task board still shows up to five tasks per lane and links to all tasks. No pipeline data or forecasts are fabricated. The shared shell's nested `#page-content` issue found in !515 remains a separate change.

The source-to-sale and UX-overhaul roadmaps already mark the earlier Sales styling work complete; this is an additional design review, not a newly delivered roadmap feature.

## Checks

Browser checks cover all concepts at 390, 1024, 1440 and 1920, no sideways scroll, header/title/actions order, board structure and concept persistence. Shared behavior covers one initial load, keyboard task expansion, error/retry/permission states, saved custom layouts and Add widget. Screenshot scenarios exercise operator filtering to nothing and back, invoice details, date range, widget creation and removal, lock/resize, boosted return, quiet data, loading, errors, dark theme and phone/laptop/wall widths. Each screenshot pass is read in full; the final full pass must have no remaining defects.

## Review outcome

Three screenshot rounds completed and every emitted PNG was inspected: 42 in round 1, 55 in round 2, and 60 in the final round (including the corrected edit-scenario assertions rerun). Final defect list is empty for all three concepts. The final set covers busy/quiet desktop, laptop, phone, wall and dark, plus loading, unavailable/retry, invoice details, keyboard task expansion, operator filtering, date-range empty results, custom widget creation/removal, boosted return, resizing/reordering/locking and Top N.

The seed intentionally contains authorised Xero lines awaiting product mapping: Top Products shows 0 mapped products while All authorised sales contains revenue. This is an intentional unmapped state, not missing sales data; the ranking calculations remain unchanged. Full-page phone shots retain the shared fixed bottom navigation at the original viewport boundary.

Validation: 125 shared/browser regression cases passed; the 19 Sales cases passed three consecutive runs. Independent HTML/JS review is clean and test evaluation is valid, with ten deliberately broken cases failing in isolated mutation probes. The user still needs to choose a concept in the draft MR.
