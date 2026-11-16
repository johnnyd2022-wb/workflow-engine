---
topic: "sales.fifo_matching"
title: "Matching sales to stock (FIFO)"
domain: "sales"
summary: "Mapped invoice lines are matched to final-product lots, lowest label batch number first, and each match is stored."
related_topics:
  - sales.xero_invoices
  - traceability.to_sale
  - inventory.holds
  - costing.cost_status
related_operations:
  - crm_crm_api_get_org_invoices
  - costing_margins_report
features:
  - crm
---
# Matching sales to stock (FIFO)

## What it means

For each mapped invoice line on an authorised or paid sale, Biz-E takes the quantity from `final_product` lots of that product and stores an **allocation**: invoice line, lot and quantity. The allocations are what the to-sale trace, cost of sales and excise use.

Lots are taken in this order: **label batch number** ascending (lots with no number last), then purchase date, then created time. It is not by expiry, and not by when the invoice was paid.

## How the records relate

- Held lots, customer-owned lots and lots with zero quantity are skipped, so the sale falls to the next lot.
- Counted goods move in whole units, and a unit is never split between lots.
- If stock is short, nothing is taken and the line stays unallocated until stock exists.
- The organisation chooses a mode: `fifo` (automatic), `manual` (a person picks the lot for each line) or `hybrid` (automatic, but inexact matches wait for review and confirm themselves after a review period).
- Sales dated before the go-live date are not matched. A voided or changed invoice reverses its allocations.
- A match to a lot made after the invoice date is marked a pre-sale.
- A sale made at a tasting or event is matched for traceability but does not move warehouse stock.

## Authoritative operations

- `crm_crm_api_get_org_invoices`: the invoices and lines.
- `costing_margins_report`: margin per product per month, using the lots each sale was matched to.

To see which lots a sale took, use the to-sale trace on a lot (traceability.to_sale).

## Do not assume

- **FIFO here means label batch order, not oldest by date.**
- **Matching does not check expiry or ready date.**
- **An unallocated line is not a lost sale.** It is a sale with no stock matched yet.
- **A pending-review allocation is provisional.**
- **Units without an allocation are costed at the product's average** in margins and marked estimated, or left out if nothing is costed.
