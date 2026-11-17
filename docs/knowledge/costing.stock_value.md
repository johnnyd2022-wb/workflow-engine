---
topic: "costing.stock_value"
title: "Stock value and snapshots"
domain: "costing"
summary: "Stock value is quantity times cost per lot plus the pool of running batches. A month-end snapshot freezes the quantities at once and its value when the month is closed."
related_topics:
  - costing.cost_status
  - costing.xero_bridge
  - production.intermediates
related_operations:
  - costing_get_stock_value
features:
  - costing
---
# Stock value and snapshots

## What it means

Stock value is, for each lot with quantity that is not customer-owned, its quantity times its known unit cost, plus one line for each batch still running holding its unabsorbed pool. It is split into raw, work in progress, finished and in production, and into actual, estimated and partial dollars.

A **snapshot** records the stock at a cutoff. Month-end snapshots are taken automatically after a month ends, with the quantities as at the cutoff, frozen at once.

A month-end snapshot's value is **provisional** until the month is closed: most of a month's bills and card spend are recorded in the days after it ends, so until then it is the frozen quantities at today's costs, and it changes as those purchases are recorded. Someone who can manage costs closes it, or it closes itself on the first sync or costing read on or after the 20th of the next month (an assistant's read never closes it). Closing values it once; from then on it is held fixed, and later changes show only as changes since close. ASSUMPTION: the 20th is late enough for a small producer's bills to be in; it is a setting, and an org can close earlier with the button.

## How the records relate

- A lot with no cost is listed with no value and counted in `unknown_lots`. A partly costed lot carries its floor.
- When snapshots exist, the movements between two of them explain the change in value (purchases, sales, wastage, samples and so on) and sum exactly (costing.xero_bridge).
- A finished batch's leftover pool is a production loss, not stock.
- Months close oldest first. A manual snapshot taken while the month before it is provisional is provisional too, and closes with that month.

## Authoritative operations

`costing_get_stock_value`: the current value, its split, `complete`, and the count of lots with no cost. Snapshots, closing a month and the CSV closing stock are separate app operations; a snapshot read says `status` (`provisional` or `closed`) and, while provisional, `closes_on`.

## Do not assume

- **A total with `complete` false is a floor.** Say the count of unknown lots.
- **Value is not market value or what Xero holds.**
- **A closed month does not move.** A later purchase changes the current value, not the snapshot.
- **A provisional month is not final.** Say it is provisional and when it closes; its CSV says "Provisional — not closed" in its first row. Don't quote it as the closing stock for the accounts.
