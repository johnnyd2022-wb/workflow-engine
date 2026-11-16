---
topic: "inventory.units_and_packs"
title: "Units and packs"
domain: "inventory"
summary: "Each lot has one unit; measured units convert within their kind, counted units are whole numbers, and a pack says what one unit holds."
related_topics:
  - inventory.lots
  - production.inputs_and_outputs
  - costing.cost_status
related_operations:
  - core_list_inventory
features: []
---
# Units and packs

## What it means

Every lot has exactly one `unit`. Units come in kinds:

- mass: `kg`, `g`, `mg`, `lb`, `oz`, `ton`, `tonne`;
- volume: `L`, `mL`, `gal`, `m3`, `ft3`;
- length: `m`, `cm`, `mm`, `ft`, `in`;
- counted: `units`, `pcs`, `pieces`, `boxes`, `pallets`, `containers`, `bottles`, `cans`, `kegs`, `cases`.

Measured units convert within their own kind (kg to g, L to mL). Counted units convert only to themselves. Counted quantities must be whole numbers: half a bottle cannot be recorded.

A **pack** says what one unit of a lot holds. It is stored on the lot as a count of containers and an optional size, for example 24 containers of 200 mL per case, a 25 kg bag, or a box of 500 pieces. With a pack, a step can use a lot of cases in bottles or in mL, and cost can be broken down per case, per bottle and per litre.

## How the records relate

- Ordinary conversion always wins. A pack is used only where ordinary conversion cannot apply: counted to containers, counted to volume or mass, measured to containers.
- A pack belongs to the lot. Editing it changes later conversions only. Quantities already recorded keep the numbers they were written with.
- When a run of counted product does not divide into whole bottles, the whole bottles are recorded as the output. The remainder is entered separately in mL, as stock named "<product> - Library stock". Library stock is new stock with the batch's lineage. It takes no share of the batch cost.

## Authoritative operations

The full `core_list_inventory` list returns each lot's `unit` and its `extra_data`, which holds any `pack`. Cost per case, bottle and litre comes from the costing operations, not from dividing yourself (see costing.cost_status).

## Do not assume

- **Do not convert between a counted unit and a measured one yourself.** Without a pack there is no valid conversion.
- **Do not add quantities in different units.** Convert within one kind or report them separately.
- **A fractional bottle count is not valid stock.** Library stock in mL is how a remainder is recorded, and it is created only when a remainder figure comes with the step's output. It is not worked out automatically.
- **A pack with no size is just a count.** A box of 500 labels is a count of 500.
- **A lot with no pack behaves as if there were none.** Do not infer a pack from the name.
