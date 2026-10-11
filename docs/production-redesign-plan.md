# Production overview: redesign plan

The Production overview (`/core`) is where someone running the floor lands. It should answer,
on one screen: **what is under way right now, is anything wrong, and what do I do next.**
This plan covers that page only. The pages behind its tabs (Planner, Workflows, Inventory)
and the overview API (`/api/core/hub/overview`) are unchanged.

It builds on !512: Home is a board, the tab is called Home, and the sidebar collapses to a
rail. Style 1 here is that same board, so the two pages read as one product.

## What is wrong today

Observed in screenshots of a seeded org with four workflows and seven batches under way
(`~/.cache/workflow-engine-ui-shots/prod/00-before`):

1. **The answer is last.** Active production is the fourth card, about 1,400px down. Above
   it sit a health card, eight counters, a "Get to work" card and a grid of links.
2. **Every batch says the same thing.** All seven rows read "In progress". How far along a
   batch is, and how long it has been going, are behind a click on each row.
3. **The next step is two clicks away.** "Record next step" only appears after a row is
   opened.
4. **Seven batches, six shown**, with nothing to say one is missing.
5. **Counters that do not help.** "Product workflows 4" and "Stock lines 32" take the same
   space as "Active batches".
6. **The clear checks shout as loudly as the failing ones.** "0 Expires in 7 days" has the
   same weight and the same instruction ("Use, hold, or plan disposal") as "3 Expired stock".
7. **A cancelled request is reported as a failure.** Leaving the page while it loads logs
   "Failed to load core overview: AbortError" to the console.
8. **A workflow with no steps** would have shown a batch with nothing where its progress goes.

## What other products do

| Product | What it does | What it changes here |
|---|---|---|
| Katana, Make screen (support docs) | One schedule of manufacturing orders: status (Not started, Work in progress, Done), ingredient availability, deadline; the status is changed from the row. | The work is the page, and each row carries its own action. Style 3 is this. |
| Breww, production dashboard (docs) | A picture of every vessel: what is in it and how full, at a glance; the batch list is one click away. | Show where each batch is, not just that it exists: the step and a progress bar on every batch. |
| Odoo 17 Shop Floor and work orders (third-party guides) | Work orders as cards with Start, Pause and Done on the card; kanban grouped by status or work centre. | The action on the batch itself. (Lanes by stage were tried in round one and dropped.) |
| MRPeasy (docs, demo video) | A dashboard of key figures, separate from the schedule and from "My production plan" for workers. | Figures support the work; they do not lead it. At a glance sits beside or below. |
| Tulip (vendor blog) | Floor dashboards should show less: "it is easy to become overwhelmed"; start from the whiteboard. | Six figures, not eight, and a clear check goes quiet. |
| Linear (docs, changelog) | The same items as a list or a board; lists are denser and ordered, boards group by status. | Styles 2 and 3 are the board and the list of the same batches. |
| Shopify Polaris, index table and resource index (design system) | One column; an at-a-glance table whose rows lead to an action; filters sit above the list and affect it. | Style 3's table, its filter above it, and the action at the end of the row. |
| Home, this app (!512) | A board: a status card beside bordered figures, then two cards level with each other. | Style 1, tile for tile. |

Not found: the exact columns of Katana's schedule, Odoo's kanban card states, or any study of
how small producers read a production screen. The Odoo detail rests on third-party guides.

## Round one: the board was chosen

Three layouts were shown first (!515, round one): a board that matches Home, the batches in
lanes by stage, and a worklist table. **The board was chosen.** The lanes and the worklist
are deleted. The note back was that the main actions ("Get to work") sat off to the side and
did not read as the page's calls to action.

## Round two: where the actions sit

Three boards were shown that differed only in where "Get to work" sits: in the page header,
as a bar of large tiles above the board, and in a column beside the batches. **The header
version was the only one that worked.** The other two are deleted.

## Round three: the title, the tabs and the action buttons

Three orders were shown: tabs then title with the buttons on its line; title, tabs, buttons;
and tabs, title, buttons, the last two with the buttons left or centred. None was picked
outright. Two questions came out of it, and both were researched before round four.

**Does the page need its title?** Mostly yes. Shopify's page guidance says to always give a
page a title; the W3C's pattern for making a page's purpose clear asks for a clear heading at
the top of each page, and a 2014 W3C list thread argues against hiding it for sighted users.
Only Microsoft's Fluent 2 goes the other way, and its advice is to leave the space empty *or
use a different title* when the title merely repeats where you are. So: keep the title, drop
the sentence under it, which carried nothing.

**Are tabs the right tool, and are ours drawn right?** Tabs suit a small flat set of sibling
pages (Carbon: no more than six; Appian: fewer than seven), and Carbon pairs a side menu with
"tabs within the page" for what sits beneath it. But:

| Finding | Source | What it changes |
|---|---|---|
| Put tabs directly above their content; avoid anything between a tab and its panel. | Nielsen Norman Group, "Tabs, Used Right" | Title first, then tabs, then the board. |
| Primary tabs go under the bar that holds the title. | Material 3, via SAP Fiori's usage page | The same order. |
| A filled, equal-width, boxed bar is a segmented control, used to switch views of the same content; use tabs to switch the main view. | Apple HIG; Keystone; designsystems.surf | Underlined tabs for the section, keeping the filled look for switches inside cards. |
| Navigation tabs and in-page tabs should look different. | Nielsen Norman Group | The same. |
| Mark the current tab at least twice. | Nielsen Norman Group | A bar under it and a darker, heavier label. |
| Title, with the page's actions on the same line at the right. | An Atlassian designer, on the developer forum (informal) | Buttons at the right of a row, main one furthest right. |

Not found: how Katana, Linear or Stripe lay this out, or any current guidance on full-width
tabs on a wide desktop.

## Round four: five mock-ups, and the choice

Five were shown with the title alone on top and the tabs beneath: tabs underlined on a divider
or as the old filled selector, left or centred, with the buttons on the tab row or the row
beneath. **A was chosen: underlined tabs at the left, buttons on the same row at the right**,
with two changes asked for: the current tab's label is green as well, and its bar runs the
whole width of the tab. The other four and the switch are deleted.

## The design

### A section head, shared by every page under a main tab

`app/ui/templates/shared/section_tabs.html` and `section-tabs.css`. It replaces the filled
tab strip on every page that had one, in Production, Compliance and Sales.

1. **The section's name**, alone, starting where Home's title starts. No sentence under it.
2. **The tabs, on a divider line, directly above the page.** The current tab is marked three
   ways: green text, a heavier label, and a bar on the divider. Tabs touch each other, so the
   bar runs the tab's whole width and ends half way to the next label; the first tab starts
   at the page's left edge.
3. **A slot for a page's main buttons** on the tab row, at the right, main one furthest right
   (`{% block section_actions %}`). Without room for both (under about 1100px for the page,
   which includes a 1280px laptop with the sidebar open), the buttons take the row beneath,
   main one first, and the divider stays under the tabs.

On the Production overview, the Compliance home and the Sales overview, the section's name is
the page's title (its `h1`) and those pages' own titles and subtitles are gone. Every other
page keeps its own title beneath the tabs, and the section's name above is plain text, so each
page still has exactly one main heading.

**Known and deliberate for now:** Planner, Workflows and Inventory show "Production", the tabs,
and then their own title, which repeats the tab's word ("Workflows" under a "Workflows" tab).
Removing those titles and moving each page's buttons into the head is the next step for each
page as it is redesigned; doing it here would have touched every Production page's layout.

### The Production overview

1. **One main action, and it looks like one.** "Record production step" is a solid button;
   "Add to inventory" and "Trace and recall" are outlined beside it. Before, the main action
   was a pale full-width block and, once setup was done, it was "Trace and recall".
2. **Every batch shows its next step, a progress bar with "Step 2 of 3", and how long ago it
   started**, longest running first. All of them, not the first six.
3. **"Record next step" is on the batch**, in view. Its accessible name includes the product
   and the step, so two batches of one product can be told apart.
4. **Production health** keeps its state in words, its bar and "View health details". The four
   standing checks (expired, expiring, low stock, missing trace link) sit with it; a check at
   zero is greyed and says "Nothing to do".
5. **At a glance** is six bordered figures, each a link: active batches, longest running,
   finished this week, product workflows, stock lines, stock movements in 24 hours.
6. With room, health sits beside the figures, then the batches run the full width, then the
   links in a row. With less than about 1100px, it is one stacked column in the same order.
   The page's source is in that order too, so keyboard order matches what is seen.

The page keeps the section's reading width (1280px) on a wide screen, unlike Home's 1760px,
so the tab strip does not jump when moving between Overview, Planner, Workflows and Inventory.

### The main action changed, and that is a product call

Once an org has stock, a workflow and a batch, the main action in "Get to work" used to be
"Trace and recall". It is now **"Record production step"**, with "Trace and recall" beside
it. Recording is the everyday job on this page; tracing is the occasional one. During setup
the main action is unchanged (add inventory, then create a workflow, then record a step).

## Not in this change

- No change to `/api/core/hub/overview` or any calculation. "Longest running" is
  worked out in the page from the batches the response already carries.
- That response carries at most 20 batches. The page says how many it shows; an org with more
  than 20 under way would need the cap raised or a link to the rest. Follow-up.
- The batches have no batch number in this response, so two batches of one product are told
  apart by step and age. Adding a number is an API change. Follow-up.
- Planner, Workflows, Inventory and the pages beneath them keep their own titles and header
  buttons for now (see above). Compliance's and Sales' other tabs likewise.
- Some page logs "AbortError: Request cancelled by navigation" to the console when it is left
  mid-load. Production overview and Inventory no longer do; the source of the remaining one
  was not traced. Follow-up.
- **Root cause found for "the page sits 32px lower after an in-app click".** `base_spa.html`
  boosts with `hx-target="#page-content"` and `hx-select="#page-content"` and the default
  swap, so the selected `<main id="page-content">` is inserted *inside* the existing one: two
  elements with that id, and the top padding applied twice. The section head is made immune
  to it here. Fixing it properly (selecting the children, or swapping the element itself) is
  a shell change that every page's boosted render depends on, so it is its own piece of work.

## Checks

- `tests/e2e/test_workspace_overviews.py`: the overview layout test pinned the old stack and a
  click-to-open batch; it now checks the board at 1440, the stacked order at 390 and 1024, and
  the action on the batch.
- `tests/e2e/test_production_overview.py` (new): batches in age order with step, progress and
  age; the quiet-floor state and the greyed clear check; leaving mid-load logs no failure;
  recording production is the main action and the only filled one; the page opening with its
  title, then the tabs, then the board at 390, 1024, 1440 and 1920, with the buttons on the tab
  row when there is room and beneath when there is not, nothing overlapping and no sideways
  scroll; the current tab marked by colour, weight and a bar the tab's whole width sitting on
  the divider, with tabs touching; and another Production page showing the section, the tabs in
  the same place, and its own title, with one main heading.
- Screenshots of the overview at 1440 (sidebar open and as the rail), 1920, 1280, 1024 and 390
  and dark, and of Planner, Workflows, Inventory, Batches, Tasks, Compliance and Sales.
