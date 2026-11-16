---
topic: "inventory.stocktakes"
title: "Stocktakes"
domain: "inventory"
summary: "A stocktake counts finished and in-progress stock, and every difference must be resolved with a reason that becomes an ordinary stock record."
related_topics:
  - inventory.sites_and_locations
  - inventory.holds
  - compliance.excise_position
related_operations:
  - stocktake_get_stocktake_reconciliation
  - stocktake_get_stock_position
features: []
---
# Stocktakes

## What it means

A stocktake counts reality against what Biz-E holds. It covers **finished and in-progress lots with quantity above zero**, optionally at one location. Raw material is not counted. Customs requires at least an annual stocktake of a licensed area, and Biz-E schedules counts monthly, quarterly, six-monthly or annually. A stocktake is `scheduled` or a `customs_visit`.

Each lot is a line. The **expected** quantity is taken when the line is counted, not when the stocktake starts, so a sale made during the count does not show up as a difference.

A line is `matched` when the count is within tolerance: zero for counted goods, and for measured bulk a percentage (default 0.5%). Otherwise it is `open` until resolved. A line can be `investigating`, which holds it open (default 14 days) with no stock change.

## How the records relate

Resolving a line applies a reason that becomes an ordinary, dated stock operation, so the excise figures follow without any extra step.

- **Short:** found elsewhere (stock is moved to where it is), removed without a record (a tasting, sample, gift or missed sale, moved to a system place outside the licensed area so it is a dutiable removal), broken (recorded as wastage and flagged for a remission claim), still investigating, or unexplained loss (moved to a system place outside the licensed area, so it is dutiable and flagged to tell Customs).
- **Over:** returned, a recorded removal that did not happen, production that was under-recorded, or an unexplained gain (added back and flagged for review).

The reconciliation is per product since the last completed stocktake: opening count, plus produced and other additions, less removals and losses, equals expected. Where a compliance module tracks regulated flows, it covers the controlled area only.

## Authoritative operations

`stocktake_get_stocktake_reconciliation` returns that equation for one stocktake. It takes a stocktake id, and no assistant operation lists stocktakes, so ask the person which count they mean. For what is held now and where, use `stocktake_get_stock_position`.

## Do not assume

- **A difference is not a loss until it is resolved.** An open or investigating line has changed no stock.
- **A surplus is not automatically good news.** Customs' published guidance does not cover surpluses, and Biz-E marks a gain for review rather than treating it as settled.
- **Unexplained loss is dutiable.** Do not describe it as a write-off.
- **A held lot is still counted.** A hold does not remove a lot from a stocktake.
- **The count is not the stock position.** The position is what Biz-E holds now. A count is what a person found.
