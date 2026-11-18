---
topic: "planning.stock_cover"
title: "Stock cover"
domain: "planning"
summary: "Stock cover says how fast each product sells, when it runs out, and what to make, using the planner's own rules for what counts as stock."
related_topics:
  - inventory.availability
  - planning.planned_batches
  - sales.xero_invoices
related_operations:
  - planning_get_stock_cover
features: []
---
# Stock cover

## What it means

For each product (a workflow output) that sells or has a cover target, stock cover gives:

- **Rate**: units sold per week over a window (default 12 weeks, 4 to 52), from connected sales. A sale counts for an output only through its product mapping.
- **Seasonality**: with at least 12 months of sales, coming weeks are scaled by last year's pattern (clamped to a quarter to four times). With less history there is no adjustment, and the row says so.
- **Available**: stock on hand plus the output of live planned batches, less open demand that is not itself a forecast.
- **Runs out on**: today plus available divided by the daily rate.
- **Suggestion**: only with a stock target. Enough to keep the target weeks of cover, in whole batches.

## How the records relate

- Stock on hand here means lots of exactly that output, at the planning site, with the same owner, not expired, not on hold or flagged on hold, quarantined or in transit, less quantity recorded as an input on unfinished steps.
- Each row carries a ready-made `sentence`.

## Authoritative operations

`planning_get_stock_cover` (`weeks`, `site_id`).

## Do not assume

- **Ready dates are not applied.** In-stock lots count as ready today, so a lot still resting can be counted. Check inventory.ready_dates.
- **Unknown stays unknown.** A product with no sales source, mapping or batch size has a stated reason, not a guess. Use the `sentence` and `unknowns`.
- **It reserves nothing and starts nothing.**
- **Contract-customer demand is not met from the producer's stock.**
