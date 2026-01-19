Cursor Prompt: Implement Variable Inputs, Variable Outputs, and Execution Prompts with Clear Mental Models

You are extending an existing Flask + SQLAlchemy platform that models manufacturing processes as ordered steps (DAG-like), with inventory already implemented for supplier-provided raw materials (including supplier, batch number, quantity, unit, expiry, etc).

Your goal is to cleanly separate and implement three distinct concepts in both backend and frontend:

Variable Inputs (inventory-driven)

Variable Outputs (execution-confirmed results)

Execution Prompts (metadata captured at run time, not inventory)

This separation is critical for UX clarity, regulatory traceability, and future scalability.

1. Core Mental Models (DO NOT BLUR THESE)
A. Variable Inputs = Inventory Selection at Execution

Variable inputs do not mean “free-form values”

They mean: “At execution time, the user must select which inventory item(s) are consumed”

Inventory already exists and is the source of truth

Execution consumes inventory and creates a traceable edge

Key rule

Users must never type supplier batch numbers for inputs

Batch numbers come only from inventory selection

B. Variable Outputs = Confirm or Override Actual Produced Quantity

Variable outputs represent expected outputs defined at design time

At execution, users:

Confirm the expected quantity

OR override with actual produced quantity

Outputs create new inventory records (WIP or final product)

Outputs may later be selected as inputs in downstream steps

Key rule

Outputs are not inventory selection

Outputs are inventory creation

C. Execution Prompts = Metadata, Not Inventory

Execution prompts capture execution-specific metadata:

Batch numbers

Run IDs

Temperatures

Operator notes

These prompts:

Do not affect inventory directly

Are stored against the execution record

Are fully auditable

Key rule

Execution prompts must never be confused with inputs or outputs

They exist solely to record compliance and context

2. Backend Requirements
Step Definition Model

Extend step definitions to clearly support:

inputs[]

name

expected_quantity

unit

requires_inventory_selection (boolean)

outputs[]

name

expected_quantity

unit

requires_execution_confirmation (boolean)

execution_prompts[]

label

type (text, number, date, select)

unit (optional)

required (boolean)

These can be stored in JSONB if already used.

Execution Model

When a step is executed, persist:

For variable inputs:

execution_input_records:

execution_id

step_id

inventory_item_id

quantity_consumed

unit

This creates a traceable consumption edge.

For variable outputs:

execution_output_records:

execution_id

step_id

output_definition_id

actual_quantity

unit

inventory_item_id (newly created)

Outputs must create new inventory rows.

For execution prompts:

execution_metadata:

execution_id

key

value

unit (optional)

Graph Integrity

Inputs reference existing inventory

Outputs generate new inventory

Executions connect the two

This allows full source-to-sale traversal later

3. Frontend UX Requirements (CRITICAL)
Step Builder UI (Design Time)
Inputs section

Rename “Variable” → “Select inventory at execution”

Tooltip:

You will choose which supplier batch is consumed when this step runs.

Do NOT ask for batch numbers here.

Outputs section

Rename “Variable” → “Confirm at execution”

Tooltip:

You will confirm or override the actual quantity produced when this step runs.

New Section: Execution Prompts

Add a third section per step:

“Execution prompts (recorded when step runs)”

User defines:

Label (e.g. “Botanical batch number”)

Field type

Unit (optional)

Required / optional

No default value required

This section must be visually distinct from inputs/outputs.

Step Execution Modal (Run Time)

When user clicks Execute Step:

1. Inventory Selection (Variable Inputs)

For each variable input:

Show expected quantity

Provide inventory selector filtered by material name

Show supplier + batch + available quantity

Allow partial consumption

Prevent over-consumption

2. Execution Prompts

Render defined prompts as form fields

Required fields must block execution if missing

3. Output Confirmation

For each variable output:

Show expected quantity

Pre-fill with expected value

Allow override

Clearly label as “Actual produced”

4. Guardrails to Prevent User Confusion

Never allow free-text batch entry for inputs

Never allow inventory selection for outputs

Never auto-convert execution prompt values into inventory data

Use explicit copy everywhere:

“Select inventory”

“Confirm output”

“Record metadata”

5. Acceptance Criteria

The system must allow:

Full supplier batch traceability from raw material → intermediate → final product

Multiple executions of the same process using different inventory

Accurate reconciliation of consumed vs produced quantities

Clean UX that matches real-world manufacturing mental models

6. Non-Goals (Do Not Implement Now)

FIFO/FEFO optimisation

Automatic yield variance alerts

Recall reporting UI

These should be enabled by the data model but not implemented yet.