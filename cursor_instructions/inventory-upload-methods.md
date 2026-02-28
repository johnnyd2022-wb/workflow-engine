📦 Barcode-Aware Inventory Entry – Implementation Plan
Objective

Enhance inventory entry so that:

When a barcode is scanned:

If barcode does not exist → open manual entry flow (same as current manual modal).

If barcode exists → prefill known product fields and only prompt for stock-specific metadata.

The solution must integrate with existing SQLAlchemy models, Alembic migrations, and frontend modal architecture.

1️⃣ Data Model Updates (SQLAlchemy + Alembic)
Step 1.1 — Add Barcode Support

Update your inventory-related model(s) to support storing a barcode.

High-level requirement:

Add barcode column (String, indexed).

Make it unique only if your business rule requires unique product identity.

Otherwise, allow reuse across stock entries.

Cursor should:

Update the SQLAlchemy model.

Generate an Alembic migration.

Apply proper indexing.

Step 1.2 — Decide Data Ownership Model

Cursor should determine from your schema whether:

You already have a Product-like abstraction.

Or inventory rows directly store item attributes.

If you already have a product table:

Barcode should live at the product level.

If not:

Barcode can initially live on the inventory table.

Cursor should align with your current domain model, not introduce new tables unless necessary.

2️⃣ Backend: Barcode Lookup Endpoint
Step 2.1 — Add Barcode Lookup Route

Create a new API endpoint:

GET /api/inventory/barcode/<code>

Behavior:

Query existing records for that barcode.

Return:

exists: true + canonical item data

OR exists: false

Important:

Do not return sensitive fields.

Return only:

name

unit

supplier

(any other product-level attributes you already store)

Cursor should:

Reuse existing service/query layers if present.

Follow your current JSON response conventions.

Use proper error handling.

3️⃣ Frontend: Scanner Integration
Step 3.1 — Hook Into Existing Scan Success

When a barcode is successfully decoded:

Replace direct modal logic with:

lookupBarcode(code)

Cursor should integrate into your existing scanner success handler.

Step 3.2 — Barcode Lookup Flow

Frontend logic:

Call lookup endpoint.

If exists === false:

Open existing manual modal.

Prefill barcode field.

If exists === true:

Open entry modal.

Prefill:

name

unit

supplier

Lock those fields.

Prompt only for:

quantity

purchase date

expiry date

batch number

Cursor should:

Reuse the current modal.

Avoid duplicating forms.

Toggle fields dynamically.

4️⃣ Modal Behavior Rules
Case A – New Barcode

User must input:

Name

Quantity

Unit

Supplier

Purchase date

Barcode should be:

Visible (or hidden) but stored

Editable only if you allow corrections

Case B – Existing Barcode

Prefill and lock:

Name

Unit

Supplier

User inputs:

Quantity

Purchase date

Expiry date

Batch number

Barcode must still be submitted in payload.

5️⃣ Backend Save Logic

Cursor should modify the existing create-inventory endpoint so that:

If barcode provided:

Persist it.

If barcode exists:

Ensure product identity remains consistent.

Prevent conflicting product definitions for the same barcode.

If mismatch occurs:

Return 409 or validation error.

6️⃣ Validation Requirements

Backend must enforce:

Quantity required

Name required (unless product resolved via barcode)

Purchase date required

Barcode optional unless coming from scanner

Do not rely solely on frontend validation.

7️⃣ Alembic Migration Instructions

Cursor should:

Modify SQLAlchemy model.

Generate migration:

alembic revision --autogenerate -m "add barcode to inventory"

Review migration for correctness.

Do not apply the migration - I will do this once all the code is prepped for review

Migration must:

Add column.

Add index.

Handle nullable state safely.

8️⃣ Edge Cases

Cursor must handle:

Barcode exists but product fields differ → reject with validation error.

Barcode reused for multiple batches → allowed.

Manual entry without barcode → allowed.

9️⃣ Testing Scenarios
Scenario 1 – First Scan

Scan unknown barcode

Manual modal appears

Save

Confirm barcode persisted

Scenario 2 – Repeat Scan

Scan same barcode

Fields prefilled and locked

Save new quantity with batch data

Scenario 3 – Manual Flow Unchanged

Manual button works exactly as before

🔟 Architectural Principle

Barcode represents product identity.

Inventory entry represents stock event.

Cursor should preserve separation if your schema already supports it.

Expected Outcome

After implementation:

Barcode acts as a product accelerator.

Manual workflow remains intact.

Scanner integrates cleanly.

Schema remains aligned with your domain model.

No duplicated modal logic.