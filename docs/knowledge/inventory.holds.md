---
topic: "inventory.holds"
title: "Quality holds"
domain: "inventory"
summary: "A hold stops a lot being used until someone releases it with a note. Holds are kept as history and never deleted."
related_topics:
  - inventory.availability
  - traceability.forward
  - inventory.stocktakes
related_operations:
  - core_list_inventory
  - lot_holds_get_lot_holds
  - lot_holds_list_open_holds
features: []
---
# Quality holds

## What it means

A hold is a quality record on one lot, such as a failed test or a cloudy batch. While it is open the lot cannot be **used**:

- in a production step;
- matched to a sale;
- sent to a tasting;
- dispatched to a contract customer;
- split off by a transfer.

A hold needs a reason (up to 500 characters). Releasing it needs a note saying why, for example "retested and passed". A release closes the hold and keeps who, when and why. Rows are never deleted, so a lot's history reads "held, then released".

## How the records relate

- A lot has at most one open hold, and any number of released ones.
- A hold can be placed on a lot together with lots made from it. Each extra hold records which hold it came from (`source_hold_id`). Releasing is per lot, so releasing the first does not release the others.
- Opening a product recall places holds. Placing a hold needs inventory adjust permission, and releasing one needs compliance manage permission.
- Planning and sale matching skip held lots up front, so a sale goes to the next lot. The block on use is also enforced where every stock quantity change is saved.

## Authoritative operations

- `lot_holds_list_open_holds`: lots currently on hold, newest first (up to 1,000), with the reason, when it was placed and the lot's name and quantity.
- `lot_holds_get_lot_holds`: one lot's full hold history, open and released.

`core_list_inventory` also shows an open hold as `quality_hold` on each lot, but only in its full view.

## Do not assume

- **A held lot is not gone.** It stays in on-hand quantity, stocktakes and the stock position. A hold stops use, not counting, moving the whole lot, writing it off, reversing a sale or receiving more stock into it.
- **A hold on a lot does not hold the lots made from it unless they were held too.** Use the forward trace to find them (traceability.forward).
- **A released hold is not an open one.** Check the `open` flag before saying a lot is held.
- **A missing hold is not a quality pass.** It means nobody recorded a hold.
