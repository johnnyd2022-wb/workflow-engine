# Production overview: redesign plan (concept, three boards)

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

## Round two: three boards that differ in where the actions sit

Open `/core?style=1`, `?style=2` or `?style=3`, or use the switch on the page. All three are
the same board with the same data. **Once one is picked, the switch and the other two are
deleted.**

| | Style 1: In the header | Style 2: An action bar | Style 3: Beside the work |
|---|---|---|---|
| Idea | The actions are buttons on the title's line, main one solid and furthest right. | A bar across the top of the board: three large tiles, each saying what it is for. | The batches fill the first screen with a column of actions beside them; health and figures follow. |
| Taken from | The page-header primary action in Shopify's admin and Polaris, Stripe, Linear | Quick-action rows on Mercury's and Xero's home pages; Katana's Make screen actions | Odoo's and Katana's work-first screens; Home's two-column second row |
| Best at | Being where people look for a page's main button; costs no height, so health and figures stay on the first screen. | Being impossible to miss, and explaining each action to someone new. | Putting the work and its actions together; least scrolling to reach a batch. |
| Gives up | No room for a description of each action. | About 200px of height before health and the figures. | Health and the figures move below the fold. |

The "Taken from" row for round two is from my knowledge of those products. The searches to
source it (Polaris's page-header primary action, quick-action rows) were not run: the session's
usage limit was reached first. Treat that row as unverified until they are.

Shared by all three:

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
6. With less than about 1100px of room, every style is one stacked column with the actions
   first, so the main one is on a phone's first screen.

The page keeps the section's reading width (1280px) on a wide screen, unlike Home's 1760px,
so the tab strip does not jump when moving between Overview, Planner, Workflows and Inventory.

### The main action changed, and that is a product call

Once an org has stock, a workflow and a batch, the main action in "Get to work" used to be
"Trace and recall". It is now **"Record production step"**, with "Trace and recall" beside
it. Recording is the everyday job on this page; tracing is the occasional one. During setup
the main action is unchanged (add inventory, then create a workflow, then record a step).

## Not in this change

- No change to `/api/core/hub/overview` or any calculation. "Longest running" and the lanes are
  worked out in the page from the batches the response already carries.
- That response carries at most 20 batches. The page says how many it shows; an org with more
  than 20 under way would need the cap raised or a link to the rest. Follow-up.
- The batches have no batch number in this response, so two batches of one product are told
  apart by step and age. Adding a number is an API change. Follow-up.
- In Style 1 the "Get to work" card is moved into the page header by the style switch's
  script. Once a style is chosen it is written where it belongs and that script goes.
- In the stacked layout the batches are shown second but come later in the page's source, so
  keyboard order differs from visual order. To be fixed in the markup once a style is chosen.
- Reaching Production by an in-app link leaves the tab strip 32px lower than a full load does.
  It predates this change (it is in the screenshots of the unchanged page). Follow-up.

## Checks

- `tests/e2e/test_workspace_overviews.py`: the overview layout test pinned the old stack and a
  click-to-open batch; it now checks the board at 1440, the stacked order at 390 and 1024, and
  the action on the batch.
- `tests/e2e/test_production_overview.py` (new): batches in age order with step, progress and
  age; the quiet-floor state and the greyed clear check; leaving mid-load logs no failure;
  recording production is the main action and the only filled one; and, concept-only, every
  style at 390, 1024, 1440 and 1920 with the main action on the first screen, no action drawn
  over another and no sideways scroll; each style putting the actions where it says; and the
  header actions surviving an in-app visit.
- Screenshots of each style at 1440 (sidebar open and as the rail), 1920, 1280, 1024 and 390,
  and dark.
