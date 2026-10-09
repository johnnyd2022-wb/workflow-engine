# Dashboard: redesign plan (concept)

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
| Stephen Few, *Information Dashboard Design* | A dashboard fits one screen and is read at a glance; it should grab attention only when needed. | The first screen holds attention, health and the week. Sparklines appear only when the series moves. |

Not found: an official description of Stripe's or Mercury's current home layout, or any
usability study on dashboards for small manufacturers. The table's first two rows rest on
vendor support docs and a third-party breakdown.

## Design

1. **Header.** "Dashboard", today's date underneath, and "Updated 8:34 pm" at the right.
2. **Setup strip.** One line with the go-live button and "Hide". Only until go-live is set.
3. **Needs attention** (left, wide). One row per item: severity dot, what it is, which
   workspace, the count, a chevron. The whole row is the link. Empty state: "Nothing needs
   you right now."
4. **Production health** (right). The score out of 100, its state in words, and the top
   drivers with what each costs. New on this page; the data was already in the response.
5. **Today's planned production.** Under attention. One line when there is nothing planned.
6. **This week.** One row of figures replacing Business signals, Production flow and
   Commercial pulse: active batches, started, completed (with change on last week), failed
   or cancelled, operator actions; and for Sales roles, revenue this month and customer
   tasks due. Each figure links to its page. A sparkline is drawn only when its series moves.
7. **Workspaces.** Kept, smaller. Compliance keeps its evidence bars.
8. **Recent activity.** Six compact rows, "Show more" for the rest, Today / This week as a
   two-button switch.

## Not in this change

- No change to `/api/core/dashboard/summary` or to any figure's calculation.
- Role gating is unchanged: planned production needs `production.view`, sales figures need
  `sales.view`.
- Currency is still formatted as US dollars in the script; the org's currency is not in the
  response. Follow-up.
- Removed from the page (still in the API): the "Open action items" tile, the revenue
  baseline variance and month-on-month rows. They duplicated or qualified other figures.
  Say so if any of them is missed.

## Checks

- `tests/e2e/test_workspace_overviews.py`: the dashboard layout test names the old blocks;
  update it to the new ones.
- New e2e: attention row is a link to the item's page; health card shows the score and
  state; a flat series draws no sparkline; activity shows six rows then expands; the setup
  strip can be hidden and stays hidden.
- Screenshots at 1440, 1024 and 390, light and dark, and after a boosted round trip.
