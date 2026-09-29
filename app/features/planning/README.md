# Production planning

The first slice is an arithmetic engine for roadmap 7.3b/c. It calculates net
requirements, rounds shortfalls to configured batch sizes, and dates batches using
the workflow's critical path. These dates are theoretical lead-time dates until the
material, capacity and compliance stages have also run. They are not customer
promises.

## Input contract

Callers supply immutable snapshots for one authenticated organisation. Product
identity is a stable output/product identifier, never a product label. Keys also
include compatible unit, site and stock owner. Convert units before calling the
engine; a case cannot substitute for a bottle without an explicit conversion.

Supply quantities are available balances after existing commitments. Shelf stock
and WIP must be distinct sources, with known ready dates. Exclude transit,
quarantine, cancelled production and unconfirmed supplier deliveries. If a WIP
completion date is unknown, report that uncertainty rather than guessing today.
Customer-owned materials cannot become producer-owned supply by omitting ownership.

Demand is processed by due date, then descending priority, then stable demand ID.
Eligible supply is consumed first-expiring first, and only once. Expiry is inclusive
of the expiry date. Overdue orders use today's date for eligibility so yesterday's
expired stock cannot fulfil them. Manufactured surplus can cover a later demand
only after the planned batch's ready date.

Workflow timing uses dependencies rather than summing parallel branches. Include
expected work, waiting and configured output readiness in the supplied timings;
the engine never changes the existing execution readiness rules. Day-level dates
round a fractional day upwards. Backward planning starts no earlier than today;
an impossible deadline produces a late date and a reason.

## Integration sequence

1. Persist demand, workflow timing and planned batches with tenant-scoped APIs.
   Resolve contract order line IDs through the contract feature's demand adapter;
   ordinary sales orders and targets need their own adapters.
2. Apply material availability, expected receipts, expiry and dependent batches.
3. Apply resource calendars, pinned dates and generic module constraints.
4. Publish versioned forecast dates and reasons to orders and the portal. Starting
   a real execution requires an explicit transaction, never this engine call.
5. Add the week/month board, replan triggers and today's dashboard projection.

There are no routes, database mutations, stock reservations or background replans
in this first slice. The remaining stages stay unchecked in the roadmap.
