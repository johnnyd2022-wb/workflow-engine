⚠️ Issue 1 — Backend Unit Validation Logic Has Redundancy
Problem

You now do:

Append error if unit invalid

but later code still contains:

elif du_raw not in VALID_EXPIRY_UNITS or wu_raw not in VALID_EXPIRY_UNITS:
    pass

This is dead logic.

Fix

Remove this block:

elif du_raw not in VALID_EXPIRY_UNITS or wu_raw not in VALID_EXPIRY_UNITS:
    pass

Because:

Validation is already handled earlier.

Leaving this is confusing and risks future regression.

⚠️ Issue 2 — Duplicate Payload Construction Paths (Frontend)

This is the biggest remaining architectural smell.

You are still constructing expiry payloads in two different loops.

You have:
Path A

Inside execution modal collector:

outputInputs.forEach(...)

Builds payload.

Path B

Inside expiry capture block:

if (mode === 'set_at_execution')

Builds payload again.

Risk

If expiry schema changes later:

You must update two code locations.

This is exactly the type of bug you were trying to eliminate.

Recommended Fix (Important)

Create one function:

window.collectExecutionOutputExpiryPayload = function(modal, outputDef) {
    // All expiry payload extraction logic goes here
};

Then replace both collectors.

This will remove ~120 lines of JS duplication.

⚠️ Issue 3 — Lookup Logic Has One Small Identity Escape Path

You correctly switched to:

outputId

BUT this pattern still exists in one place:

return id === outName || nm === outName;

This must be removed.

Correct Pattern

Always:

return dataset.outputId === outputId;

No fallback to name matching.

Remove This Completely

Search frontend code for:

dataset.outputName

Delete usage.

⚠️ Issue 4 — Minor Backend Behaviour Consistency

This block:

if du_raw not in VALID_EXPIRY_UNITS:
    execution_errors.append(...)

is good.

But later you still have:

_duration_to_timedelta(...)

which silently assumes unit validity.

Better pattern:

if validation_errors:
    return failure

Then never reach conversion stage.