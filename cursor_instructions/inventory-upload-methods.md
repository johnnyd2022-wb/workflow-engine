1. Remove Duplicate Unit Validation Path
Issue

Unit validation currently occurs through multiple logic paths:

_is_allowed_unit()

_unit_to_canonical()

This introduces the risk of divergence between validation rules and storage rules.

Fix

Make _unit_to_canonical() the single authoritative validator.

Implementation:

Remove redundant unit checks.

Replace all unit validation logic with canonical mapping resolution.

Desired behaviour:

raw unit → normalize → canonical mapping OR reject

2. Replace Floating-Point Parsing with Decimal Validation
Issue

Quantities are validated using:

float(qty_str)


This introduces potential precision drift due to floating-point representation.

Fix

Use arbitrary precision numeric parsing.

Recommended approach:

Python Decimal for validation.

Reject malformed numeric input explicitly.

Avoid:

Intermediate float conversion.

3. Preserve Original Quantity String After Sanitization
Issue

Quantities are validated numerically but then stored as:

quantity=str(qty)


This may alter user-provided formatting semantics.

Example drift:

"1.000" → float → 1.0 → "1.0"

Fix

If quantities are stored as strings:

Validate using Decimal

Store sanitized original input string

This preserves precision fidelity.

4. Add Structured Logging for Commit Failures
Issue

System exceptions during commit are currently swallowed:

except Exception:
    rollback()
    return 500


No diagnostic information is captured.

Fix

Add server-side exception logging.

Recommended pattern:

logger.exception("CSV commit failed")


Do not expose internal exception details to API clients.

5. Consolidate Validation Logic Into Single Canonical Path
Issue

Validation occurs:

During preview validation

During commit validation

However, logic duplication exists between phases.

Fix

Extract shared validation into a reusable function.

Benefits:

Reduces regression risk

Ensures parity between preview and commit behaviour

Simplifies future rule changes

6. Improve Unique Constraint Enforcement Feedback
Issue

Duplicate batch conflicts are handled via IntegrityError.

However:

Row-level error reporting is not available.

Users receive a generic conflict response.

Fix

Consider optional pre-commit duplicate detection for user experience improvement.

Required constraint remains database-level uniqueness enforcement.

7. Improve CSV Truncation Contract
Issue

Frontend infers truncation message using row count heuristics.

Fix

Backend should explicitly return:

validated_count

truncated_flag

max_rows_allowed

This removes ambiguity in client rendering.

8. Add Structured Transaction Boundary Logging (Optional but Recommended)
Issue

Transaction boundaries are currently implicit.

Fix

Consider logging:

Batch start

Batch success

Batch failure

This improves operational observability during ingestion events.

9. Remove Dead Exception Variable

Current code captures:

except Exception as e:


But does not use e.

Fix

Either:

Log exception

Or remove variable binding.