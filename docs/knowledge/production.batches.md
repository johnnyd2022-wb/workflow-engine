---
topic: "production.batches"
title: "Batches (executions)"
domain: "production"
summary: "A batch is one run of a workflow and the record of what was actually used and made. A planned batch is only a plan."
related_topics:
  - production.workflows
  - production.steps
  - production.inputs_and_outputs
  - planning.planned_batches
  - traceability.forward
  - costing.cost_status
related_operations:
  - core_get_execution
  - core_list_executions
  - planning_get_planning_batches
features: []
---
# Batches (executions)

## What it means

A **batch** is one run of a workflow. The API calls it an **execution**. It has a status (`pending`, `in_progress`, `completed`, `failed` or `cancelled`), start and completion times, a site, and one record per step. It is the record of what happened: which lots each step really used, and which lots it really made. When every step is completed the batch is completed.

## How the records relate

- A batch belongs to one workflow. Its steps are copied from the workflow when it starts.
- Each completed step lists its actual inputs (lots and quantities taken) and actual outputs. Each output becomes a lot, which points back at the batch (`source_execution_id`).
- A batch in progress has already made lots. Outputs of its early steps exist as work in progress while later steps are still to run. See production.intermediates.
- **Three different things are called a batch number.** Do not mix them up:
  - the answer to a step's reserved "Batch number" prompt, which a trace shows as `batch_id`;
  - the supplier's own code on a bought-in lot, `supplier_batch_number`;
  - a **label batch number** (`extra_data.batch_number`), a number a step output can carry, for example for a physical run of pre-printed labels. Several outputs can share one. It decides which lot is used first when a sale is matched. See sales.fifo_matching.
- A **planned batch** is a plan made by the planner, not a record of production. Starting a plan creates a real batch. See planning.planned_batches.

## Authoritative operations

- `core_list_executions`: batches newest first, with status, progress, current step and the steps already recorded. Filter by workflow or status. With `count=1` only the total is returned.
- `core_get_execution`: one batch with every step, the actual inputs and outputs, and attached evidence.
- `planning_get_planning_batches`: planned batches in a date range. These are plans.

For what a batch cost, use the batch cost operation (costing.cost_status). To see where its outputs went, trace an output lot (traceability.forward).

## Do not assume

- **A planned batch is not a batch that happened.** Only a started plan has a real batch behind it.
- **An in-progress batch has made nothing final.** Its outputs so far are work in progress, and the inputs recorded on an unfinished step have not left stock.
- **A completed batch is not necessarily all finished goods.** Outputs of earlier steps are intermediates.
- **A batch has no quantity of its own.** Read its output lots and their units.
- **Status `completed` is about steps, not about quality.** Quality holds are recorded on lots (inventory.holds).
