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

- **Rate**: units sold per week over a window (default 12 weeks, 4 to 52), from connected sales. A sale counts for an output only through its product mapping. A product first sold inside the window is rated over the whole weeks since its first sale (at least 2), not the full window; `rate_weeks` and `rate_note` say so.
- **Seasonality**: with a year of that product's own sales, the rate is scaled by how last year's next N weeks sold against last year's N weeks before them, or as many of those weeks as it was selling in, at least 2 (clamped to a quarter to four times). The rate already sits at this season's level, so only the change ahead is applied. With less history there is no adjustment, and the row says so.
- **Available**: stock on hand plus the output of live batches that are not blocked, less open demand that is not itself a forecast. A blocked batch is not counted: `blocked` gives its quantity and `blocked_note` a sentence.
- **Runs out on**: open orders take stock first (netted the planner's way, by due date), then the daily rate is drawn from what is left, each batch only from its ready date and each lot only until its expiry date. It is the first day nothing is left, even when a later batch would restock it.
- **Suggestion**: only with a stock target. Enough to keep the target weeks of cover after the batch is made, counting only supply ready by then (a blocked batch counts here, because it is already planned and needs unblocking rather than a second batch), in whole batches, planned by the run-out date less the time it takes to make.

ASSUMPTION: a product's first sale is found from up to three years of sales, so one first sold more than three years ago and not since is treated as having enough history.
ASSUMPTION: weeks with no stock still count as weeks with no sales, so a product that was out of stock for part of the window shows a lower rate than its real demand.

## How the records relate

- Stock on hand here means lots of exactly that output, at the planning site, with the same owner, not expired, not on hold or flagged on hold, quarantined or in transit, less quantity recorded as an input on unfinished steps.
- Each row carries a ready-made `sentence`, which ends with the blocked-batch note when there is one.

## Authoritative operations

`planning_get_stock_cover` (`weeks`, `site_id`).

## Do not assume

- **Ready dates are not applied.** In-stock lots count as ready today, so a lot still resting can be counted. Check inventory.ready_dates.
- **Unknown stays unknown.** A product with no sales source, mapping or batch size has a stated reason, not a guess. Use the `sentence` and `unknowns`.
- **It reserves nothing and starts nothing.**
- **Contract-customer demand is not met from the producer's stock.**
