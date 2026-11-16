---
topic: "costing.overheads"
title: "Overheads in cost (opt-in)"
domain: "costing"
summary: "Off by default. When an organisation turns it on, batches carry typed overhead rates and freight, shown apart from materials."
related_topics:
  - costing.cost_status
  - costing.joint_outputs
  - costing.readiness
related_operations:
  - costing_get_execution_cost
features:
  - costing
---
# Overheads in cost (opt-in)

## What it means

By default cost is materials only. An organisation can opt in to a fuller cost. Then:

- **Overhead rates** are typed: a name (such as rent, labour or power), an amount, a basis (per litre of finished product, or per batch) and an effective-from date. A batch completed on or after that date takes the rate.
- **Freight** on a purchase is spread by value over the stock the same purchase paid for.
- Costs show materials and overheads apart.

## How the records relate

- Only a **completed** batch that makes finished product takes overheads, in its last step that makes final product. A running batch has none yet.
- The overhead splits between outputs by the same shares as materials (costing.joint_outputs).
- Overheads never decide whether a product is cost-ready.

## Authoritative operations

`costing_get_execution_cost` shows a batch's materials and overheads split when the setting is on.

## Do not assume

- **If the setting is off, there are no overheads.** Do not estimate them.
- **A rate of $0 ends a rate** from its date.
- **A running batch's overhead is not missing.** It is added on completion.
- **Overheads are not posted to Xero.**
