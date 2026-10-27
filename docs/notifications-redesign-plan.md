# Notifications: redesign plan

**What the page is for, in one sentence:** *what needs me, starting with what's late, and one click to fix each.*

## What is wrong today (00-before screenshots, a busy org with 50+ notifications)

- **Late work is at the bottom.** Cards sort by date, newest first, so a renewal due in December sits above an NP3 review that is overdue by months.
- **Every action is behind a button.** Each card ends in a blue "Actions" link that opens a menu, usually with one item in it. Two clicks to reach the only thing you can do.
- **"Dispose of inventory item" does nothing.** Its function only exists on the Production overview and the workflow pages. On a full load of Notifications the click is silently dropped (a bug, fixed here).
- **Actions land too far from the work:**
  - Stock checks go to the generic Production overview, not the lot.
  - Licensing items go to the top of Licensing, not the licence or certificate.
  - Tasks go to an old `/core?tab=tasks` address.
  - Output expiry and ready-date items open the workflow editor, not the stock line.
- **Backend showing through:**
  - A stock lot with no batch number is named by the first 8 characters of its database id.
  - A sale with no invoice number is named by the Xero id.
  - Licensing descriptions show ISO dates ("Review due 2026-11-21") and a title cut mid-word at 90 characters.
- **No hierarchy.** Fifty identical cards with the same weight, labels in capitals ("REVIEW DUE:"), the date twice, and 25 per page.
- **Doesn't match its siblings.** Centred title, a pill toggle in browser-blue, plain blue links; Suppliers and the other pages use left-aligned headers, `workspace-card`, the house buttons and the accent colour.

## Every notification, and the action that resolves it

| Source | Example | Action today | Action now (primary first) |
|---|---|---|---|
| Expired raw material with stock | "Juniper berries · lot JB-3188 has expired" | Actions → Dispose (broken), Review in Sourcemap | **Dispose** (Record disposal with that lot, all of it and the reason "Expired" filled in: one more press) · Open the lot · Trace where it went |
| Stock needs checking (stock integrity) | "Juniper berries · lot JB-3188" | Actions → Review stock (Production overview) | **Check the lot** (Inventory with that lot open) |
| Sale needs a batch | "Sale INV-0042 needs a batch match" | Actions → Review sale | **Match the sale** (Batch matching) |
| Output expiry | "Gin distillate expires 12 Dec" | Actions → Open process | **Open the lot** · Open the workflow |
| Output ready date | "Gin distillate is ready from 2 Nov" | Actions → Open process | **Open the lot** · Open the workflow |
| Untracked item | "Botanical maceration has no step that made it" | Actions → a dialog saying which step, then the workflow editor | **Record <step>** (that step's recording screen) · Open the lot · the case, when cases are on |
| Task overdue or due soon | "Call Bottle-O" · 3 days late | Actions → Open tasks (old address) | **Open the task** (Production or Sales tasks, whichever it's on) |
| NP3 check due or overdue | "Review overdue: Staff competencies" | Actions → Open NP3 check | **Open NP3 check** (that check's page, where evidence is recorded) |
| NP3 summary ("18 checks need evidence") | — | Actions → Open NP3 | Shown as the NP3 group's heading, not as a 51st card |
| Excise entry due | "Excise entry for September due 21 Oct" | Actions → See the figures (Sales → Excise) | **Prepare the entry** (Customs → Excise entry for that period, where it is lodged and recorded as lodged) |
| Stocktake due / variance | "Stocktake variance: Gin −6 L" | Actions → Start / Resolve | **Start stocktake** / **Resolve** (that stocktake) |
| Verification corrective action | "Corrective action due 31 Mar" | Actions → Open verification | **Open verification** (that registration) |
| Licence renewal, annual fee, event manager | "Off-licence: file the renewal by 17 Nov" | Actions → Open licensing (top of page) | **Open the licence** (Licensing, Licences) |
| Manager's certificate expiring | "Sam Ngata's certificate expires 4 Dec" | same | **Open certificates** (Licensing, Certified managers) |
| Licensing check review | "Display the licence…" | same | **Record the check** (Licensing, Checks) |
| Destination registration (CCA transfers) | "…destination not registered" | Actions → its link | its link, as the primary button |

"Hide until tomorrow" and "Hide for this session" stay, in the ⋯ menu. They only change this browser's view; the menu says so.

## What other products do

| Source | Kind | Pattern | What it changes here |
|---|---|---|---|
| [Vanta, My Work](https://help.vanta.com/en/articles/11997605-my-work-page) | Comparable (compliance tasks) | Four groups by urgency: Urgent (overdue), Due soon, No due date, Pending someone else; urgent first | Style 1's sections, and in every style late work comes first |
| [Stripe, Actions required](https://docs.stripe.com/connect/dashboard/review-actionable-accounts) | Comparable and craft | One list ordered by priority: information requests, past due, currently due, future. Each entry shows its due date and opens a page with the remediation path | Order by how late, not by date; each item names its fix |
| [Linear, Inbox](https://linear.app/docs/inbox) | Craft | A list of notifications; opening one shows the issue with every action. Keyboard: J/K to move, H to snooze, Backspace to remove. A priority tab ahead of the rest | Style 2: a quiet list with the detail and all actions beside it |
| [GitHub notifications](https://docs.github.com/en/subscriptions-and-notifications/concepts/about-notifications) | Craft | Group the inbox by repository or by date; "Done" clears an item; bulk actions on a selection | Style 3: grouped by area, with a count per area |
| [Carbon, notification pattern](https://carbondesignsystem.com/patterns/notification-pattern) | Pattern | An "actionable" notification carries its follow-up action as a button and takes focus; status is a word and a colour | A visible primary button on every item that has one |
| [Overflow and row actions guidance](https://www.saasui.design/blog/saas-context-menu-overflow-actions-ux-patterns); [WebAIM thread on hover-revealed actions](https://webaim.org/discussion/mail_message?id=49566) | Pattern | Put the most-used row action on the row; the overflow menu is for secondary actions. Hover-only reveals fail keyboard and touch users | **The answer to "Actions button or visible actions": visible.** The primary action is a button on the row in all three styles; only hide and snooze go in ⋯ |

**Looked for, not found:**
- Katana's and MRPeasy's handling of an expired batch: their docs cover expiry dates, not an alert or a dispose step.
- A Polaris pattern for always-visible row shortcuts: current Polaris puts row actions in a menu.

## Chosen: Style 1, the work queue (founder, 2026-10-27)

Every fix is one click from the moment the page loads, in the order it matters, which is the brief: as few clicks as possible to get value.

- **Style 2 lost:** reaching the action took a click first, and on a phone the detail pushed the list down.
- **Style 3 lost:** grouping by area hid urgency across areas. Its bulk "Dispose all N expired" was kept: it sits beside the section heading when two or more lots have expired.

The section below is kept as the record of what was compared.

## Three directions compared

| | Style 1: Work queue | Style 2: Inbox and detail | Style 3: By area |
|---|---|---|---|
| Idea | Sections by urgency (Overdue · This week · Later · No date). Each row: what, when in words, and its primary action as a button on the right | A compact list on the left (title, area, when). Choosing one shows its detail beside the list, with every action as a button. J/K move, Enter opens the action | One card per area (Stock, Customs, Food safety, Licensing, Sales, Tasks) with its count and late count. Rows inside carry their action; the area card has the bulk action where there is one ("Dispose all 3 expired") |
| Taken from | Vanta My Work, Stripe Actions required, Carbon actionable | Linear Inbox, GitHub notifications | GitHub grouped by repository, Stripe Home |
| Best at | Clearing the most urgent work first, one click each | Reading the detail before acting; working through a long list by keyboard | Seeing which part of the business is behind; one person per area |
| Gives up | Areas mixed together | A click to see the action; less fits on a phone | Urgency across areas; a late licence sits below an on-time stock check |

**All three share:**
- the fixed actions in the table above;
- late first;
- dates and status as words ("3 days overdue", "due in 5 days");
- the house header, cards and buttons;
- hide and snooze in ⋯;
- the Archive view;
- the category filter from the Production overview's links (`?category=`).

## Not in this change

- **APIs and checks:** what each check finds is unchanged. The system findings API keeps its shape, with three additions:
  - each expired lot gains its batch number, quantity and unit (all three were trimmed before);
  - module alerts may carry `area` (which part of the business);
  - an alert may carry `summary` (it counts the others, so it heads their group). The server-side changes are links, labels and wording inside existing fields:
  - stock integrity and licensing alerts link to the item or the section;
  - no id stands in for a lot or invoice name;
  - licensing dates are written in words;
  - no title is cut mid-word.
- **Follow-ups:**
  - Hiding and snoozing are still per browser. Shared "done" state needs a store and is a product decision.
  - A deep link to one sale line on Batch matching.

## Checks

- **Browser tests:**
  - every action on a seeded org lands on its page;
  - Dispose opens Record disposal with the lot chosen (fails on the old code);
  - overdue first;
  - no raw id in any notification;
  - hide and restore still work;
  - `CONCEPT ONLY` layout checks for the three styles at phone, laptop and wall.
- **Shots:** laptop, phone, dark and wall for each style; busy and quiet (empty) orgs; an action menu, the archive, and arriving by the bell.
