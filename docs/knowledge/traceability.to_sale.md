---
topic: "traceability.to_sale"
title: "Tracing to the sale"
domain: "traceability"
summary: "The to-sale trace adds Xero invoice lines to the production trail using the recorded sale-to-lot allocations."
related_topics:
  - traceability.forward
  - traceability.back
  - sales.fifo_matching
  - sales.xero_invoices
related_operations:
  - core_trace_inventory_to_sale_graph
features:
  - crm
---
# Tracing to the sale

## What it means

A to-sale trace traces a lot both ways through production, then adds **sale nodes**: the invoice lines whose sales were matched to those lots. It answers "which customers received stock from this lot", and for an invoice, "which lots filled it".

## How the records relate

- Sale nodes come from the stored allocations between an invoice line and a final-product lot (sales.fifo_matching). One sale can show several lots when it took stock from more than one.
- An edge from a lot to a sale names the exact lot that filled that line.
- A sale appears only if its invoice line is mapped to a product and was matched.

## Authoritative operations

`core_trace_inventory_to_sale_graph` returns the traced lot, all production items and sale nodes, and the connections. Invoices themselves come from sales.xero_invoices.

## Do not assume

- **No sale node does not mean nothing was sold.** Sales before the organisation's go-live date are not matched. Unmapped lines, lines without enough stock, and manual-mode lines awaiting assignment have no allocation.
- **A pending-review match is not final.** In hybrid mode it confirms itself after the review window unless changed.
- **A sale made at a tasting or event** is matched for traceability but does not take warehouse stock.
- **A sale can be a pre-sale.** It may be matched to a lot made after the invoice date.
- **Customer names in sale nodes are the organisation's data.** Report them only to the person who may see sales.
