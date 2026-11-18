---
topic: "production.intermediates"
title: "Intermediates (work in progress)"
domain: "production"
summary: "An intermediate is a real lot made by a step that is not the last. It has quantity, cost and lineage but is not finished stock."
related_topics:
  - production.inputs_and_outputs
  - production.batches
  - inventory.lots
  - costing.stock_value
related_operations:
  - core_get_execution
  - core_list_inventory
features: []
---
# Intermediates (work in progress)

## What it means

An **intermediate** is a lot made by a step that is not the last step of its workflow. Its `inventory_type` is `work_in_progress`. Examples are a base, a blend or a rested batch waiting for the next stage. The last step's outputs are `final_product`.

## How the records relate

- An intermediate is a real lot. It has a quantity and unit, and can have a ready date, an expiry, a hold, a cost and a site. It can be used as an input to a later step of the same batch or of another batch.
- A step output marked "sample only" is always work in progress, even from the last step, so a sample cannot be mistaken for finished stock.
- The stock position shows intermediates as "In progress". Stocktakes count them. Stock value reports them as work in progress, and reports the unabsorbed cost of a batch that is still running separately as "in production".
- A trace follows intermediates like any other lot, so a final product traces back through them to its raw materials.

## Authoritative operations

- `core_get_execution`: which lots each step of a batch produced.
- `core_list_inventory` with `type=work_in_progress`: intermediates currently on hand, with their holds, ready dates and findings.

## Do not assume

- **An intermediate is not for sale.** Sales matching uses final products only. Do not count intermediates as finished stock.
- **An intermediate that is gone is still in the trail.** Its lot stays with quantity zero, and traces include it.
- **A batch "in production" is not an intermediate.** Money still held in a running batch is not a lot. Only lots made by completed steps exist.
- **Intermediates can be spent by another batch.** Do not assume one batch's intermediate ends up in that batch's final product.
