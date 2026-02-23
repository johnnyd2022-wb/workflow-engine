2️⃣ Critical Issues & Improvements for csv upload to inventory
🚨 Issue 1: No Transaction Wrapping in csv_commit

You are doing:

for r in rows:
    repo.create_inventory_item(...)


If:

Row 1 succeeds

Row 2 succeeds

Row 3 throws

Row 4 succeeds

You will commit partial state.

Risk:

Operational inconsistency

Audit trail confusion

Broken expectation of “bulk commit”

Recommended Fix

Wrap entire batch in a DB transaction:

with db_session.begin():
    for r in rows:
        ...


Or:

try:
    ...
    db_session.commit()
except:
    db_session.rollback()


Decide explicitly:

Atomic batch? (all-or-nothing)

Partial commit allowed? (current behavior)

Right now it is implicitly partial.

That should be explicit.

🚨 Issue 2: Duplicate Batch Race Condition

This check is unsafe:

existing = db_session.query(...).first()


Two uploads in parallel could pass this check simultaneously.

Correct solution:

Enforce unique constraint at DB level:

UNIQUE (org_id, name, supplier_batch_number)


Then catch IntegrityError on insert.

Application-layer checks are not safe for uniqueness.

⚠ Issue 3: Unit Normalization Inconsistency

In validate:

ul = _normalize_unit(unit_raw)


But in commit:

if not _is_allowed_unit(unit):


If frontend changes casing to Kg or similar, normalization is weaker in commit phase.

Recommendation:

Normalize on commit explicitly:

unit = _normalize_unit(unit)


Then map to canonical value.

Never trust the frontend normalization.

⚠ Issue 4: Quantity Stored as str(qty)

You pass:

quantity=str(qty)


This is suspicious.

Inventory quantities should be numeric types:

Decimal

Numeric

Float (if you're okay with precision risk)

If DB column is string:
That is a design flaw for financial/compliance-grade systems.

If DB column is numeric and repo casts:
Fine.

But verify that.

⚠ Issue 5: Missing CSV Row Count Limit on Validation

You limit commit to 500 rows:

if len(rows) > 500:


But validation does not enforce row count.

Someone could upload 50k rows → heavy memory usage during validation.

Add:

if i > 500:
    break


Or hard error if > 500.