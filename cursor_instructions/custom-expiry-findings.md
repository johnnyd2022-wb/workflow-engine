⚠ Minor backend improvement (optional)

You normalize invalid units to "days" silently:

if du_raw not in VALID_EXPIRY_UNITS:
    du_raw = "days"

Better behaviour would be reject invalid units instead of mutating them.

Safer version:

if du_raw not in VALID_EXPIRY_UNITS:
    execution_errors.append(
        f"Output '{output_name}': invalid expiry duration unit."
    )

1. Duplicate Execution Expiry UI Still Exists ❌

You still have two separate blocks generating the same markup.

Example blocks appear around:

~ line 833
~ line 480

Both generate:

.execute-output-expiry-input
.execute-output-expiry-duration-fields
.execute-output-expiry-datetime-fields
.execute-output-expiry-warning-fields

The duplication was not actually removed, only modified.

Why this matters

Any future change (validation, styling, new expiry option) must be applied twice, which guarantees drift later.

Required Fix

Extract the markup generator into a reusable function.

Create:
function renderExecutionExpiryUI(output) {
  const outputId = (output.id != null && String(output.id).trim() !== '')
    ? String(output.id)
    : (output.name ? 'out-' + output.name.replace(/\s+/g, '-') : 'out-unknown');

  const outName = output.name || '';

  return `
  <div class="execute-output-expiry-input"
       data-output-id="${escapeHtml(outputId)}"
       style="margin-bottom: 12px; padding: 12px 16px; background: hsl(38,92%,95%); border:1px solid var(--warning,#f59e0b); border-radius: var(--radius-md);">

    ...existing markup...

  </div>
  `;
}
Replace duplicated blocks with
expiryInputHtml = renderExecutionExpiryUI(output)

This removes UI drift risk.

2. data-output-name Still Exists ❌

You introduced data-output-id correctly, but did not remove data-output-name.

Example:

data-output-id="..."
data-output-name="..."

and later:

var nm = (b.dataset.outputName || '').trim()
return id === outName || nm === outName

This re-introduces the original bug.

Why this matters

Output names:

are editable

may not be unique

may change after step definition edits

DOM identity must only use IDs.

Required Fix
Remove all data-output-name attributes

Change:

data-output-id="..."
data-output-name="..."

to:

data-output-id="..."
Update lookup logic

Replace:

return id === outName || nm === outName

with:

return id === outputId

Then ensure outputId is passed consistently when searching.

3. Execution Expiry Lookup Still Uses Name ⚠

You still locate expiry boxes like this:

const box = Array.from(modal.querySelectorAll('.execute-output-expiry-input')).find(function(b) {
  const id = (b.dataset.outputId || '').trim();
  const name = (b.dataset.outputName || '').trim();
  return id === outName || name === outName;
});

This should use only IDs.

Correct version
const box = Array.from(
  modal.querySelectorAll('.execute-output-expiry-input')
).find(function(b) {
  return (b.dataset.outputId || '').trim() === outId;
});