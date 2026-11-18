---
topic: "production.inputs_and_outputs"
title: "Inputs and outputs"
domain: "production"
summary: "Steps declare inputs and outputs; completing a step records the actual ones, takes lots out of stock and creates new lots."
related_topics:
  - production.steps
  - production.intermediates
  - inventory.units_and_packs
  - inventory.availability
  - traceability.back
related_operations:
  - core_get_execution
  - core_get_process
features: []
---
# Inputs and outputs

## What it means

A workflow step **declares** inputs (a name, a quantity, a unit) and outputs. When a person completes the step in a batch, they record the **actual** inputs and outputs. Declared figures are the usual ones. Actuals are what happened.

Each actual input names a lot (`inventory_item_id`), a quantity and a unit. Each actual output becomes a new lot.

## How the records relate

**Inputs.** Biz-E converts each input to the lot's own unit and refuses to take more than is on hand. The lot's quantity falls when the step completes, not when the input is first recorded. A step is refused if a lot is on quality hold, or if it is not yet ready (unless the person confirms).

**Outputs.** Each output with a quantity above zero becomes a lot:

- a `work_in_progress` lot if the step is not the last, or the output is marked "sample only";
- a `final_product` lot if the step is the last.

An output with zero or an unreadable quantity is skipped, with a warning kept on the step. Counted outputs such as bottles must be whole numbers, and a remainder can be recorded as remainder stock in mL. An output can be reconciled into an existing untracked lot (inventory.untracked_items).

An output lot is linked to its step and to the output definition that made it (`source_output_id`). The step's actual inputs on that record are what a trace follows (traceability.back).

## Authoritative operations

- `core_get_execution`: the actual inputs and outputs of every step of one batch.
- `core_get_process`: the declared inputs and outputs of a workflow.

## Do not assume

- **A declared input is not a consumed input.** Only completed steps have consumed anything.
- **An input recorded on an unfinished step is still on hand.** Planning treats it as spoken for, but the lot's quantity has not changed.
- **Outputs are not linked to inputs one for one.** Every output of a step is linked to every input lot of that step. There is no share of an input in an output. Do not say how much of one lot is in one bottle.
- **Output quantity is not sold quantity.** It is stock created.
- **An output's name is not its identity.** The output definition's id is.
