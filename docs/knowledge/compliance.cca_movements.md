---
topic: "compliance.cca_movements"
title: "CCA movements"
domain: "compliance"
summary: "A CCA is a Customs-controlled area. Excise-unpaid moves between CCAs are recorded and shown per licence, apart from removals for duty."
related_topics:
  - compliance.excise_periods
  - inventory.sites_and_locations
related_operations:
  - compliant_compliant_api_get_excise_period
features:
  - compliant
---
# CCA movements

## What it means

A CCA licence covers an area where excise-unpaid alcohol can be held. Goods leaving a CCA are either transferred to another CCA, staying excise-unpaid, or entered for duty. Nothing falls between the two.

A sale to another business's CCA, such as a duty-free shop or an export warehouse, is a **transfer**, not a removal. It is left out of the duty lines and listed under `cca_transfers` in the excise entry with its movement-register status.

## How the records relate

- Physical movements between sites are recorded as dispatch, transit and receipt. A partial receipt refers to the original dispatch and does not create a second charge.
- A movement register groups recognised excise-unpaid movements by source CCA and marks anything with missing or mismatched proof as unresolved. It is always marked incomplete: it cannot declare a nil return or a total.
- A producer-liable removal from a CCA for home consumption shows only observed excise due, not paid or lodged.

## Authoritative operations

`compliant_compliant_api_get_excise_period` returns `cca_transfers`, the CCA list for the period and, with `cca`, one licence's entry. The separate movement register is not available to assistants.

## Do not assume

- **A transfer is not a sale for duty.** Do not add it to duty.
- **Excise-unpaid is not excise-paid.** Duty-paid return stock is not turned back into excise-unpaid.
- **A register total is not a lodgement.** Levy, GST and other removal sources are not reconciled in it.
- **A site is not a CCA.** A licence can cover several sites.
