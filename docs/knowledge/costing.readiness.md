---
topic: "costing.readiness"
title: "Cost readiness"
domain: "costing"
summary: "A product is cost-ready when every material it needs has a cost. Readiness is about materials, not about when a lot is usable."
related_topics:
  - costing.cost_status
  - costing.last_known_price
  - inventory.ready_dates
related_operations:
  - costing_readiness_detail
  - costing_readiness_list
features:
  - costing
---
# Cost readiness

## What it means

Readiness answers "can this product's cost be worked out yet". A product is a workflow output, or for older finished lots a name. Its materials come from its latest batch, walked back through earlier batches, or, with no batch yet, from its workflow's declared inputs.

A material is **costed** when the lot actually used has status `actual` or `estimated`. A product is **ready** when it has materials and all are costed. A ready product also shows its cost per unit from the latest batch.

## How the records relate

- A material with no price of its own can be costed by the last known price (costing.last_known_price).
- Overheads never make a product not ready (costing.overheads).
- Margins are shown only where cost is complete.

## Authoritative operations

- `costing_readiness_list`: every product with `ready`, materials costed out of total, and unit cost.
- `costing_readiness_detail`: one product, with each material and whether it is costed. The key is `output:<id>` or `name:<name>`.

## Do not assume

- **Not ready does not mean no cost.** Some materials may be costed, so say how many.
- **Cost readiness is not a ready date.** A lot's usability is in inventory.ready_dates.
- **A product with no batch is judged from declared inputs.** It is less certain.
