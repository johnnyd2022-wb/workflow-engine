# Custom Output Expiry Configuration — Implementation Instructions

## Overview

Implement custom expiry definitions for process step outputs using the **same architectural pattern used for SOP document attachments in process steps**.

Do NOT build a new expiry subsystem.

Instead:

- Extend the existing expiry detection pipeline
- Store configuration using the existing database schema/storage style
- Reuse CoreChecks traversal and banner/sourcemap alert rendering

---

## 1. Execution Flow Design

Custom expiry should be defined as a **prompt-style configuration attached to process step outputs**, similar to SOP documentation. Add the configuration for output expiry on step3 of the step definitions under the output configuration with the same drop down options as process docs or evidence or batch number

Users must be able to:

- Define expiry rules when configuring process steps
- Specify expiry behaviour that applies during execution
- Have the system evaluate expiry during system checks

---

## 2. Storage Approach (Critical — Follow This)

Do NOT create new expiry tables.

Reuse existing metadata storage patterns used for SOP docs.

Store custom expiry configuration inside:


process_step.extra_data
OR
step.output_definition.extra_data


Structure example:

```json
{
  "custom_expiry": {
    "enabled": true,
    "expiry_days": 30,
    "expiry_prompt": "Output must be used within 30 days after production",
    "rule_type": "custom_output_expiry"
  }
}

Rules:

Keep schema flexible

Do not modify core inventory or execution schemas

Maintain backward compatibility

3. UI Behaviour (Execution Modal)

When operator performs execution:

If output step has custom expiry config:

Show Prompt

Display expiry guidance inline:

Expiry rule description

Required action if expiry risk exists

Example UI hint:

⚠️ Custom expiry rule applies:
This output should be consumed within X days.
4. System Checks Integration

Implement expiry evaluation inside the existing checks framework.

Create:

app/core/backend/checks/output_expiry_check.py

This file must follow the same pattern as:

expired_materials.py

untracked_items.py

Check Logic Responsibilities

The check should:

Traverse executions and process step outputs

Detect custom expiry configuration

Evaluate current date vs configured expiry rule

Generate standardized risk findings

Output Format

Return findings in the same structure used by CoreChecksRunner.

Example:

{
    "type": "expiry",
    "severity": "red" | "amber" | "yellow",
    "message": "",
    "execution_id": "",
    "process_id": "",
    "step_id": "",
    "metadata": {}
}
5. Banner Alert Integration

Custom expiry risks must appear in:

System findings banner

Sourcemap highlighting

Execution modal warning boxes

Reuse existing renderer components.

Do NOT create new alert rendering pipelines.

6. DAG Traversal Usage

When evaluating expiry:

Use existing traversal logic in:

dagtraversal.py

Purpose:

Ensure downstream step dependencies are respected

Allow expiry signals to propagate through process flows

7. Database Integrity Rules

Custom expiry configuration must NOT:

Modify inventory quantity

Automatically block execution flow

Instead:

Generate risk signals only

Allow operator override where appropriate

This preserves operational usability.

8. Audit Trail Requirement

When custom expiry configuration is used:

Log event in audit system with:

User ID

Execution ID

Step ID

Expiry rule triggered

Timestamp

Use existing audit logging pattern.

9. Performance Safety

Implementation must:

Avoid repeated traversal scans

Cache check results where possible inside CoreChecksRunner lifecycle

10. Testing Requirements

Add tests covering:

Custom expiry configuration storage

Check detection logic

Banner alert propagation

Execution modal warning display

Positive path (no expiry risk)

Negative path (expired / near expiry)

11. Code Style Requirements

Follow existing backend repository patterns

Use repository/service separation already present

Do not introduce new architectural layers

Keep implementation minimal and consistent

12. Final Architecture Goal

Custom expiry should behave as:

Process Step Output Definition
        ↓
Execution Runtime Evaluation
        ↓
CoreChecks Risk Signal
        ↓
Banner / Sourcemap / Modal Highlight

Without creating a parallel expiry subsystem.

Cursor Execution Priority

Implement storage extension using existing metadata fields

Create output_expiry_check.py inside checks module

Integrate check into CoreChecksRunner pipeline

Add UI prompt rendering hooks

Write integration tests