# CRM Enhancements Plan

## Checklist

- [ ] **1. Line items on invoices** — show line items in the invoice accordion on customer detail page
- [ ] **2. Mappings dropdown** — prefill Xero description dropdown from that customer's invoice line item descriptions/codes
- [ ] **3. CRM Overview page** — new `/crm` landing page with sales insights, task board
- [ ] **4. Wire up navigation** — sidebar points to `/crm` overview, overview links to `/crm/customers`

---

## 1. Line Items on Invoices

**Status:** API already returns line items (`with_line_items=True` in `_serialise_invoice`). Frontend doesn't render them.

**Files to change:**
- `app/features/crm/frontend/templates/crm/customer_detail.html` — expand the invoice accordion to show a line items table beneath each invoice row
- `app/features/crm/frontend/js/customer-detail.js` — ensure line_items are stored on each invoice object (they already come from the API)

**Line item fields to display:** description, item_code, quantity, unit_amount, line_amount, tax_type

**UI pattern:** When the user clicks an invoice row, expand an inline sub-table showing line items. Already accordion-style — just add the line items table inside the expanded panel.

---

## 2. Mappings Dropdown from Line Items

**Status:** Mappings tab has a free-text "Xero description" input. Should become a dropdown populated from all unique line item descriptions/item_codes for that customer.

**New API endpoint needed:**
```
GET /api/crm/customers/<contact_id>/line-item-descriptions
```
Returns `[{description, item_code, display_label}]` — unique list across all that customer's invoices.

**Files to change:**
- `app/features/crm/routes/api_routes.py` — add new endpoint
- `app/features/crm/services/crm_service.py` — add `get_customer_line_item_options(contact_id, org_id)`
- `app/features/crm/repositories/xero_invoice_repo.py` — add query for distinct descriptions/codes for a contact
- `app/features/crm/frontend/templates/crm/customer_detail.html` — change mappings input to `<select>` populated from API
- `app/features/crm/frontend/js/customer-detail.js` — load line item options on tab open, populate dropdown

---

## 3. CRM Overview Page

**New route:** `GET /crm` — currently redirects to `/crm/customers`, change to render `crm/overview.html`

**New API endpoint:**
```
GET /api/crm/overview
```
Returns:
```json
{
  "current_month_revenue": 12500.00,
  "current_month_invoice_count": 23,
  "outstanding_receivables": 4200.00,
  "outstanding_invoice_count": 8,
  "revenue_vs_last_month_pct": 12.5,
  "top_products": [
    {"item_code": "WB-700", "description": "Whistlebird 700ml", "total_qty": 48, "total_revenue": 2200.00}
  ],
  "monthly_trend": [...],   // last 6 months
  "open_tasks": [...],      // all pending/in_progress tasks
  "tasks_by_status": {"pending": 5, "in_progress": 3, "completed": 12}
}
```

**Files to create/change:**
- `app/features/crm/routes/api_routes.py` — add `/api/crm/overview` endpoint
- `app/features/crm/services/crm_service.py` — add `get_overview(org_id)` method
- `app/features/crm/repositories/xero_invoice_repo.py` — add current month totals, outstanding totals, top products queries
- `app/features/crm/routes/page_routes.py` — change `/crm` from redirect to `render_template("crm/overview.html")`
- `app/features/crm/frontend/templates/crm/overview.html` — new template (see layout below)

**Overview page layout:**
```
┌─────────────────────────────────────────────┐
│ CRM                    [Customers →]         │
│ Sales performance and customer insights      │
├──────────┬──────────┬──────────┬────────────┤
│ This     │ Outstand-│ MoM      │ Open Tasks │
│ Month    │ ing      │ Change   │ Count      │
│ $12,500  │ $4,200   │ +12.5%   │ 8          │
├──────────┴──────────┴──────────┴────────────┤
│ Monthly Sales (bar chart — last 6 months)   │
├──────────────────────┬──────────────────────┤
│ Top Products         │ Task Board           │
│ (table: item, qty,   │ Kanban 3 cols:       │
│  revenue)            │ To Do | In Progress  │
│                      │ | Done (recent)      │
└──────────────────────┴──────────────────────┘
```

**Stat cards:** current month revenue, outstanding receivables, MoM % change, open task count

**Bar chart:** last 6 months revenue (reuse same canvas approach as analytics.html)

**Top products table:** aggregate line items by item_code/description, sort by total revenue desc, show top 8

**Task board:** mini kanban — 3 columns (pending, in_progress, completed last 7 days), max ~5 cards per column, "View all tasks →" link

---

## 4. Navigation

**Files to change:**
- `app/ui/templates/shared/sidebar-v2.html` — CRM nav link points to `/crm` (was `/crm/customers`)
- `app/features/crm/frontend/templates/crm/overview.html` — "View all customers →" button links to `/crm/customers`
- `app/features/crm/routes/page_routes.py` — `/crm` renders overview instead of redirecting

---

## Implementation Order

1. Line items in customer detail UI (quickest — API already done)
2. Line item descriptions endpoint + mappings dropdown
3. Overview API endpoint + service methods + repo queries
4. Overview page template + JS
5. Navigation wiring
6. Ruff check + commit

---

## Key Files Reference

| File | Purpose |
|------|---------|
| `app/features/crm/routes/api_routes.py` | Add overview + line-item-descriptions endpoints |
| `app/features/crm/routes/page_routes.py` | Change /crm to render overview |
| `app/features/crm/services/crm_service.py` | Add get_overview(), get_customer_line_item_options() |
| `app/features/crm/repositories/xero_invoice_repo.py` | Add monthly totals, outstanding, top products queries |
| `app/features/crm/frontend/templates/crm/overview.html` | New overview page |
| `app/features/crm/frontend/templates/crm/customer_detail.html` | Add line items sub-table in invoice accordion |
| `app/features/crm/frontend/js/customer-detail.js` | Wire line items + mappings dropdown |
| `app/ui/templates/shared/sidebar-v2.html` | Update CRM nav link |
