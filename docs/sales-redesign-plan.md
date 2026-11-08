# Sales overview: selected Board after !515

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

## Direction review and selection

| | Style 1: Board (selected) | Style 2: Revenue review | Style 3: Sales desk |
|---|---|---|---|
| Idea | Figures beside trend; full-width task board; paired rankings | Full-width figures and trend; paired rankings before follow-ups | Compact figures; task board first; all cards in one reading column |
| Taken from | Settled Production !515, Pipedrive | HubSpot, Stripe | Salesforce work queue, Linear |
| Best at | A quick balanced check, matching Production | Reviewing revenue and customer/product contribution | Working customer follow-ups on a laptop |
| Gives up | Less room for chart labels | Tasks appear further down | More scrolling for financial analysis |

Style 1 was selected because its paired summary and trend follow the same board rhythm as
Production while leaving the task board full-width. The final adjustment makes the locked
Sales Trend exactly the same height as At a glance, in both busy and quiet states. Unlocking
the trend restores the existing full-width editing behavior. Revenue review placed follow-up
work too far down the page, while Sales desk made financial analysis require more scrolling.

The selected Board uses !515's existing section header. Add widget stays available beside
**Open tasks**, the only filled primary action, at the right of the tab row. Narrow layouts
inherit the shared main-action-first wrap. A user's saved widget order, size and lock state
still win; dragging, resizing, adding and removing widgets persist as before. The preview
chooser, query/session selection and both losing layout structures were removed.

## Not in this change

No API, backend permission, revenue calculation, month-on-month calculation, invoice export, task status behavior or custom-widget configuration changes. No other Sales pages are redesigned. Existing API list limits stay in place. The task board still shows up to five tasks per lane and links to all tasks. No pipeline data or forecasts are fabricated. The shared shell's nested `#page-content` issue found in !515 remains a separate change.

The source-to-sale and UX-overhaul roadmaps already mark the earlier Sales styling work complete; this is an additional design review, not a newly delivered roadmap feature.

## Checks

Browser checks cover the selected Board at 390, 1024, 1440 and 1920, no sideways scroll,
header/title/actions order and board structure. An exact bounding-box regression covers the
paired card height in busy/quiet and light/dark states, then unlocks the trend and verifies
the editable full-width layout. Shared behavior covers one initial load, keyboard task
expansion, error/retry/permission states, saved custom layouts and Add widget. Screenshot
scenarios exercise operator filtering to nothing and back, invoice details, date range,
widget creation and removal, lock/resize, boosted return, quiet data, loading, errors, dark
theme and phone/laptop/wall widths. Each screenshot pass is read in full.

## Review outcome

Three concept screenshot rounds completed and every emitted PNG was inspected: 42 in round
1, 55 in round 2, and 60 in round 3. After selection, a 20-image winner-only pass was also
inspected in full. Its defect list is empty. The final set covers busy/quiet desktop, laptop,
phone, wall and dark, plus loading, unavailable/retry, invoice details, keyboard task
expansion, operator filtering, date-range empty results, custom widget creation/removal,
boosted return, resizing/reordering/locking and Top N.

The seed intentionally contains authorised Xero lines awaiting product mapping: Top Products shows 0 mapped products while All authorised sales contains revenue. This is an intentional unmapped state, not missing sales data; the ranking calculations remain unchanged. Full-page phone shots retain the shared fixed bottom navigation at the original viewport boundary.

Validation before selection: 125 shared/browser regression cases passed; the 19 concept
cases passed three consecutive runs. Independent HTML/JS review was clean and test
evaluation valid, with ten deliberately broken cases failing in isolated mutation probes.
Winner-only validation and final CI are recorded in the MR and page-design report.

## Review round: figures band, trend beside follow-ups

Review against the page-design bar found the shipped board still put the Task Board below the
first screen while naming follow-ups the everyday action, repeated one destination three times
("Open tasks", the Tasks tab, "View all tasks"), and left the empty states without a next step.

- **Board.** The three figures run across the top as one band. The locked Sales Trend (5 of 12
  columns) then shares a row with the locked Task Board (7 of 12) at equal height, so figures,
  trend and follow-ups are all on the first screen at 1440x900. Rankings stay paired below.
  The pair needs trend then task board as the first two widgets; any other saved order falls
  back to each widget's own size. The switch is a container query at 1100px of content.
- **Primary action.** "New task" opens the Tasks page with the new-task form ready
  (`/crm/tasks?new=1`). The Tasks tab and "View all tasks" remain the ways to the list.
- **Status in words.** Due dates read "2 days overdue", "Due today", "Due in 3 days".
- **Cut from the first read.** The task board caption, the "Showing N of N" line when nothing is
  held back, and the "No description" placeholder. All data stays reachable.
- **Empty states.** No open follow-ups shows one line and a "New task" button instead of two
  empty lanes; a board filtered to nothing keeps its lanes and filter. The trend says whether
  there are no sales yet or none in the chosen range.

These are design judgements from the review, not new research findings. No API, calculation,
export or permission changed; `?new=1` is read only by the Tasks page script.
