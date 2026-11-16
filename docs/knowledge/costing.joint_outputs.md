---
topic: "costing.joint_outputs"
title: "Joint outputs and cost splitting"
domain: "costing"
summary: "A batch's cost is pooled and handed to the outputs of each step by configured share, else by quantity, so losses are absorbed."
related_topics:
  - costing.cost_status
  - production.inputs_and_outputs
  - costing.overheads
related_operations:
  - costing_get_execution_cost
  - costing_margins_report
features:
  - costing
---
# Joint outputs and cost splitting

## What it means

Cost is pooled per batch and passed to output lots step by step. When a step makes several outputs, the pool is split:

1. An output definition can set a `cost_share`: a percentage, or `byproduct`, which takes none.
2. Outputs without a share split the rest by quantity when their units are compatible. If not, all of it goes to the primary output and the split is flagged as assumed.
3. Remainder stock of counted products takes no share.
4. An opt-in setting splits by litres of finished product instead.

The primary output prefers final product, then work in progress, then raw material, then the largest quantity.

## How the records relate

- Normal losses are absorbed, because the whole pool is spread over what actually came out.
- Cost consumed after a batch's last output stays as cost so far while it runs, and is a production loss once the batch is complete.

## Authoritative operations

- `costing_get_execution_cost`: the batch's pool, per-output costs and whether the split was assumed.
- `costing_margins_report`: margin using the lots' resulting unit costs.

## Do not assume

- **Equal quantity is not equal cost.** Shares and by-products change it.
- **A split flagged as assumed is a default.** Say so.
- **Cost per bottle depends on yield.** A smaller output raises it.
