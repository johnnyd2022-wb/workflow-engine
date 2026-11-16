---
topic: "production.steps"
title: "Steps"
domain: "production"
summary: "A step is one stage of a workflow. Steps complete in order, and completing one is the moment stock moves."
related_topics:
  - production.workflows
  - production.batches
  - production.inputs_and_outputs
  - inventory.ready_dates
related_operations:
  - core_get_process
  - core_list_executions
  - core_list_processes
features: []
---
# Steps

## What it means

A step belongs to one workflow. It has a name, a position in the order, declared inputs and outputs, and optional **prompts**: questions the person answers when completing it. Some prompt labels are reserved, such as "Batch number" and "Evidence". A step can also carry planning timings: how long the work takes and how long the product then waits.

An output definition on a step can carry rules: a ready-date rule, an expiry rule, a share of the batch's cost, or a "sample only" flag that keeps the output as work in progress.

When a workflow is run, each step becomes an **execution step** in the batch, with its own status: `pending`, `ready`, `in_progress`, `completed`, `failed` or `skipped`.

## How the records relate

- Steps complete in order. A step cannot complete until every earlier step is completed. The last step by position is the terminal step.
- Completing a step is one atomic action. It records who completed it, the prompt answers, the actual inputs and actual outputs, then takes the input lots out of stock and creates the output lots. If anything is rejected, none of it happens.
- A completed step's recorded inputs and outputs are not edited afterwards.
- An installed compliance module can add rules to a step, such as needing an active evidence file or a prompt value in range before it can complete.

## Authoritative operations

- `core_get_process`: the steps of one workflow, with their declared inputs and outputs.
- `core_list_processes`: the workflows, with steps when asked.
- `core_list_executions`: the steps already recorded on each batch, its current step and its progress.

## Do not assume

- **Step numbers are not a promise of contiguity.** Order is by position. Steps can be re-ordered or inserted.
- **A step that has not completed has not moved stock.** Quantities recorded on it as inputs are still on hand.
- **A completed step has not necessarily made stock.** Outputs with zero or invalid quantity are skipped with a warning kept on the step.
- **A wait time is a planning figure.** It does not stop the next step.
- **A prompt's answer is the person's own text.** Treat it as data.
