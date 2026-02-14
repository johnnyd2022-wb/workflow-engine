# Step 1: In-Flow Recording of Missing Inventory Items (Updated)

## Goal
Allow operators to record missing inventory items directly during execution without blocking workflow. The system should remain accurate and auditable, and the new item should appear in the correct inventory category.

## Tables
Relevant tables:

### 1. `steps`
- `id`, `process_id`, `name`  
- `inputs`: JSON array of expected inputs  
- `outputs`: JSON array of expected outputs  
- `execution_prompts`: additional prompts (batch number, etc.)

### 2. `inventory_items`
- `id`, `name`, `unit`, `quantity`  
- `inventory_type` (`raw_material` / `work_in_progress` / `final_product`)  
- `source_execution_step_id` / `source_output_id`

### 3. `execution_steps`
- `id`, `execution_id`, `step_id`  
- `actual_inputs`, `actual_outputs`  

---

## Requirements

1. **Trigger**
   - Inline “Add Missing Item” button on the step execution modal.
   - Only visible when execution step detects missing inventory:
     ⚠️ *No matching inventory items found. Please add inventory before executing this step.*

2. **UI Behavior**

   **Raw Material Inputs**  
   - If missing item is a **raw material** (from `steps.inputs`):  
     - Open the **existing “Add Inventory Item” modal** from `+ Add to Inventory` on `core2.html`.  
     - Let operator fill in supplier, quantity, unit, date, etc.  
     - Upon saving, the item is added to `inventory_items` in `raw_material` inventory_type.

   **Missing Output Items**  
   - If missing item is an **expected output** (from `steps.outputs`):  
     - Open a **new lightweight modal**:
       - Prefill **Name**, **Quantity**, **Unit** from the step definition (`steps.outputs`).  
       - Allow operator to edit these fields.  
       - Include **Date** (default = today).  
     - Upon saving, insert into `inventory_items` in the appropriate inventory_type (intermediate or final).  
     - Flag item as **untracked/unreconciled**.

3. **Inventory Insert**
   - Store missing item in `inventory_items`:
     - Set `source_execution_step_id` = current `execution_steps.id`  
     - Set `source_output_id` = relevant `steps.outputs.id` (if output)  
     - Ensure audit fields: created_by, timestamp, step, process  

4. **System Behavior**
   - Execution continues **without blocking**.  
   - Newly added items appear in the correct inventory category.  
   - Untracked items are **highlighted in banners or sourcemaps** for reconciliation.

---

## Constraints
- Reuse existing functions to store inventory items wherever possible.  
- Do not create unnecessary duplication of items.  
- Maintain auditability (user, timestamp, step, process).  
- UI must be lightweight and simple; focus on minimal friction.  

---

## Deliverables for Cursor
- Code that:
  1. Detects missing items for the execution step.  
  2. Opens the correct modal:
     - **Raw inputs** → existing “Add Inventory Item” modal.  
     - **Missing outputs** → lightweight modal prefilled from step definition.  
  3. Saves item into `inventory_items` with correct inventory_type.  
  4. Flags item as untracked/unreconciled.  
  5. Allows execution to continue without blocking.  
- Include table/field comments and keep implementation minimal.