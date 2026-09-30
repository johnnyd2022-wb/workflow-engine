# Production planning

The persisted manual-demand board is documented in
[planned-batches.md](../../../docs/planned-batches.md). Its proposed dates remain
separate from delivery forecasts and production clearance.

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

## Material availability engine (7.3d, partial)

`materials.assess_materials` applies a separate material check to the arithmetic
engine's `PlannedBatch` tuple. It expands each group's `batch_count` into physical
batches and preserves caller order, including demand priority. Each result carries
its group demand ID and one-based batch number; adapters must keep demand IDs
unique within a snapshot. There is a 10,000 physical-batch limit per assessment.

Callers provide an authenticated `org_id`, `today`, and immutable tuples of:

- `MaterialRecipe`: organisation, workflow, exact output `StockKey`, and input
  quantities **per physical batch**, already converted to the input key's unit.
  Duplicate input keys are summed. An explicit empty recipe requires no material;
  a missing recipe is unknown and blocks the batch.
- `MaterialSupply`: organisation, an existing `Supply` snapshot, and an explicit
  `MaterialSource` (`ON_HAND`, `INCOMING`, or `SCHEDULED_PRODUCTION`). Quantities must
  be available after other commitments. The adapter must authenticate the
  organisation, verify ownership/site access and delivery or production status,
  exclude quarantine/transit, and provide known readiness dates. Unknown or
  unconfirmed replenishment must not be supplied as a guessed arrival.

Recipes and supplies from another organisation are rejected, as are duplicate
supply IDs, ambiguous recipes and invalid quantities/dates. Product, unit, site
and owner match exactly; `None` is a specific scope, never a wildcard. A recipe can
explicitly require customer-owned material, but producer stock or another
customer's stock cannot satisfy that key. The upstream batch tuple has no tenant
field, so its authenticated tenant filtering remains the adapter's responsibility.

All inputs are consumed at the batch's **start**, conservatively before any
workflow steps run. A lot is eligible when ready on or before that day and expires
on or after it. Each trial uses FEFO (expiry, then readiness, then supply ID).
Expired stock is never used to satisfy a past requested start: checks begin at
`max(today, planned_start_date)`. Material consumption at individual workflow
steps, capacity and compliance constraints are later stages.

Trials are atomic for all inputs. A successful trial reduces only local forecast
balances; a failed trial or blocked batch consumes nothing. If inputs are short,
the engine checks the known matching supplies' readiness dates for the earliest
common feasible start, then moves the ready date by the same elapsed duration.
Results include per-lot quantities and source types, shortages at the checked
start, and reasons naming the missing input and known supply that caused a delay.

For example, two physical batches each need 5 kg of juniper. With 5 kg available
now and 5 kg explicitly arriving in three days, the first keeps its start and the
second moves three days later. With only 7 kg and no known receipt, the first uses
5 kg; the second is blocked, has no start/ready forecast, and leaves 2 kg unused.
An input that expires before another arrives also blocks the batch: taking the
latest arrival date alone would overstate availability.

`earliest_start_date` and `forecast_ready_date` are `None` for blocked results.
These are material-only forecasts, not delivery promises. The returned balances
and allocations are read-only assessments, not persisted commitments. Calling the
engine again with the same snapshots produces the same result and reserves no
stock. Supply is never inferred from the assessed output batches: trusted known
scheduled production must be passed explicitly, and dependency construction
belongs to a later adapter.

This slice adds no delivery records, database migrations, API routes or planning
persistence. Expected supplier-delivery persistence, current inventory/recipe
adapters, dependent-production planning and integration with published forecasts
remain open in 7.3d.
