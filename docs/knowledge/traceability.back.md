---
topic: "traceability.back"
title: "Tracing back to sources"
domain: "traceability"
summary: "Backward trace walks from a lot to the lots its producing step used, and on to suppliers, using recorded step inputs."
related_topics:
  - traceability.forward
  - traceability.to_sale
  - production.inputs_and_outputs
  - inventory.untracked_items
related_operations:
  - core_trace_inventory_backward
  - core_trace_inventory_to_sale_graph
features: []
---
# Tracing back to sources

## What it means

A backward trace starts at any lot (raw, in progress or finished) and answers "what went into this". It looks at the step that made the lot, takes the lots recorded as that step's actual inputs, then repeats for each of those until it reaches lots with no producing step, such as bought-in stock.

## How the records relate

- The trail is the recorded link between a made lot (`source_execution_step_id`) and the step's `actual_inputs`. It is not worked out from names or quantities.
- Zero-quantity lots are included, so fully used intermediates still appear.
- The response has the traced lot, its `raw_materials`, `intermediates`, all items, the `connections` between them, and `trace_steps` (each upstream operation once).
- A lot added by hand, or an untracked lot, has no producing step, so the trace ends there.

## Authoritative operations

- `core_trace_inventory_backward`: the sources of one lot.
- `core_trace_inventory_to_sale_graph`: the same lot traced both ways, with sales added (see traceability.to_sale).

## Do not assume

- **A step's inputs are linked to all of its outputs.** If a step used lots A and B and made lots X and Y, the trace links both A and B to both X and Y. It does not say how much of A is in X.
- **The trace ends at what was recorded.** An unrecorded or hand-added lot is a dead end, not proof of no earlier history.
- **Supplier information is on the source lots** (`supplier`, `supplier_batch_number`), not on the traced lot.
- **A missing lot id is "not found".** It may belong to another organisation or not exist.
