## Pick a style

Roadmap **8.1d — the Purchases page** (spec "The Purchases page"), stacked on !693. Three concept styles on the same data, behind `?style=1|2|3` (and the switch in the header). **Pick one and the other two are deleted before this merges.**

| | Style 1: Reconcile pairs | Style 2: One at a time | Style 3: Review table |
|---|---|---|---|
| Idea | Each card: what Xero says ← → what to do | One purchase fills the screen; keys 1/2/3 act | Dense rows, select many, batch bar |
| Taken from | Xero bank reconciliation | Linear Triage | QuickBooks "For review", Carbon batch actions |
| Best at | A normal week at a laptop | Clearing a backlog fast | A big historical run of small purchases |
| Gives up | Fewer per screen | No overview, no bulk | Less room for "last time"; link via the dialog only |

| Style 1 | Style 2 | Style 3 |
|---|---|---|
| ![style1-laptop](/uploads/84319fdb6d7efc2ec11c3ca38b168aec/style1-laptop.png) | ![style2-laptop](/uploads/16b2e3d6ab7b91645c99fa1136ffade8/style2-laptop.png) | ![style3-laptop](/uploads/d13c0dff79387186aca586cdd90d99d3/style3-laptop.png) |
| ![style1-phone](/uploads/4e92aeae89348659e2f56b86f8e9dcfc/style1-phone.png) | ![style2-phone](/uploads/af54e243cd7d23d0f48cf24caa139322/style2-phone.png) | ![style3-phone](/uploads/2873773294c67847db6954ec1f573335/style3-phone.png) |

Shared by all three — the record dialog (pre-filled from a rule or last time) and Style 3's batch bar:

![dialog-record-laptop](/uploads/bc1e9af344d33a43dbaa552da3d064cd/dialog-record-laptop.png) ![style3-selected](/uploads/4c0c1c1e80e7e80ef78f22331471a0ef/style3-selected.png)

My recommendation: **Style 1**. It's the shape producers already know from Xero, it shows the "last time" suggestion beside every purchase, and it keeps "Already in stock" one click away. Style 2 is the better tool for a 100-card historical catch-up and could become a mode later.

## What changed

- `/core/costing/purchases`: tabs with counts (To record / Recorded / Skipped / Not stock), cards with the pre-fill, Record stock (dialog: rows, "the rest isn't stock / record later"), Already in stock (candidates), Lower the cost of… (refunds), Not stock, Skip, review Keep / Unlink, Undo toasts, "Remember for <payee>".
- Production nav: a Purchases link beside Inventory and Suppliers, only for orgs with the `costing` feature. Nav conditions are now computed on Production pages too (they were Compliance / Sales / Settings only).
- `scripts/ui_shots.py seed purchases`: a month of card spend in every state.

**Bug found driving the page (fixed on !690, merged up):** `purchase_lines` had a foreign key to `xero_accounts` but the costing models didn't import that model, so any process without the CRM slice loaded crashed on its first purchase write. Test added; fails without the fix.

## Behaviour to be aware of

- Finished goods bought in are offered as "already in stock" candidates (per spec), so a botanicals purchase can list nearby bottles.
- A recorded purchase's card doesn't yet say what it became (follow-up).

## Research and plan

`docs/purchases-page-plan.md`: Xero reconciliation, QuickBooks bank feed, Linear Triage, Carbon batch actions; what each changed here.

## Tests

- `tests/test_costing_purchases_page.py`: served for `costs.view`, 403 / 404 gates, view-only users get no actions, nav link only for costing orgs.
- Screenshot scenarios (7 passes, last one empty): 3 styles × desktop / laptop / phone / dark, every tab, record and link dialogs, an end-to-end record, a bulk selection.
- **Not done:** Playwright e2e in CI — the dev server runs on the shared test DB, which doesn't have the costing migrations; to add once !689–!693 are on main.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_012K4jB79TxztZobCHJU3cVj
