---
topic: "inventory.expiry"
title: "Expiry"
domain: "inventory"
summary: "Bought-in stock has an expiry date on the lot. Made stock gets its expiry from the step that made it, not from that field."
related_topics:
  - inventory.availability
  - inventory.ready_dates
  - traceability.forward
related_operations:
  - core_list_expired_materials
  - core_list_inventory
features: []
---
# Expiry

## What it means

There are two separate kinds of expiry.

1. **A date on the lot.** `expiry_date` is entered when stock is added by hand, by CSV or when a purchase is recorded. It is meant for bought-in material.
2. **An expiry rule on a made output.** A workflow step's output can carry a custom expiry: `fixed_duration` (the step's completion time plus a duration in hours, days, weeks or months) or `set_at_execution` (the person enters a duration or an expiry date-time when completing the step, stored on the lot as `extra_data.custom_expiry_actual`). Completing a step does not fill the lot's `expiry_date` field, so on a made lot it is usually empty.

Each rule can have a warning window. A made lot inside it is flagged amber, and past expiry is flagged red.

## How the records relate

- The expired-materials check takes raw-material lots that have an `expiry_date` in the past and quantity above zero. For each one it lists the products that trace forward from it and were made after it expired.
- Made-output expiry shows up as a `system_findings` entry on the lot in `core_list_inventory`. It is a risk signal only: it never changes the lot's quantity or status.
- Planning leaves a lot out of available stock when its `expiry_date` has passed. See inventory.availability.

## Authoritative operations

- `core_list_expired_materials`: expired raw materials with stock, and the products made from them after the expiry date.
- `core_list_inventory`: each lot's `expiry_date`, and its `system_findings` for expired-material and output-expiry findings.

## Do not assume

- **An empty `expiry_date` does not mean a lot never expires.** A made lot's expiry comes from its step's rule.
- **The expired-materials list is not a full recall list.** Products must still hold stock to appear, because the check drops zero-quantity lots. Products made before the raw material expired are left out on purpose. For everything a material went into, use the forward trace (traceability.forward).
- **Only raw-material lots are checked for an expired date there.** Expired work in progress or finished goods is not reported by that operation.
- **Expiry does not stop a sale.** Matching a sale to a lot does not check expiry. The expiry checks are signals only and never change a quantity.
- **Months are approximate in places.** A duration in months is about 30 days when the rule is validated, so quote the computed expiry the app returns.
