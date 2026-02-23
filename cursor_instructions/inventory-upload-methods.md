1. ❗ Float Parsing Still Exists (Highest Priority)
Problem

Despite the design notes, the code still contains:

qty = float(qty_str)


This defeats the decimal safety objective.

Floating point parsing is still occurring in:

Preview validation phase

Commit phase

Fix

Replace all numeric parsing with decimal arithmetic.

Example pattern:

from decimal import Decimal, InvalidOperation

try:
    qty = Decimal(qty_str)
    if qty <= 0:
        raise ValidationError
except InvalidOperation:
    reject

Why This Matters

Floating point parsing can introduce:

Representation drift

Audit mismatch

Compliance uncertainty

This is especially relevant if inventory data feeds reporting pipelines.

2. ❗ _is_allowed_unit() Is Now Redundant

You have achieved single-source canonicalisation via:

_unit_to_canonical()


But validation still checks:

_is_allowed_unit(unit_raw)


This creates two semantic validation paths.

Fix

Remove _is_allowed_unit() entirely.

Replace validation logic with:

canonical_unit = _unit_to_canonical(unit_raw)

if canonical_unit is None:
    error


This guarantees rule consistency.

3. ⚠ Quantity Reconstruction Drift Risk

You still reconstruct quantity via:

quantity=str(qty)


Combined with float parsing, this can cause formatting drift.

Example risk:

"1.000" → float → 1.0 → "1.0"

Correct Pattern

If quantities are stored as strings:

sanitize → validate → preserve original numeric representation


Do not regenerate numeric strings after parsing.

4. ⚠ Exception Variable Is Unused

You have:

except Exception as e:


But e is not used.

Either:

Remove as e, or

Add structured logging.

Recommended:

logger.exception("CSV batch commit failed", extra={"org_id": org_id})


Silent exception swallowing is operationally dangerous.

5. ⚠ Validation Logic Duplication Still Exists

You have improved architecture by introducing _validate_row() conceptually.

However, duplication still exists between:

Preview validation path

Commit Phase 1 validation path

The only remaining divergence risk is numeric parsing.

Recommendation

Extract:

validate_row(name, qty_str, unit_raw)


Return:

(status, message, canonical_unit, quantity_storage_value)


This eliminates future drift risk.