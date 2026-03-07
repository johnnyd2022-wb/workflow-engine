Step-by-Step Implementation Plan
1. Stop Fabricating completed_at Timestamps
Problem

If completed_at is invalid or missing, the code replaces it with the current time:

completed_dt = _normalize_dt(completed_at) or datetime.now(timezone.utc)

This hides data corruption and produces incorrect expiry calculations.

Fix

Replace this logic with a skip.

Change

Locate:

completed_dt = _normalize_dt(completed_at) or datetime.now(timezone.utc)

Replace with:

completed_dt = _normalize_dt(completed_at)
if not completed_dt:
    continue
2. Normalize Output Unit Comparison
Problem

InventoryItem.unit is trimmed in SQL but the step definition value is not.

Fix

Ensure the configuration value is trimmed before comparison.

Change

Locate the unit comparison query:

func.trim(InventoryItem.unit) == out_unit

Replace with:

func.trim(InventoryItem.unit) == out_unit.strip()
3. Remove Unnecessary UUID String Conversions
Problem

seen_item_ids stores string versions of UUIDs which creates unnecessary allocations.

Fix

Store UUIDs directly.

Change

Locate:

seen_item_ids: set[str] = set()

Replace with:

seen_item_ids: set[UUID] = set()

Locate:

item_id_str = str(item.id)

if item_id_str in seen_item_ids:
    continue

seen_item_ids.add(item_id_str)

Replace with:

item_id = item.id

if item_id in seen_item_ids:
    continue

seen_item_ids.add(item_id)
4. Prevent Potential N+1 Inventory Queries
Problem

Inventory queries run inside nested loops:

execution_steps
  → step outputs
       → inventory query

This can produce hundreds of SQL queries.

Fix

Load all relevant inventory items once and group them in memory.

Implementation

Before the loops, collect all execution step IDs.

Add:

step_ids = [es.step_id for es in execution_steps if es.step_id]

Load all inventory items once:

inventory_items = (
    session.query(InventoryItem)
    .filter(InventoryItem.source_step_id.in_(step_ids))
    .all()
)

Group by (step_id, unit):

inventory_map = {}

for item in inventory_items:
    key = (item.source_step_id, (item.unit or "").strip())
    inventory_map.setdefault(key, []).append(item)

Then replace the inner query with:

items = inventory_map.get((step_id, out_unit.strip()), [])

Remove the original SQL query from inside the loop.

5. Limit Expiry Results to Prevent Huge Responses
Problem

The API can return extremely large lists of expired items.

Fix

Add a hard cap on returned items.

Implementation

Add constant:

MAX_EXPIRY_ITEMS = 500

Inside the item loop, add:

if len(output_expiry_items) >= MAX_EXPIRY_ITEMS:
    break

Apply this check in the outer loops as well to fully stop processing once limit is reached.

6. Add Backend Validation for Custom Expiry Inputs
Problem

The backend currently trusts frontend validation.

Fix

Validate execution-time expiry input server-side.

Implementation

When processing custom_expiry_input:

Add checks:

- duration_value must be > 0
- duration_unit must be one of: days, weeks, months
- warning_value must be >= 0
- warning_unit must be one of: days, weeks, months
- warning duration must not exceed expiry duration

Example validation:

VALID_UNITS = {"days", "weeks", "months"}

if duration_unit not in VALID_UNITS:
    raise ValueError("Invalid expiry duration unit")

if warning_unit not in VALID_UNITS:
    raise ValueError("Invalid warning duration unit")

if duration_value <= 0:
    raise ValueError("Expiry duration must be positive")

if warning_value < 0:
    raise ValueError("Warning duration must not be negative")

Then ensure:

expiry_delta = _duration_to_timedelta(duration_value, duration_unit)
warning_delta = _duration_to_timedelta(warning_value, warning_unit)

if warning_delta > expiry_delta:
    raise ValueError("Warning period cannot exceed expiry period")
7. Enforce Mode Rules on the Backend
Problem

Frontend currently decides which expiry mode is allowed.

Fix

Backend must enforce mode.

Implementation

When reading output configuration:

If mode is:

fixed_duration

Reject any incoming execution expiry payload.

Example:

if mode == "fixed_duration" and custom_expiry_input:
    raise ValueError("Custom expiry not allowed for fixed_duration outputs")
8. Frontend: Normalize Units Before Sending
Problem

Unit strings can contain whitespace.

Fix

Trim units before sending API requests.

Implementation

Before submission:

payload.unit = payload.unit?.trim()

Apply to:

output unit
expiry unit
warning unit
9. Frontend: Restrict Expiry Mode Values
Problem

Mode strings can drift from backend expectations.

Fix

Use constants.

Implementation

Create constants:

export const EXPIRY_MODES = {
  FIXED: "fixed_duration",
  EXECUTION: "set_at_execution"
}

Use these everywhere instead of raw strings.

10. Frontend: Block Custom Expiry UI When Not Allowed
Problem

Execution UI might allow expiry input even when mode is fixed.

Fix

Conditionally render expiry controls.

Implementation

When rendering execution modal:

if (output.extra_data?.custom_expiry?.mode !== "set_at_execution") {
  hideExpiryControls()
}
11. Frontend: Validate Warning Duration
Problem

Frontend must enforce the same rule as backend.

Fix

Add validation:

warning duration <= expiry duration

Example:

if (warningDuration > expiryDuration) {
  throw new Error("Warning period cannot exceed expiry period")
}
12. Frontend: Always Send UTC ISO Timestamps
Problem

Expiry calculations rely on consistent timestamp formats.

Fix

Ensure all timestamps are serialized in UTC ISO format.

Implementation

When sending timestamps:

new Date().toISOString()

Never send:

local time strings
browser formatted timestamps
13. Prevent Duplicate Expiry Items in UI
Problem

Duplicate inventory items may appear if the backend ever returns duplicates.

Fix

Deduplicate on frontend by item ID.

Implementation

When building the expiry list:

const seen = new Set()

items = items.filter(item => {
  if (seen.has(item.id)) return false
  seen.add(item.id)
  return true
})
14. Add Expiry Result Pagination Support (Optional)
Problem

Large expiry lists can degrade UI performance.

Fix

Support optional pagination parameters.

Backend parameters:
limit
offset

Example:

GET /expiry-check?limit=100&offset=0

1. Remove Duplicate Expiry UI Rendering Logic

Status: ❌ Not included previously — must be added

Your prior instructions focused on validation and mode enforcement, but did not address duplicate rendering logic.

Since you have multiple blocks generating:

.execute-output-expiry-input
.execute-output-expiry-duration-fields
.execute-output-expiry-datetime-fields
.execute-output-expiry-warning-fields

this should absolutely be centralized.

Additional Instruction for Cursor
Step A — Locate duplicate blocks

Search the frontend for:

execute-output-expiry-input

Identify all UI sections generating execution expiry controls.

Step B — Extract reusable renderer

Create a reusable function:

function renderExecutionExpiryUI(output) {
  // existing expiry UI generation logic moved here
}

Move all markup construction related to execution expiry input into this function.

This includes creation of:

.execute-output-expiry-input
.execute-output-expiry-duration-fields
.execute-output-expiry-datetime-fields
.execute-output-expiry-warning-fields
Step C — Replace duplicated code

Replace duplicated rendering blocks with:

expiryInputHtml = renderExecutionExpiryUI(output)

or if used inline:

html += renderExecutionExpiryUI(output)

Ensure only one implementation exists.

2. Stop Using Output Name as DOM Lookup Key

Status: ❌ Not included previously — must be added

The prior plan mentioned unit trimming and schema enforcement, but did not address DOM identity issues.

Using:

data-output-name

is unsafe because output names:

are user editable

may not be unique

may contain whitespace differences

The DOM must use stable identifiers.

Additional Instruction for Cursor
Step A — Replace all data-output-name

Search frontend code for:

data-output-name

Replace with:

data-output-id
Step B — Update DOM rendering

Change UI markup from:

data-output-name="..."

to:

data-output-id="..."

Example:

const outputId = output.id

'<div class="execute-output-expiry-input" data-output-id="' + escapeHtml(outputId) + '">'
Step C — Update lookup logic

Replace selectors like:

el.dataset.outputName === name

with:

el.dataset.outputId === outputId

Ensure all DOM lookups use output.id only.

3. Fix Validation Duplication

Status: ⚠️ Partially included but needs stronger enforcement

The previous instruction set included:

Ensure frontend uses same validation rule

But it did not explicitly remove duplicate inline logic.

Your system currently validates expiry in three locations:

1️⃣ Step builder UI
2️⃣ Execution modal
3️⃣ Pre-submit validation

If each location contains its own validation logic, they will drift.

Additional Instruction for Cursor
Step A — Use shared validator everywhere

All expiry validation must call:

window.CustomExpiryValidation.validateWarnNotLongerThanExpiry()
Step B — Remove inline validation

Search frontend for inline checks such as:

if (warnHours > expiryHours)

or similar variations.

Remove them.

Step C — Replace with shared validator

Replace inline logic with:

window.CustomExpiryValidation.validateWarnNotLongerThanExpiry({
  expiryValue,
  expiryUnit,
  warningValue,
  warningUnit
})
Step D — Ensure validator is used in three locations

The shared validator must be used in:

Step builder UI validation
Execution modal validation
Pre-submit validation

No additional validation logic should exist outside this module.