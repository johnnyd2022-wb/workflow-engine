## ✅ Resolved (latest)

**Dual validation path (architecture fix)**  
- Added **`app/core/domain/expiry_rules.py`** as the single place for the invariant `warning_delta <= expiry_delta`.
- Exports: **`VALID_EXPIRY_UNITS`**, **`duration_to_timedelta(value, unit)`**, **`assert_warning_within_expiry(output_name, duration_value, duration_unit, warning_value, warning_unit)`** → returns list of error strings (one if invalid, else empty).
- **Backend**: `validate_custom_expiry_warning_not_exceed_duration()` now delegates to `assert_warning_within_expiry()`. Execution save path and tests still call the backend wrapper; both use the same domain rule.
- **Runtime check** (`run_output_expiry_check`) only derives expiry/warn from stored data and does not re-validate the rule; it can later call the same domain rule if we want to flag invalid stored data.

**Assertion style**  
- The `next(i for i in items ...)` pattern was already replaced with `filtered = [i for i in items if ...]; assert len(filtered) == 1` in the output-expiry tests.

**Deferred (low priority)**  
- **Fixture leakage**: Tests still use `db.query(...).delete(); db.commit()`. If you introduce parallel test runs, consider a transactional rollback fixture pattern.
- **Naming**: `execution_errors` vs `details` vs errors list left as-is for now; standardising the error envelope can be done later.

---

⚠️ MOST IMPORTANT FINDING (Fix This)
🚨 Risk: Dual Validation Path (Backend Logic Split)

You now have expiry warning validation in:

Layer A — Save-time validator
validate_custom_expiry_warning_not_exceed_duration()

Runs during execution completion.

Layer B — Runtime check extractor logic
run_output_expiry_check()

Uses derived expiry window.

Why this is dangerous

If someone later modifies one layer but not the other:

You can get:

Execution saved successfully

But system check banner shows contradiction

This is a classic workflow compliance drift bug.

⭐ Recommended Architecture Fix (Strongly Recommend)

Extract invariant rule:

warning_delta <= expiry_delta

Into a single domain utility module.

Example:

app.core.domain.expiry_rules.py

Export:

assert_warning_within_expiry(...)

Then call it from:

Execution save validator

Tests

Future UI validator

Right now you are close but not fully unified.

⚠️ Second Risk — Test Fixture Leakage Pattern

This pattern appears multiple times:

db.query(...).delete()
db.commit()

inside tests.

This is okay but:

👉 If tests ever run in parallel, you may get race contamination.

If CI parallelization is possible, switch to:

Transactional rollback fixture pattern.

🟡 Minor Notes (Low Priority)
Naming consistency

You have both:

execution_errors
details
errors list

Consider standardising error envelope shape.

Not mandatory.

Assertion style

This is slightly weaker:

next(i for i in items ...)

Safer pattern:

filtered = [i for i in items if ...]
assert len(filtered) == 1

(You already use this elsewhere.)