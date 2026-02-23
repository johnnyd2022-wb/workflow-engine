# Inventory Addition Enhancements — Implementation Guide

## Goal

Extend the existing **`core2.html` centralized inventory panel** to support **three inventory entry methods**:

1. Manual Add Inventory (existing "+ Add to Inventory" modal)
2. CSV Bulk Upload Inventory
3. Barcode / Camera Scan Inventory (Python + raw HTML/CSS/JS)

All implementations must be:

- Responsive across **mobile, laptop, and desktop**
- Non-blocking UX (streaming confirmations preferred)
- Trustworthy — inventory must never silently mutate without user visibility

---

## 1. Central Inventory Entry Hub

### On `core2.html`

Modify the **+ Add to Inventory** button flow to open a selection modal first.

Add three entry paths:

[ Manual Entry ]
[ Upload CSV Template ]
[ Scan Barcode / Camera ]


Do NOT auto-switch methods.

User must explicitly choose.

---

## 2. Manual Inventory Entry Modal (Existing Flow)

Reuse the modal structure.

### Required Fields

| Field | Requirement |
|---|---|
| Item Name | Required |
| Quantity | Required |
| Unit | Required |
| Category | Required (default Raw material) |
| Supplier Name | Optional |
| Purchase Date | Optional |
| Batch Number | Optional |
| Expiry Date | Optional |

---

### Business Rules

- Quantity must be > 0
- Unit must be from allowed unit list
- Store inventory type:
  - Raw Material
  - Work In Progress
  - Final Product

---

## 3. CSV Bulk Upload Inventory (New Feature)

### 3.1 CSV Template Download

Add **Download Template Button**.

Generate template with headers:

Item Name,Quantity,Unit,Supplier Name,Purchase Date,Batch Number,Expiry Date


### Rules

- Required columns:
  - Item Name
  - Quantity
  - Unit

- Optional columns:
  - Supplier Name
  - Purchase Date
  - Batch Number
  - Expiry Date

---

### 3.2 UI Requirements

Upload interface must show:

- Drag and drop area
- File picker button
- Live validation preview

Do NOT immediately commit inventory.

Instead:

1. Parse CSV
2. Validate rows
3. Show streaming preview list:

✓ Row 1 validated
✓ Row 2 validated
⚠ Row 3 unit mismatch


User must confirm before commit.

---

### 3.3 CSV Parsing Backend Strategy

Implement streaming-style processing:

Upload → Parse → Validate → Preview → Confirm → Commit Inventory


Do NOT batch commit without preview.

---

### 3.4 Column Header Protection

Attempt to enforce:

- Frozen header row in preview table
- Unit dropdown suggestion list

Frontend implementation:

- Use CSS sticky header:

```css
thead th {
    position: sticky;
    top: 0;
    background: var(--bg-card);
    z-index: 10;
}
3.5 Unit Dropdown Enforcement
In preview grid:

Replace Unit text with selectable dropdown.

Allowed units should come from backend configuration.

Autocomplete preferred.

Prevent invalid unit submission.

4. Barcode / Camera Inventory Scan
Implement using Python backend + raw HTML/JS frontend.

Do not introduce heavy frameworks.

4.1 Frontend Scanner UI
Create scanner panel:

[ Camera Viewport ]
[ Capture Button ]
[ Manual Fallback Input ]
[ Scan Result Preview ]
[ Add To Inventory ]
4.2 Browser Camera Access
Use native browser APIs:

navigator.mediaDevices.getUserMedia({
    video: { facingMode: "environment" }
});
Prefer rear camera on mobile.

4.3 Barcode Detection Strategy
Backend Python should handle decoding.

Suggested libraries:

python-zxing or pyzbar

Flow:

Capture Frame → Send Image → Backend Decode → Return Item Metadata
4.4 Scan Result Behaviour
When barcode is decoded:

Lookup inventory item

Populate modal fields automatically

Show confirmation card

Never auto-add inventory.

User must confirm.

5. Streaming Confirmation UX (Critical)
For all three methods:

Inventory must be added only after explicit confirmation.

Show confirmation summary:

Item: Steel Rods
Quantity: 50 kg
Supplier: ABC Ltd
Source: CSV Upload (Row 12)
Then show:

[ Confirm Add to Inventory ]
6. Backend Validation Layer
Before inventory commit:

Check:

Unit consistency

Quantity numeric validity

Positive stock rule

Duplicate batch detection (if batch number provided)

7. Mobile UX Priority
Ensure:

Modal width = 95vw max on mobile

Tables scroll vertically

Scanner camera defaults to fullscreen viewport

Buttons are touch-friendly (minimum 44px height)

8. Audit Logging (Platform Requirement)
Every inventory mutation must record:

User ID

Timestamp UTC

Source method:

manual

csv_upload

barcode_scan

Store in:

extra_data.inventory_audit_history
Append only.

Never overwrite.

9. Performance Expectations
CSV processing must be incremental.

Scanner decoding should not block UI thread.

Inventory commit should be transactional.

10. Non-Goals (Explicit)
Do NOT implement:

Background auto-stock inference

Phantom inventory creation

Silent reconciliation

11. Security Notes
Validate uploaded CSV size.

Reject malformed rows.

Sanitize all string inputs.

Backend must revalidate all previewed data before commit.

12. Future Extension Ready
Design code so that you can later add:

Supplier portal uploads

IoT inventory feeds

Multi-execution reconciliation

Priority Implementation Order
CSV Upload Pipeline

Streaming Preview Validation

Barcode Scanner UI

Backend Decoder Endpoint

Audit Trail Logging