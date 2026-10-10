# Dashboard: redesign plan (concept, three styles)

The dashboard (`/core/dashboard`) is the first page after sign-in. It should answer, on one
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
| Geckoboard (TV dashboard guidance) | Clarity over quantity; see the whole dashboard at once; status indicators; size and position carry importance. | Style 2, and the wall-screen check on all three. |
| Bento grids (design guides) | Tiles of different sizes; size signals priority; keep rows level. | Style 2's layout and its capped lists. |
| Linear Pulse, Notion dashboard summary, Trackingplan digest | Prose first, charts under it. | Style 3's opening sentence, built from the same figures. |
| Carbon tiles; KPI card anatomy | Tiles in a row share a height; label, value, comparison, small trend with no axes. | The This week grid. |
| Stephen Few, *Information Dashboard Design* | A dashboard fits one screen and is read at a glance; it should grab attention only when needed. | The first screen holds attention, health and the week. Sparklines appear only when the series moves. |

Not found: an official description of Stripe's or Mercury's current home layout, or any
usability study on dashboards for small manufacturers. The table's first two rows rest on
vendor support docs and a third-party breakdown.

## Three directions to choose from

The page is the first thing a user sees each day and may sit on a wall TV: the whole
business on one page, and still easy. Three ways to do that. All three show the same data
from the same script; they differ in layout and emphasis. Open `/core/dashboard?style=1`,
`?style=2` or `?style=3`, or use the switch in the header. **Once one is picked, the switch
and the other two styles are deleted.**

| | Style 1: Stacked | Style 2: Board | Style 3: Rail |
|---|---|---|---|
| Idea | Full-width cards in priority order. Read top to bottom. | A grid where size carries priority and the whole business fits one screen. | The summary (score and the week) is one panel down the left that stays in view; the work scrolls beside it. |
| Taken from | Stripe's and Shopify's home pages: today's figures and what needs action first. | Geckoboard's TV guidance (clarity over quantity, see it all at once) and bento grids (size signals priority). | Summary rails beside a work column: Linear's properties panel, Mercury's account rail, monitoring tools' status sidebars. |
| Best at | A laptop at a desk. Nothing is ever beside anything taller. | A TV, or a wide monitor glanced at through the day. | Working down a long attention list or plan without losing sight of the numbers. |
| Gives up | Needs a scroll to reach the lists. | Lists are capped at four rows and three batches to keep cards level; Workspaces and most of Activity are a click away. Below 1280px it falls back to Style 1. | Figures are small and have no trend lines; the rail takes 372px. Below 1100px it falls back to Style 1. |

A first third style, "Briefing" (one plain sentence, then borderless sections in a reading
column, after Linear Pulse and Notion's dashboard summary), was shown in round one and
dropped: it gave up the boxes and width the other two use well.

### The menu along the bottom (round two)

The side menu takes 260px. On a phone it is already a bar along the bottom. A second
concept switch, `?nav=bottom` or "Menu at bottom" in the header, does the same at laptop
and desktop widths **on this page only**, to see what each style does with the width:
Style 1's tiles and compliance parts breathe; Style 2 fits score, week, attention and plan
on a 1080p screen with room to spare; Style 3's work column gains the most.

This is a look at the dashboard, not a proposal to move the menu everywhere. Doing that is
a shell change touching every page (the collapsed state, the logout control that lives in
the menu's footer, the bee menu) and would be its own piece of work. The switch clears
itself when the dashboard is left.

Common to all three:

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
5. **Setup strip**, **Workspaces**, **Recent activity** as before.

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
- e2e: the compliance card shows the figure, state and parts; This week is a full grid of
  equal bordered tiles above the plan; every style renders at 390, 1440 and 1920 with no
  sideways scroll and no trend line over a number; the board fits one wall screen with its
  two lists level; the rail stays in view, below the top bar, while the work scrolls; the
  menu can sit along the bottom and goes back when the dashboard is left.
- Screenshots of each style at 1440, 1920 (wall), 1024 and 390, dark, and on a quiet day.
