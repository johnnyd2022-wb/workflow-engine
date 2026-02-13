1. In-Flow Recording of Missing Items
Goal

Allow operators to record items during execution that do not exist in inventory yet, without blocking the workflow, while keeping the system trustworthy and accurate.

Key Points

Operators can enter missing items directly during execution. Executions are defined in flows2.html

Operators should be prompted to add raw material from supplier or missing output items

For raw material from supplier we should bring up the "Add Inventory Item" modal we load from the + Add to Inventory button on core2.html. 

For missing output items we should prompt for Required fields:

Process  - drop down selection (default to current process where execution is happening)
step - drop down selection
Item Name, quantity & unit should prefill with saved output definition from the process step data for confirmation (able to be changed by the operator)
date

The system should then add the untracked item to inventory in relevant area e.g raw material from supplier goes in raw materials column, missing output items go into relevant intermediate or final products column and show in process specific inventory

UI Considerations

Inline “Add Missing Item” button on step execution modal or grid. This should show up when the system currently flag the existing check in the modal that shows "⚠️ No matching inventory items found. Please add inventory before executing this step." 

Source selection:

Dropdown or typeahead for existing steps/process outputs.

If linking to a different process or step:

Show clean contextual link: [Process Name → Step Name]

Clicking opens a small modal or flyout with details for confirmation. Note we should not show execution ids or metadata since this is not taking from existing stock but creating a backlog item that is untracked and will be reconciled

System Behavior

Upon entry, the item is flagged as untracked/unreconciled.

Banner notifications or sourcemap highlights indicate items requiring reconciliation.

System ensures execution can proceed without blocking due to missing items.

2. System Checks

Follow the approach we have for expired_materials.py - leverage corechecks.py & dagtraversal.py to achieve a solid system check

After recording a missing item, the system performs checks in three areas:

Banner Alerts - copy existing banner alerts

Display unresolved untracked items across the system to all relevant operators.

Sourcemap

Track items that have no upstream source. Show this as a "Check needed" item in sourcemap like we do for expired materials with the reason e.g untracked inventory item, reconsiliation required

Highlight any discrepancies between execution inputs and inventory outputs.

Execution Flow Validation

Ensure downstream steps referencing this item can proceed.

Prevent negative stock or unbalanced quantities from propagating.

3. Reconciliation Concepts
Reconciliation Goals

Transform untracked items into recognized inventory stock.

Reduce friction while maintaining system accuracy and auditability.

Two Reconciliation Paths

Add to Inventory button on core2.html

For items that do not correspond to prior executions, but exist physically.

Operator enters actual quantity, date, and category.

Positive quantities that offset previously untracked balances are stored in live inventory as usable stock.

Untracked balance is decreased accordingly.

When user adds item using this approach there should be an option in the modal to map to untracked item if the system has detected untracked items with a drop down selection

Perform Execution

For items that should have been produced by a previous step:

System prompts to map untracked item to execution output.

Requires:

Selection of relevant process and step (with contextual link)

Enter quantity produced if different from untracked quantity

After mapping, execution reconciles the item without creating new stock, preventing double-counting.

4. Inventory Balancing Rules

Positive balance:

Any quantity recorded that offsets an untracked balance but exceeds it becomes usable stock in inventory.

Untracked balance:

Maintained until reconciled via inventory addition or execution mapping.

Audit trail:

All untracked items and reconciliations are timestamped, user-stamped, and linked to relevant process/step.

5. UX / UI Principles

Minimal friction:

Operators should not be blocked from continuing execution due to missing items.

Clear visibility:

Banner and sourcemap highlights show unresolved untracked items.

Contextual linking:

For mapping to other executions, always provide a clear, clickable reference.

Feedback:

On reconciliation, immediately update live inventory and remove banners for resolved items.

If you have questions just ask

Tackle this step by step and we will work on each step individually so only tackle 1 step then ask me if we can progress to next step