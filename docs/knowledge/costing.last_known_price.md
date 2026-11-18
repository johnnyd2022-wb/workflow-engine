---
topic: "costing.last_known_price"
title: "Last known price"
domain: "costing"
summary: "A lot with no price of its own can take the price of the same material bought on or before its date. The result is estimated, never actual."
related_topics:
  - costing.cost_status
  - costing.readiness
related_operations:
  - costing_get_lot_cost
  - costing_readiness_detail
features:
  - costing
---
# Last known price

## What it means

When a lot has no purchase or typed price, Biz-E can use the price of **the same material**: same normalised name (case, spacing and a trailing "library stock" ignored), a compatible unit, and the same pack count and size when a pack is recorded. Equivalent measures such as 700 mL and 0.7 L match. A lot with a known pack does not borrow a price from a lot with no recorded pack. It uses the most recent price dated on or before the lot's date, else the earliest after. The lot's status is `estimated`, and its `source` shows it is an estimate.

It is an organisation setting, on by default. With it off, only actual costs make a cost complete.

## How the records relate

- Only directly priced lots are candidates. Estimates never chain, and a production cost is never used as a material's price.
- Customer-owned lots are not candidates.
- Once each material has been bought once, older stock of it is costed too.

## Authoritative operations

- `costing_get_lot_cost`: a lot's cost, source and the lot its estimate came from.
- `costing_readiness_detail`: whether each material of a product is costed.

## Do not assume

- **An estimate is not what was paid.** Report it as an estimate.
- **Same name, different unit may not match.** Units must be compatible.
- **The setting may be off.** Check the status.
