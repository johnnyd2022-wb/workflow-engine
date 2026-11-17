---
topic: "inventory.availability"
title: "Available stock versus on-hand"
domain: "inventory"
summary: "On-hand is the recorded quantity. Whether it can be used depends on holds, ready dates, expiry, spoken-for quantity, owner and site."
related_topics:
  - inventory.holds
  - inventory.ready_dates
  - inventory.expiry
  - inventory.lots
  - planning.stock_cover
  - sales.fifo_matching
related_operations:
  - core_list_inventory
  - core_list_output_ready_date
  - lot_holds_get_lot_holds
  - lot_holds_list_open_holds
  - planning_get_stock_cover
  - stocktake_get_stock_position
features: []
---
# Available stock versus on-hand

Never assume that all physically present stock is usable.

## What it means

**On-hand** is a lot's recorded `quantity`. **Available** is the part that can be used now. Core has no single `available` field on a lot. The difference comes from these things, each held separately:

- **Open quality hold.** A held lot cannot be used in a step, matched to a sale, sent to a tasting, dispatched to a contract customer or split for a transfer.
- **Ready date not reached.** A step will not take a lot before its ready date unless the person confirms.
- **Past expiry.** Planning leaves out a lot whose `expiry_date` has passed.
- **Spoken for.** Quantity recorded as an input on a step that is not finished stays in `quantity` until the step completes. Planning subtracts it. Planned batches can also commit a lot (`committed` on the list).
- **Owner.** Customer-owned material is not the producer's stock.
- **Site.** Planning counts stock per site.
- **Flags.** Planning also treats a lot flagged `on_hold`, `quarantined` or `in_transit` in its extra data as unavailable.

## How the records relate

`core_list_inventory` shows on-hand plus `quality_hold`, `committed`, `ready_date_display`, `expiry_date` and `system_findings` for each lot. Together these let you say why a lot cannot be used. `lot_holds_list_open_holds` and `lot_holds_get_lot_holds` give the holds in full. `core_list_output_ready_date` lists made lots that are on hand but not yet ready.

## Authoritative operations

- Product-level "how long will it last": `planning_get_stock_cover`. Its `available` is stock on hand (as defined above, per site and owner) plus the output of live batches that are not blocked, less open demand that is not a forecast. Its run-out date counts each batch only from its ready date.
- Where stock physically is, by place and batch: `stocktake_get_stock_position`. It lists what is recorded as there, including held and not-yet-ready lots. It is a position, not availability.
- Why one lot cannot be used: `core_list_inventory`, `lot_holds_get_lot_holds` and `core_list_output_ready_date`.

## Do not assume

- **There is no `available` number to read off a lot.** Do not compute one from `quantity`. Say which of the reasons above apply.
- **Stock cover does not wait for ready dates.** Planning counts each in-stock lot as ready today, so a lot that is still resting or maturing can be inside a cover figure. Check `core_list_output_ready_date` before promising it.
- **Sales matching does not check expiry or ready date.** It skips held lots, customer-owned lots and zero quantity, and takes the next lot by label batch number.
- **A commitment warns; it does not block.** Using a committed lot in another batch is allowed.
- **A held lot can still be counted, moved whole or written off.** A hold stops use, not stocktakes or wastage.
- **An empty hold list means no holds, not "all stock is fine".**
