---
topic: "costing.stock_value"
title: "Stock value and snapshots"
domain: "costing"
summary: "Stock value is quantity times cost per lot plus the pool of running batches. Month-end snapshots freeze a closed month."
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

A **snapshot** freezes the value at a cutoff. Month-end snapshots are taken automatically after a month ends, and held fixed. Quantities are as at the cutoff, and later changes show only as changes since close.

## How the records relate

- A lot with no cost is listed with no value and counted in `unknown_lots`. A partly costed lot carries its floor.
- When snapshots exist, the movements between two of them explain the change in value (purchases, sales, wastage, samples and so on) and sum exactly (costing.xero_bridge).
- A finished batch's leftover pool is a production loss, not stock.

## Authoritative operations

`costing_get_stock_value`: the current value, its split, `complete`, and the count of lots with no cost. Snapshots and the CSV closing stock are separate app operations.

## Do not assume

- **A total with `complete` false is a floor.** Say the count of unknown lots.
- **Value is not market value or what Xero holds.**
- **A closed month does not move.** A later purchase changes the current value, not the snapshot.
