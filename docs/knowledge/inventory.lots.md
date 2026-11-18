---
topic: "inventory.lots"
title: "Lots of stock"
domain: "inventory"
summary: "A lot is one stock record: a name, a quantity in a unit, a type and where it came from. There is no separate product record."
related_topics:
  - inventory.availability
  - inventory.units_and_packs
  - inventory.untracked_items
  - production.intermediates
  - traceability.back
related_operations:
  - core_list_inventory
features: []
---
# Lots of stock

## What it means

A lot is one row of stock. It has a name, a `quantity`, a `unit` and an `inventory_type`:

- `raw_material`: ingredients, packaging and other inputs.
- `work_in_progress`: an intermediate made by a step that is not the last one.
- `final_product`: finished goods, made by a workflow's last step or added by hand.

`quantity` is what is on hand now. Only recorded events change it: adding stock, a step using it, a sale being matched, wastage, a stocktake correction or a transfer. Each event carries a reason.

A lot also carries the supplier, the supplier's own batch code (`supplier_batch_number`), a `barcode`, `purchase_date`, `expiry_date`, its site and stock area, and `extra_data` for notes, a pack, a label batch number and flags.

## How the records relate

- A lot made by a batch points at that batch, the step and the workflow output that made it (`source_execution_id`, `source_execution_step_id`, `source_output_id`). Stock added by hand has none of these, so a trace ends at it.
- Core has no product record. A product is a name, and for made stock the workflow output id. One product normally has many lots, one per delivery or batch.
- Adding stock with a barcode that already exists in the organisation adds to that lot instead of creating a new one.
- Customer-owned material (contract manufacturing) is a lot with a customer set. It is raw material only. It appears in the list, but it is not the producer's stock: sales matching, planning's own-stock figures and stock value leave it out, and its cost is zero.

## Authoritative operations

`core_list_inventory` lists lots with their `quantity`, `unit`, `inventory_type`, `expiry_date`, `ready_date_display`, `quality_hold`, `committed` (planned batches holding it) and `system_findings`. The default list leaves out lots with nothing left. `view=compact` does not, and it carries no holds or findings.

## Do not assume

- **Same name is not the same lot.** Lots of one name differ in batch, expiry, site, hold and cost. Do not add quantities across units.
- **`raw_material` does not always mean bought in.** Stock added by hand can be any of the three types.
- **A lot with quantity is not necessarily usable.** See inventory.availability.
- **Quantities are decimal strings.** Keep them as text and keep the unit with them.
- **Zero-quantity lots still exist.** They stay in the trail. The default list hides them, and traces include them.
