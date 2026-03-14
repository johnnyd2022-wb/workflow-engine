Reconciliation for Untracked Inventory Items
Objective

Convert untracked inventory items (created during in-flow recording) into properly reconciled stock while:

Preventing double-counting

Preserving audit integrity

Maintaining accurate live inventory balances

Minimizing operator friction

Untracked items represent a temporary imbalance between execution inputs and recorded inventory.

Definitions

Untracked Item
Inventory entry created during execution that lacks a confirmed upstream source.

Reconciled Item
An untracked item that has been resolved via:

Inventory addition

Execution mapping

Live Inventory
Usable stock available for allocation in future executions.

Reconciliation Paths

There are exactly two reconciliation mechanisms.

Path A — Add to Inventory (Physical Stock Exists)
Use Case

The item physically exists but was never recorded in inventory.

Entry Point

+ Add to Inventory button in core2.html

Required Behavior

When opening the modal:

System checks for matching untracked items (same name + unit + process scope).

If matches exist:

Show dropdown: "Map to Untracked Item"

Selection is optional but strongly encouraged.

Operator enters:

Quantity

Unit

Date

Category (raw, intermediate, final)

System Logic:

If mapping selected:

reconciliation_amount = min(added_quantity, untracked_balance)


Reduce untracked balance by reconciliation_amount

Increase live inventory by added_quantity

If added_quantity > untracked_balance:

Surplus becomes positive usable stock

If no mapping selected:

Treat as standard inventory addition

Do not affect untracked balances

Required Constraints

Never auto-map silently.

Never delete untracked records.

Always maintain audit linkage.

Path B — Perform Execution (Production Event Occurred)
Use Case

Item should have been produced by a prior process step but execution was not recorded.

Required Flow

System detects untracked item with missing upstream source.

Prompt user:

“Map to Execution Output?”

Operator selects:

Process (dropdown)

Step (dropdown)

Quantity produced

Date

System creates execution record.

System Logic:

reconciliation_amount = min(execution_output_quantity, untracked_balance)


Reduce untracked balance by reconciliation_amount

Do NOT increase live inventory separately

Execution output becomes the inventory source

Prevent duplicate stock creation

If execution quantity exceeds untracked balance:

Surplus becomes positive live inventory

Inventory Balancing Rules
Rule 1 — Positive Balance Handling

Any quantity exceeding the untracked balance becomes:

Positive live inventory

Fully usable stock

Available for future executions

Rule 2 — Untracked Balance Persistence

Untracked balances remain until:

Fully reconciled

Explicitly addressed by either path

System must not auto-clear them.

Rule 3 — No Double Counting

Reconciliation must ensure:

No inventory quantity is counted twice

Execution output mapping does not duplicate stock

Audit & Traceability Requirements

Each reconciliation must record:

Timestamp

User ID

Reconciliation method (Add vs Execution)

Linked process and step (if applicable)

Quantity reconciled

Surplus created (if any)

Untracked item record must maintain:

Original creation source (execution + step)

Remaining balance

Reconciliation history

System Checks After Reconciliation

After any reconciliation:

Recalculate inventory balances.

Remove banner alerts if balance = 0.

Update sourcemap status:

Remove “Check Needed” flag if resolved.

Validate downstream execution integrity.

UX Requirements

Show current untracked balance clearly.

Show how much will be reconciled before confirmation.

Display resulting live inventory impact.

Provide immediate visual confirmation upon success.

Remove banners automatically when fully reconciled.

Edge Cases

Partial reconciliation allowed.

Multiple untracked items for same name must remain distinct.

Unit mismatch must block reconciliation.

Cross-process mapping allowed but must be explicit.

Implementation Guardrails

No automatic reconciliation.

No hidden quantity adjustments.

No deletion of untracked records.

All actions reversible via audit trail.

RULES
DO NOT UPDATE/EDIT EXISTING CODE

Reconciliation functions must be new code only - if you recommend changing existing code I need a good reason why

Any new code should be in its own file and imported wherever it makes sense 