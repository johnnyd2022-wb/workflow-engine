1️⃣ Backend Python Changes
elif du_raw in VALID_EXPIRY_UNITS and wu_raw in VALID_EXPIRY_UNITS:
    expiry_delta = _duration_to_timedelta(dv_int, du_raw)
    warning_delta = _duration_to_timedelta(warn_val_int, wu_raw)
    if warning_delta > expiry_delta:
        execution_errors.append(
            f"Output '{output_name}': warning period cannot exceed expiry period."
        )
Observations:

✅ Good: You removed the previous redundant pass blocks and now validate only when both units are valid.

⚠ Small Risk: Make sure dv_int and warn_val_int are always integers. If either could be None, _duration_to_timedelta may raise an exception. You might want to do an extra check:

if dv_int is not None and warn_val_int is not None:
    expiry_delta = _duration_to_timedelta(dv_int, du_raw)
    warning_delta = _duration_to_timedelta(warn_val_int, wu_raw)
    if warning_delta > expiry_delta:
        execution_errors.append(...)
2️⃣ Frontend JS — collectExecutionOutputExpiryPayload

You’ve introduced a single canonical collector for expiry data:

window.collectExecutionOutputExpiryPayload = function(modal, outputId) { ... }
Observations:

✅ This addresses the earlier duplication issue. Now all modal expiry inputs (duration or datetime) are captured in one place.

✅ Proper fallback defaults: duration unit defaults to "days", warning value defaults to 7.

⚠ Minor: parseInt is used for both duration and warning. Make sure decimals aren’t allowed (or intentionally truncated). This is consistent with your previous step quantity pattern, so probably okay.

✅ You correctly handle both "duration" and "datetime" modes with a single path.

3️⃣ Frontend JS — Payload Assignment
if (mode === 'set_at_execution' && typeof window.collectExecutionOutputExpiryPayload === 'function') {
    const payload = window.collectExecutionOutputExpiryPayload(modal, outputId);
    if (payload) outPayload.custom_expiry_input = payload;
}
Observations:

✅ Correctly uses the single shared collector.

⚠ Redundant Try Block: You still have two identical try blocks in the snippet you pasted. One is enough.

⚠ Could be simplified:

const ce = outputDef?.extra_data?.custom_expiry;
if (ce?.enabled && ce.mode === 'set_at_execution' && typeof window.collectExecutionOutputExpiryPayload === 'function') {
    const payload = window.collectExecutionOutputExpiryPayload(modal, outputId);
    if (payload) outPayload.custom_expiry_input = payload;
}

This removes duplication and reduces nesting.