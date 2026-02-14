Step 1: Prefill & Modal Handling Improvements
Goal

Enhance in-flow missing item handling by:

Prefilling unit from step definition (instead of default 'kg') for raw inputs.

Parallelizing input modal initialization to improve performance.

Standardizing dataset flags to reliably determine raw vs output.

Clarifying validation messages for untracked outputs.

Requirements
1. Prefill Unit from Step

For window.openAddInventoryModalForMissingInput(prefill):

Use prefill.unit if present.

Fall back to default 'kg' only if no unit in step definition.

if (unitEl) unitEl.value = prefill.unit || 'kg';

2. Parallelize Input Initialization

Currently:

for (const input of step.inputs) {
  await window.addGuidedInput(inputType, true);
}


Suggested:

await Promise.all(step.inputs.map(input => window.addGuidedInput(inputType, true)));


Keeps modals collapsible, avoids serial delays for many inputs.

3. Standardize Dataset Flags

Determine whether “Add Missing Item” is from previous output or raw input consistently:

var fromOutput = Boolean(
  this.dataset.sourceOutputId || this.dataset.sourceStepId || this.dataset.sourceProcessId
);


Use this flag to decide which modal to open:

fromOutput === true → window.openAddUntrackedOutputModal

fromOutput === false → window.openAddInventoryModalForMissingInput

4. Clarify Validation Messages

In add-untracked-output-form submit handler:

if (!name || !unit || isNaN(quantity) || quantity < 0) {
  showNotification(
    'error',
    'Validation error',
    'Please provide a valid name, unit, and non-negative quantity.'
  );
  return;
}


Ensures user understands exactly what is missing or invalid.

Deliverables

Prefill raw input modal with unit from step definition.

Input modals initialized in parallel.

Consistent logic for determining raw vs output when opening missing item modals.

Clear, user-friendly validation for untracked output submission.