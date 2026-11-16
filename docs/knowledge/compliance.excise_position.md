---
topic: "compliance.excise_position"
title: "Excise position"
domain: "compliance"
summary: "The position summarises the year's duty against Customs thresholds, the period in progress, stocktake status, remissions and product setup."
related_topics:
  - compliance.excise_periods
  - inventory.stocktakes
  - inventory.sites_and_locations
  - compliance.nz_alcohol_records
related_operations:
  - compliant_compliant_api_get_excise_position
  - stocktake_get_stock_position
  - stocktake_get_stocktake_reconciliation
features:
  - compliant
---
# Excise position

## What it means

The position is where the organisation stands with Customs right now:

- **The year**: duty over the last twelve months, as lodged duty plus estimates for finished periods not yet lodged, against the thresholds for six- and twelve-monthly lodging.
- **This period**: litres of alcohol so far, an estimate when the entry is complete, and the due date.
- **Unlodged and overdue periods.**
- **Stocktake**: when the next count is due and how many differences are open, with their duty.
- **Remissions**: breakages from stocktakes the owner may claim a remission for.
- **Setup**: active alcohol products and those missing pack volume or an excise category.

## How the records relate

Stock position and stocktake reconciliation tie the physical count to what was declared. Reconciliation uses the same removals as excise entries.

## Authoritative operations

- `compliant_compliant_api_get_excise_position`: the summary.
- `stocktake_get_stock_position`: stock by place and batch with litres of alcohol.
- `stocktake_get_stocktake_reconciliation`: one count against the books.

## Do not assume

- **The year's figure mixes lodged and estimated duty.** Report both parts.
- **A threshold flag is not a decision.** It says what the choice of frequency allows.
- **Estimates need complete setup.** With incomplete products the period estimate is empty, not zero.
- **Remissions are for the owner to claim.** Biz-E lists them and claims nothing.
