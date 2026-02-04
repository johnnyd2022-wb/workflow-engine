# Production Hardening Instructions – Core Checks (TEST & CHECK LAYER ONLY)

## Scope (IMPORTANT)
These changes apply **ONLY to the core checks and test-related logic**:
- `expired_materials.py`
- `corechecks.py`
- Related test coverage

🚫 **DO NOT modify DAG traversal logic**
🚫 **DO NOT change dagtraversal.py behavior**
🚫 **DO NOT alter traversal semantics, SQL, or performance characteristics**

The DAG traversal layer is already trusted and correct.

---

## 1. Quantity Handling: Remove Defensive Parsing

### Problem
`expired_materials.py` currently converts quantities using:
- `str → Decimal`
- Silent exception swallowing

This hides data integrity issues and adds unnecessary overhead.

### Action
Replace this logic:

```python
try:
    qty_str = str(item.quantity).strip() if item.quantity else "0"
    quantity_decimal = Decimal(qty_str)
    if quantity_decimal > Decimal("0"):
        expired_with_stock.append(item)
except (InvalidOperation, ValueError, TypeError):
    pass
With direct numeric comparison, trusting the DB type:

if item.quantity is not None and item.quantity > 0:
    expired_with_stock.append(item)
Rationale
Quantity is a numeric DB field

Invalid quantities should surface upstream, not be silently ignored

Core checks must be trustworthy and auditable

2. Deduplicate Impacted Connections
Problem
connections returned from DAG traversal may be appended multiple times across expired raw materials.

Action
Ensure result_connections is deduplicated using a stable key:

(from_id, to_id, execution_id)

Implementation options:

Use a set of tuples internally

Or post-process list into unique entries

Constraint
Preserve output shape

Do NOT change traversal output itself

3. Add Explicit Domain Semantics Comment
Action
Add a single, explicit comment in expired_materials.py explaining the compliance intent.

Example:

# Impacted items are products produced by executions that consumed
# expired raw materials while stock was present.
# This aligns with compliance and recall semantics.
Rationale
Prevents future refactors from weakening compliance correctness.

4. Preserve Traversal Granularity (No Bulk Refactor)
Explicit Instruction
⚠️ Do NOT refactor traversal into bulk mode at this stage.

Even though traversal runs once per expired raw material:

This is acceptable for current SME scale

Bulk traversal may be added later deliberately

Cursor should not attempt optimization here.

5. API Contract: No Structural Changes
Constraint
Do NOT change the API response shape returned by:

GET /api/core/inventory/expired-materials
Current shape must remain:

{
  "expired_raw_materials": [...],
  "impacted_items": [...],
  "connections": [...]
}
Any future envelope changes will be handled separately.

6. Tests: Lock in Compliance Semantics
Add / Ensure Tests Cover:
Expired raw with zero quantity

Not flagged

Not included in results

Expired raw with stock, but used before expiry

Raw flagged

No impacted items

Expired raw with stock, used after expiry

Raw flagged

Impacted items present

Connections present

Constraints
Tests may use real DB + demo data

Do NOT modify DAG traversal to satisfy tests

Tests should validate behavior, not implementation details

7. Error Handling Philosophy
Rule
Core checks must:

Fail loudly in logs

Never silently hide corrupt data

Never compromise accuracy for convenience

If a check fails:

Runner should mark it flagged=True

Include failure message

Continue running other checks

(This behavior already exists — preserve it.)

Summary
What to change
Simplify quantity handling

Deduplicate connections

Add domain clarity comment

Strengthen test coverage

What NOT to change
DAG traversal logic

Traversal SQL

API response shape

Execution semantics

The goal is audit-grade correctness, not premature optimization.