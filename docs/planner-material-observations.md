# Material observations for proposed batches

This is a bounded 7.3d adapter on the persisted board. It records exact-lot raw
recipe bindings and historical material evidence. It does not reserve stock,
publish delivery forecasts or clear execution starts.

## Exact bindings

In workflow planning settings, select an exact raw lot for each external raw
input. The saved binding contains the workflow step UUID and input position,
the lot UUID, exact native quantity and unit. The existing process version and
workflow digest pin that position and recipe. New batches freeze these bindings;
changing settings leaves existing batches intact. Saving timings without a binding
field preserves existing bindings only while the definition is unchanged.

The server resolves every selected lot inside the authenticated organisation and
requires raw material and the exact input unit. Names, barcodes, labels and
supplier batch numbers never become product identities or replacement rules.
Another lot with the same name cannot satisfy an exact binding. Internal workflow
links are handled by the same physical batch's recipe; external intermediate
inputs, incoming deliveries and dependent production remain unresolved.

Manual demand currently requires producer-owned inputs. Only the persisted
`InventoryItem.contract_customer_id` column can establish ownership: null means
producer, while a customer UUID cannot satisfy this adapter. Missing owner schema
and legacy JSON ownership hints stay unresolved. No customer receipt or title
feature is activated here.

## Authority and uncertainty

**On-hand quantity is an observation, not an available balance.** The default
`resolve_availability` boundary always reports unresolved commitments, holds and
readiness because no authoritative reservation/hold adapter exists in this slice.
An empty query, a pending execution, another planner request or JSON flags cannot
establish uncommitted usable stock. No date is inferred from purchase date,
missing ready data or an arbitrary `ready_date_actual` field.

A future trusted server adapter must return a finite nonnegative Decimal available
balance no greater than the observed on-hand quantity, a known day-level ready
date, and no unresolved restrictions. It must inspect current commitments, holds,
transit/receipt authority and readiness together. Legacy transit/hold/commitment
metadata requires authoritative review, including apparently clear zero/false
values. The production boundary remains closed even when ownership schema lands.
Tests replace only these explicit server boundaries to exercise future known
availability; there is no HTTP clearance field or production bypass.

When trusted facts are complete, the material engine assesses all live unstarted
batches in proposed-date/priority order, sharing local balances across requests.
It matches exact lot, site, producer owner and unit. Per-batch trials are atomic,
expiry is inclusive, and no lot can be overallocated in the assessment. Known
readiness can move a material-only date. An uncovered shortage or unknown mapping
keeps the date null. Unknown output readiness also keeps the material timing
estimate null. The engine's recipe slot uses physical batch identity so different
frozen generations can refer to different exact lots without conflation.

## Historical evidence and UI

**Check materials** writes one assessment with its sequence/time, observations and
per-batch results. Same-organisation composite foreign keys link results to their
assessment and physical batch. API mutations require `production.record` and real
Flask-WTF CSRF; reading requires `production.view`. Assessment and actor audit
commit together. Organisation locking serialises sequence assignment and concurrent
planning changes. Stock is read and never written or reserved.

The board shows observed on-hand quantities and unresolved reasons. Any eventual
known material date is labelled as material availability and a timing estimate
with those materials. It is a historical observation: refresh after stock changes.
Batch revision/status or normal process-version changes mark prior results stale.
No automatic stock-event invalidation or replan is claimed. Assessment records are
append-only through the API; there is no edit/delete route.

`PlanningBatch.forecast_ready_date` remains null, and its start check still blocks
for materials, capacity and site compliance. Known materials alone never start
production or publish an order/portal date. The actual adapter conservatively
keeps raw-stock assessments unresolved until authoritative availability exists.

Bounds: 1,000 live physical batches and 1,000 exact lots per assessment; excessive
catalogues are rejected rather than partly assessed. The settings selector lists
at most 500 lots and retains an existing saved binding outside that list. Queries
prefetch workflow/version/lot facts instead of reading them per batch.

## Integration

The new additive migration `planner_material_forecasts_001` follows the published
!440 `planned_batches_001`. This child branch does not edit !440/!425 or change
their ancestor revisions. !425 is now merged, and the deployed ordering includes
`custom_roles_001 → planner_demands_001 → contract_orders_001` from !426. The merge
train must restack !440's old site/demand ancestor to respect that history before
upgrading this child. Do not silently move an already-applied demand ancestor.

Full 7.3d stays open: authoritative commitments/holds/readiness, raw product
identities beyond exact lots, intermediate supply and recipes, expected supplier
delivery records, capacity/compliance, reservations and published forecasts remain.
