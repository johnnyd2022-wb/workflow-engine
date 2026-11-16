---
topic: "costing.xero_bridge"
title: "The Xero bridge"
domain: "costing"
summary: "Xero expenses purchases when bought and Biz-E costs them when sold. The bridge explains the walk between them for a period."
related_topics:
  - costing.stock_value
  - costing.cost_status
  - sales.xero_invoices
related_operations:
  - costing_get_stock_value
features:
  - costing
---
# The Xero bridge

## What it means

The bridge is a report between two stock snapshots. It has two halves:

- **Tie-out.** Xero's stock-account totals for the period against the purchase lines Biz-E synced, listing every line not recorded as stock (open, skipped, partly recorded or not stock), plus journal entries made in Xero.
- **Roll-forward.** Opening stock value plus purchases, less closing value, equals the cost that left stock, split into cost of sales, wastage, samples, variance, production loss, estimate changes and other. It adds up to the cent.

It sits beside Xero's duty accounts against Biz-E's duty, and Xero's overhead accounts, untouched. The roll-forward works with no Xero. Biz-E posts no journals to Xero.

## How the records relate

The bridge reads stored snapshots (costing.stock_value), so it exists only from the second snapshot on. Its Xero state is `ok`, `not_connected`, `needs_reconnect` or `failed`.

## Authoritative operations

The bridge report is an app page and has no assistant operation. `costing_get_stock_value` gives the stock value that closes each period.

## Do not assume

- **Biz-E cost of sales and Xero cost of sales differ by design**, because of timing. Do not call the gap an error.
- **A bridge needs two snapshots.** Say so if there are fewer.
- **Do not suggest a journal.** Biz-E does not post one, and accounting advice belongs to the accountant.
