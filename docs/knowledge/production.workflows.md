---
topic: "production.workflows"
title: "Workflows"
domain: "production"
summary: "A workflow is a reusable definition of how something is made: ordered steps with named inputs and outputs. It is not a record of what was made."
related_topics:
  - production.steps
  - production.batches
  - production.inputs_and_outputs
related_operations:
  - core_get_process
  - core_list_processes
features: []
---
# Workflows

## What it means

A workflow is a reusable definition of a production process. The code and the API call it a **process**, and the pages call it a flow. It has a name, a description, an optional category (manufacturing, chemical, packaging, assembly or other), a draft flag, a small settings object and an ordered list of steps. Each step names its inputs and outputs.

Settings are per workflow, for example whether input lots are auto-selected first-in-first-out, and what the remainder stock of counted products is called.

## How the records relate

- A workflow has many steps (production.steps). Running it creates a **batch**, which the API calls an execution (production.batches).
- Every change to a workflow or its steps writes an immutable version snapshot. That is how Biz-E answers "what procedure was being followed when this batch ran".
- A made lot points at the workflow output that made it (`source_output_id`), so a product is identified by its output, not only by its name.
- A workflow cannot be deleted once it has batches, and deleting one needs an admin.
- A draft workflow cannot be used to plan batches.

## Authoritative operations

- `core_list_processes`: the workflows, with step counts and how many batches are active or complete. Add `include_steps` to get the steps.
- `core_get_process`: one workflow with its steps in order, and the inputs and outputs of each.

## Do not assume

- **A workflow is not a record of what was made.** Use the batch operations for that (production.batches).
- **Declared quantities are usual figures, not actuals.** A batch records what was really used and made.
- **A workflow's current definition may differ from the one a past batch followed.** Versions are kept, but the definition read now is the latest.
- **Two workflows can make products with the same name.** The workflow output's id is what keeps them apart.
- **Do not reproduce a workflow's inputs as advice or as a public recipe.** They are the organisation's own data.
