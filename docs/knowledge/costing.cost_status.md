---
topic: "costing.cost_status"
title: "Cost and its status"
domain: "costing"
summary: "Every cost carries a status: actual, estimated, partial or unknown. A cost is complete or says what is missing, and unknown is never zero."
aliases:
  - "pay"
  - "cost per kilogram"
related_topics:
  - costing.readiness
  - costing.last_known_price
  - costing.joint_outputs
  - costing.stock_value
  - sales.fifo_matching
related_operations:
  - costing_get_execution_cost
  - costing_get_lot_cost
  - costing_get_stock_value
  - costing_margins_report
  - costing_readiness_list
features:
  - costing
---
# Cost and its status

## What it means

Biz-E costs each lot by tracing it back through production to purchase prices. Costs are **computed when read**, never stored, so a late price or a changed setting shows on the next read.

Each cost has a `status`, worst last:

- `actual`: every input has its own recorded price (a purchase, or a typed price, including a free lot at zero).
- `estimated`: some input took the last known price of the same material (costing.last_known_price).
- `partial`: some inputs have no cost. The figure is a floor.
- `unknown`: nothing costs it.

`unit_cost` is filled only for `actual` and `estimated`. For `partial` it is null and `known_unit_cost` holds the floor. A cost also lists `missing` lots and `warnings`.

## How the records relate

- A batch's inputs are valued at each lot's unit cost and pooled. The pool is handed to the lots the step makes (costing.joint_outputs). The status of an output is the worst status of what went in.
- Customer-owned material is zero cost.
- Excise duty is not in lot cost. It is added per sale in margins, from the excise module.
- Cost works with no Xero connection, from typed prices.

## Authoritative operations

- `costing_get_lot_cost`: one lot.
- `costing_get_execution_cost`: one batch, including cost so far while it runs.
- `costing_readiness_list`: which products can be costed yet.
- `costing_get_stock_value`: stock value with its split by status.
- `costing_margins_report`: margin per product per month with cost status.

## Do not assume

- **Unknown is not zero.** Never show a missing cost as $0, and never present a `partial` floor as the cost.
- **A cost can change after the fact.** A purchase recorded late changes past batches' costs.
- **Do your own division only on an actual or estimated figure.** Use the app's per-unit values.
- **Cost is production cost.** Do not call it margin, price or duty-inclusive.
