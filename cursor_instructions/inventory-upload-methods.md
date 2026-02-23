Remaining Recommendations — Quick Summary
1. Single Source of Truth for Unit Validation

The pipeline currently validates units using multiple helper paths. This should be consolidated so that canonical unit mapping is the only validation gate.

Recommended approach:

Normalize input → resolve canonical unit → reject if mapping fails.

Remove redundant checks such as separate allowed-unit predicates.

This reduces regression risk and ensures storage semantics always match validation semantics.

2. Use Decimal Arithmetic for Quantity Validation

Floating-point parsing is still used during validation.

Replace this with arbitrary precision numeric validation using decimal arithmetic.

Key goals:

Avoid representation drift.

Improve audit consistency.

Ensure deterministic ingestion behaviour.

If quantities are stored as strings, validate numerically but preserve the sanitized original numeric representation.

3. Avoid Numeric Reconstruction Drift

The current pipeline converts:

input string → float → string storage


This can subtly change formatting.

Preferred pattern:

sanitize → validate → store original numeric form


Do not reformat numeric strings after parsing.

4. Add Structured Logging for Batch Operations

Commit failures currently return generic error responses.

Introduce server-side structured logging for:

Batch start events

Batch success events

Batch rollback events

Exception stack traces

This improves operational observability and debugging efficiency.

5. Reduce Validation Logic Duplication

Validation occurs in both preview and commit phases.

While this is architecturally correct, shared validation logic should be extracted into a reusable function to prevent divergence over time.

Suggested abstraction:

validate_csv_row(row) → validation result object

6. Improve Transaction Boundary Visibility

Although batch commits are atomic, transaction lifecycle signals are not explicitly logged.

Optional but recommended:

Log batch ingestion size

Log tenant ID

Log source method metadata

This is particularly valuable for multi-tenant SaaS monitoring.