# Ready Date Implementation for Process Step Outputs

## Overview

Implement a **Ready Date** feature for process step outputs using the **same architectural pattern as Custom Output Expiry**.  

**Definition:**  
- The Ready Date is the **earliest date an output can be used**.  
- Executions and inventory cannot consume or use the output **before this date**.  
- Functionally, this is the inverse of the expiry date.

Use the **same domain single source of truth approach** as with output expiry (metadata in `extra_data`, `CoreChecksRunner` evaluation, and UI alert propagation).

---

## 1. Storage Approach

Store Ready Date configuration in the **existing process step output metadata**, exactly like Custom Output Expiry:


process_step.extra_data
OR
step.output_definition.extra_data


Example structure:

```json
{
  "ready_date": {
    "enabled": true,
    "date": "2026-03-15T00:00:00Z",
    "prompt": "Output cannot be used until 15 March 2026",
    "rule_type": "custom_ready_date"
  }
}

Rules:

Keep storage flexible and backward compatible

Do not create new database tables

Use the same datetime storage conventions as expiry

2. Execution Modal Integration

When performing an execution:

If an output has Ready Date enabled and the current date is before the ready date, display a warning/prompt using the same modal pattern as expiry.

Example UI hint:

⚠️ Ready Date rule applies:
This output cannot be used until 15 March 2026.

Optionally, allow operator to see guidance but still proceed if business rules allow, consistent with expiry prompts.

3. Step Modal Integration

Add Ready Date input in the step configuration modal, same pattern as expiry:

Checkbox/Toggle to enable

Date picker for the ready date

Optional prompt field to describe rule for operators

Validate input before saving:

Must be a valid future date

Optional: Cannot be after an expiry date if expiry is also defined

4. Check Integration

Create a dedicated check module:

app/core/backend/checks/output_ready_date_check.py

Follow the same pattern as output_expiry_check.py:

Traverse process outputs in executions

Detect ready date configuration

Compare current datetime against configured ready date

Generate standardized risk signals if outputs are used before ready date

Return findings in the same structure used by CoreChecksRunner:

{
  "type": "ready_date",
  "severity": "red" | "amber",
  "message": "",
  "execution_id": "",
  "process_id": "",
  "step_id": "",
  "metadata": {}
}

Ensure the check integrates into CoreChecksRunner pipeline, so ready date warnings appear consistently across all system checks.

5. Alert Integration

Render Ready Date alerts in the same UI channels as expiry:

System Findings Banner

Live Inventory modal highlighting

Execution modal

Sourcemap view

Use existing rendering components, no new alert pipelines

6. DAG Traversal

Use dagtraversal.py to respect output dependencies in process flows

Ready Date checks must propagate correctly to downstream steps

Reuse the same traversal logic as for output expiry

7. Audit Logging

Log Ready Date configuration usage:

User ID

Execution ID

Step ID

Timestamp

Message describing Ready Date enforcement

Follow the same audit logging pattern as expiry and SOP docs

8. Tests

Write unit and integration tests covering:

Storage and retrieval of Ready Date configuration

Execution modal prompt rendering before ready date

Step modal configuration and validation

CoreChecksRunner evaluation of ready date rules

Alert rendering in banner, execution modal, inventory modal, sourcemap

Edge cases: current date == ready date, no ready date configured, conflicting expiry dates

Reuse test structure used for output_expiry_check tests

9. Performance Considerations

Avoid repeated scans for Ready Date in long execution flows

Cache or batch-check outputs in CoreChecksRunner where possible

10. Cursor Execution Steps

Extend process_step.extra_data to store Ready Date config

Add Ready Date UI to Step Modal and Execution Modal

Implement output_ready_date_check.py in checks module

Integrate Ready Date check into CoreChecksRunner

Render Ready Date warnings in banner, execution modal, sourcemap, and live inventory

Add audit logging for Ready Date events

Write comprehensive tests mirroring output_expiry_check coverage

Outcome:

Users can define Ready Dates per output

System enforces Ready Date consistently across all execution and inventory flows

Uses existing DB schema, checks pipeline, and alert system

Fully tested and maintains single source of truth