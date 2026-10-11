# Production overview: redesign plan (concept)

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

Open `/core?style=1`, `?style=2` or `?style=3`, with `&cta=left` or `&cta=center` for Styles 2
and 3, or use the switches on the page. Everything below the buttons is the same board in all
of them. **Once one is picked, the switches and the others are deleted.**

| | Style 1 (round two's pick) | Style 2 | Style 3 |
|---|---|---|---|
| Top to bottom | Tabs; then the title with the buttons on its line, at the right | The title; then the tabs; then the buttons in a row | Tabs; then the title; then the buttons in a row |
| Buttons | Right, main one furthest right | Left or centred, main one first | Left or centred, main one first |
| Best at | Costs no height; the convention for a page's main button | The page says what it is before offering its sections; the buttons sit right under the tabs | Leaves the tabs where they are on every other Production page; the buttons belong to the title |
| Gives up | The buttons are far from the title on a wide screen | The title moves above the tabs here but not on Planner, Workflows or Inventory unless those change too; 60px more height | 60px more height |

On a phone the buttons are full width in every style, so left and centred look the same there.

Shared by all of them:

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
   links in a row. With less than about 1100px, it is one stacked column.

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
- The style switch's script moves the "Get to work" card (and, for Style 2, the tab strip) to
  where each style wants it. Once a style is chosen the markup is written that way and the
  script goes.
- Style 2 changes the order of title and tabs on the overview only. If it is chosen, the same
  order should be applied to Planner, Workflows and Inventory, which is a shell change.
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
  variant at 390, 1024, 1440 and 1920 with the main action on the first screen, no button
  drawn over another and no sideways scroll; each style ordering title, tabs and buttons as it
  says; the row centring; and the arrangement surviving an in-app visit.
- Screenshots of each style at 1440 (sidebar open and as the rail), 1920, 1280, 1024 and 390,
  and dark.
