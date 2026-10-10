# Home (the dashboard): redesign plan

Home (`/core/dashboard`, called Dashboard until this change) is the first page after sign-in. It should answer, on one
screen: what needs me today, and is the business healthy. This plan covers how the page
shows that. The summary API (`/api/core/dashboard/summary`) is unchanged.

## What is wrong today

Observed on a seeded org at 1440 wide (screenshots in the MR):

- **Seven stacked cards, about 2,900px tall.** The answer to "what needs you today" is one
  row in the second card. The rest is below the fold.
- **The same number three times.** Active batches is in the Workspaces summary, in Business
  signals and in Production flow. Open action items is a KPI tile directly under the list of
  those items.
- **Tiles with nothing to say.** Sparklines are drawn for flat and all-zero series, and
  "Set target" sits in the slot where a number goes.
- **Setup takes the top slot.** The go-live card is the largest thing above the fold.
- **The health score is not shown.** The API already returns a production health score, its
  state and what is driving it. The dashboard ignores it.
- **Ten event rows, each a full bordered card,** make the page's longest section its least
  urgent one.
- Dates are forced to US format ("Oct 10, 8:34 AM") whatever the browser's locale.

## What other products do

| Source | Pattern | Use here |
|---|---|---|
| Stripe Dashboard home (Stripe support docs) | "Today" figures first, plus the items that need action (disputes, verifications). Charts are secondary and estimates. | Needs attention and health lead; the week's figures are one quiet row. |
| Mercury (design breakdown) | Position first, controls one level down. Red and amber are reserved for "act now" and used for nothing else. | Colour only on the attention list, the health state and a non-zero failure count. |
| Linear Inbox (Linear docs) | Priority items by default; everything else is a second tab. | Attention rows are whole-row links, most severe first. Activity is short, with the rest one click away. |
| Shopify app home pattern (shopify.dev) | Order: one banner, setup guide, metrics, callouts. One banner at a time; setup is dismissible and remembered. Metric cards are clickable and show change. | Go-live becomes a slim strip that can be hidden. Figures link to where the number lives. |
| Shopify admin Home, 2026 update (merchant community thread) | Merchants objected when stats were pushed behind suggestion cards. | Nothing promotional above the work. Setup is one line, not a card. |
| Odoo manufacturing dashboards | Status tiles (in progress, done, late) that click through to the filtered list. | The week's figures are links, not static tiles. |
| Katana (support docs) | No KPI home at all: Make opens on the schedule and tasks. | Planned production keeps its own block beside attention, not under the KPIs. |
| Safefood 360 (help guide) | A site compliance dashlet: one percentage, defined, with red / orange / green bands. | One overall figure with a stated definition and a state in words. |
| Drata and Vanta (help docs) | Readiness per framework as a percentage with a progress bar; neither documents a single blended number. | The parts are always shown beside the overall figure, each with its own bar. |
| Geckoboard (TV dashboard guidance) | Clarity over quantity; see the whole dashboard at once; status indicators; size and position carry importance. | The board, and the wall-screen check. |
| Bento grids (design guides) | Tiles of different sizes; size signals priority; keep rows level. | The board's layout and its capped lists. |
| Linear Pulse, Notion dashboard summary, Trackingplan digest | Prose first, charts under it. | Tried as a "briefing" style and dropped: it gave up the boxes and width the board uses well. |
| Carbon tiles; KPI card anatomy | Tiles in a row share a height; label, value, comparison, small trend with no axes. | The This week grid. |
| Stephen Few, *Information Dashboard Design* | A dashboard fits one screen and is read at a glance; it should grab attention only when needed. | The first screen holds attention, health and the week. Sparklines appear only when the series moves. |

Not found: an official description of Stripe's or Mercury's current home layout, or any
usability study on dashboards for small manufacturers. The table's first two rows rest on
vendor support docs and a third-party breakdown.

## Design: a board

The page is the first thing a user sees each day and may sit on a wall TV: the whole
business on one page, and still easy.

Three layouts were built and shown side by side (!512): a stacked column, a board, and a
rail with the summary pinned down the left. A "briefing" style and a menu along the bottom
of the screen were also tried. **The board was chosen, with the menu staying down the left.**
The others were deleted with the switch that chose between them.

**With room (about 1100px for the page itself), the page is a board**: a grid where size
carries priority. The compliance score and This week share the top row; Needs attention and
Today's planned production share the second, level with each other; Recent activity runs
underneath. On a 1080p wall screen the first two rows fit without scrolling. To keep the
cards level, the board caps Needs attention at four rows, the plan at three batches and
Recent activity at three lines; each has its link to the full list. The Workspaces block is
left out of the board, since it repeats the menu.

**With less room, the page is one stacked column** in the same order, full lists and the
Workspaces block included. This is what a phone, a tablet and a 1280px laptop with the menu
open get. The switch is by the room the page has (a container query), not the window, so
collapsing the menu on a small laptop is what turns the column into the board.

Taken from: Geckoboard's guidance for wall screens (clarity over quantity, see it all at
once), bento grids (size signals priority), and Stripe's and Shopify's home pages (today's
figures and what needs action first).

What the page shows:

1. **Compliance score.** One figure out of 100 for the whole business, drawn as a ring,
   with its state in words and the parts it is made of beside it, each with its own score,
   bar and a line of detail (what is costing points; evidence count and next verification).
2. **This week.** A full grid of bordered figures: open action items, active batches,
   started, completed, failed or cancelled, operator actions, revenue this month, customer
   tasks due. The count is always even (8, 6, 4 or 2 by role), so no row is left ragged.
   Each links to its page. A trend line is drawn only when its series moves and the tile is
   wide enough to hold it.
3. **Needs attention**, then **Today's planned production.** This week sits above the plan.
4. **Live.** The header says so, and the page refreshes itself every minute as well as on
   every change LiveSync reports, so a screen nobody touches stays current.
5. **Setup strip** and **Recent activity** as before.

## The tab is called Home

The first tab, the page heading and the first breadcrumb now say **Home**. The address
(`/core/dashboard`) and the API are unchanged. Production and Compliance keep their names.

| Looked at | What they call it | What it changed here |
|---|---|---|
| Stripe, Vanta, Xero | The landing page with figures is "Home" | Home, not Dashboard: shorter on the phone bar and the name people already know |
| Katana (Sell, Make, Buy, Stock), MRPeasy, Cin7 Core, Breww | Short plain words; the making area is "Production" or "Make" | Production stays |
| Drata; Nielsen Norman Group on branded terms in menus; HubSpot (sells "Marketing Hub", menu says "Marketing") | The plain word in the menu, the product name on the pricing page | Compliance stays as the tab; "Core" and "Compliant" stay as plan names, not tab names |

Not found: the menus of Ekos, DISTILLx5 or CraftedERP, or any study of how small producers
read these words.

## The sidebar collapses to a rail

The menu is the shell's, so this applies to every signed-in page, not only Home.

The menu stays down the left: that is the convention for this kind of product, and
Material and SAP Fiori both treat a bottom bar as a phone pattern. The width it takes
(260px) comes back by collapsing it to an 80px rail.

- **A rail with names, not bare icons.** Each tab keeps its label under its icon, as on the
  phone's bottom bar (Material's navigation rail). The old collapsed state hid the labels,
  the logo and the logout button.
- **Nothing reflows when it moves.** Each icon keeps its place and lifts 8px; the wide label
  fades out, the width glides (240ms), the small label fades in. The page beside the menu
  and any bar pinned along its edge move with it, because one length (`--sidebar-w` in
  `styles2.css`) drives all of them. Five pages each hard-coded the two widths for a pinned
  bar; they now read that length, and Inventory's edit panel, which ignored the collapsed
  state, is fixed by the same change.
- **It is remembered**, per browser, and applied before the first paint so a collapsed menu
  never flashes open on a full load. Until then, the script that set the page's margin by
  hand forgot the choice on every load.
- **A narrow laptop or tablet (768 to 1099px) starts as the rail** until the user chooses
  otherwise. The phone keeps its bottom bar whatever was chosen elsewhere.
- **The control** is a quiet button in the menu's corner, named for what it will do
  ("Collapse menu" / "Expand menu") with `aria-expanded`, in place of a bright blue circle
  floating over the logo. With reduced motion set, the change is instant.

### The overall compliance score is new, and its definition is an assumption to confirm

The summary response gains `compliance_overall`. It is the **mean, equally weighted, of
every compliance score the summary already carried**: the production checks score, and
each enabled compliance module's evidence score (NP3 today). Its state is the worst of its
parts. An org with no compliance module gets the production score unchanged.

No existing figure is recalculated. But averaging them is a product decision, and equal
weighting is the simplest defensible choice, not the only one: an org at 69 on production
checks and 9 on NP3 evidence shows 39. The parts are always on screen so the figure can be
read back. Say if the weighting should differ, or if the overall figure should be the
lowest part rather than the mean.

The module's score, bar and evidence count used to be repeated in the Compliance workspace
tile; they now live in the compliance card only. The next verification date (plan 2.2,
"always on screen") moved with them.

## Not in this change

- One addition to `/api/core/dashboard/summary`: `compliance_overall` (above). No existing field
  or calculation changes.
- Role gating is unchanged: planned production needs `production.view`, sales figures need
  `sales.view`.
- Currency is still formatted as US dollars in the script; the org's currency is not in the
  response. Follow-up.
- The top bar's contents are centred in a 1400px column, so on a 1920px screen the bell and
  the account menu sit inside the page's right edge. It predates this change and is on every
  page. Follow-up.
- Other pages still say "dashboard" in places (the landing page's button, some help text).
  Home is named in the menu, the page and the breadcrumb; the rest is a follow-up.
- The summary route takes "today" from the server clock's date (`date.today()`) and then
  treats it as a New Zealand date. The production image sets its clock to Pacific/Auckland,
  so the two agree there; on a UTC machine (CI) the NZ morning is filed under yesterday.
  One line to fix (`datetime.now(_APP_TZ).date()`), but several existing tests build due
  dates from `date.today()` and would need the same change. Follow-up.
- Removed from the page (still in the API): the revenue baseline variance and
  month-on-month rows. "Open action items" was removed in the first version and is back.

## Checks

- `tests/e2e/test_workspace_overviews.py`: the dashboard layout test names the old blocks;
  update it to the new ones.
- Unit: `compliance_overall` is the equal mean, its state the worst part, and a module part
  keeps its evidence count and next verification.
- e2e, the page: the compliance card shows the figure, state and parts; This week is a full
  grid of equal bordered tiles above the plan; the page renders at 390, 1024, 1440 and 1920
  with no sideways scroll and no trend line over a number; the board fits one wall screen
  with its two lists level, three lines of activity and no Workspaces block.
- e2e, the sidebar (`tests/e2e/test_sidebar_rail.py`): the rail keeps every tab's name inside
  its width and gives the page the 180px; icons do not move sideways; the choice survives an
  in-app visit and a reload, and is in place before the page's scripts run; a pinned bar
  moves with the sidebar; a narrow laptop starts as the rail; the phone keeps its bottom bar.
- Screenshots at 1280, 1440, 1920 (wall), 1024 and 390, each with the sidebar open and as
  the rail, and dark.
