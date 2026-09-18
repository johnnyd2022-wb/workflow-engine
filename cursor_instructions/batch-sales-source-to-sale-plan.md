# Source-to-sale traceability — batch IDs + sales wiring plan

## Status (2026-09-19)
§1/§2 (batch id + custom execution metadata on the trace) are **built** — see "Implemented"
note at the top of each section below; the `Execution.batch_label` column proposed in the
original §1 draft was **not** built: the real canonical batch id turned out to already exist
(the step-level "Batch number" compliance/traceability prompt, `execution_prompts`), so no
new column or migration was needed. §3 (sales wired into the DAG) is being built by a
separate agent in parallel — left as-is below for reference, not being worked here.

## Why this doc exists
Ask: "sourcemap should carry batch IDs and other execution metadata on traces, and show
sales that are wired up — may need sales wired into the DAG." Findings below are from
reading the code as it stood on this branch, 2026-09-19, before §1/§2 were built.

## tl;dr
- The sourcemap trace itself (`app/core/backend/dagtraversal.py`,
  `temporal_dag_tracer.py`, `/core/sourcemap`) is solid — reviewed 2026-08-09, well tested,
  don't rebuild it.
- **Batch identity is not canonical.** Three different, incompatible "batch" concepts
  already exist in the live code, none of them fit for a clean source-to-sale key. See
  §1.
- **Sales are not wired into the DAG at all**, beyond a product-*name*-level Xero mapping
  that never touches a specific inventory item, execution, or batch. `SalesTraceabilityConfig`
  (fifo/manual/hybrid) is UI-configurable but nothing reads it — there is no matching
  engine behind it. See §2.
- CLAUDE.md's `workflow_engine_bp` ("lineage tracing", flag `workflow_engine_enabled`) is
  dead: the blueprint doesn't exist in this repo, and `.agents/feature-index.md` itself
  flags the flag as legacy. Its `workflow_parent_executions` table (with
  `execution_batch_id` / `sales_mapping_status` columns) is created by `app/initialize.py`
  and read/written nowhere else — this is almost certainly the "I think this already
  builds it all?" instinct; it doesn't, and nothing should be built on top of it.

---

## §1 — Batch identity today (why it's not one field)

**Implemented 2026-09-19, superseding the recommendation below.** The real canonical batch
id was already in the codebase, just not surfaced on the trace: the process/step builder
("Compliance & Traceability" section, `create-process-modal.js`) already lets a step
declare a reserved `execution_prompts` entry labeled exactly `"Batch number"` (matched
case-insensitively — see `deriveTraceabilityModes`/`isBatchNumber` in
`create-process-modal.js` and `isTraceabilityOrSystemPrompt` in `flows2-steps.js`). Whoever
completes that step types the batch id into that prompt; it lands in
`ExecutionStep.execution_data["Batch number"]` (and, via `execution.step_completed`, in the
`entity_events` payload used by the temporal tracer). So the fix was extraction, not a new
column: `app/core/backend/dagtraversal.py::_split_trace_prompts` pulls it out of
`step.execution_data` and promotes it to a top-level `batch_id` field on every trace item
(`_item_to_dict`), and `temporal_dag_tracer.py::_split_temporal_prompts` /
`_collect_node_metadata` do the same for every node in a temporal replay (previously only
the root node had populated state at all — AC17 already covers `state` itself, untouched
here; `batch_id`/`custom_prompts` are new, separate fields). `supplier_batch_number` is
unchanged and still the right field for genuine raw-material supplier lot codes.
`sourcemap.js` now shows `batch_id` (falling back to `supplier_batch_number`) on the impact
header, item cards, map tree nodes, and the table view. Not extended: the Batches
browse/search tab still reads `GET /api/core/inventory`'s `supplier_batch_number` only,
since that's a different endpoint (`inventory_repo.py`) than the trace serializer — WIP/final
batch ids aren't browsable/searchable pre-trace yet, only visible once a trace is run.

| Where | Field | What it actually means | Populated by |
|---|---|---|---|
| `InventoryItem.supplier_batch_number` (String) | the schema's only real "batch" column | genuine supplier lot code, **raw materials only**, by design | manual entry / CSV import for raw materials |
| same column, overloaded | — | `scripts/whistlebird_migration.py` also writes the VAT batch label (`"VAT55"` etc.) here for **WIP and final products**, because it's the only string field on the item | backfill/import script only — **not** the live "complete a step" UI path |
| `InventoryItem.extra_data["batch_label"]` | duplicate of the above | same VAT label, redundant copy | same backfill script only |
| `ExecutionStep.execution_data["batch_ref"]` (`BATCH_MARKER_KEY`) | idempotency marker | groups rows for re-import safety, not user-facing | same backfill script only |
| `InventoryItem.extra_data["batch_number"]` (int) | a *label/lot* number, e.g. "this is physical print-run #12 of 500 labels" | explicitly **not unique per (org, name)** — one physical batch can span several executions (`backend.py:2832-2844`) | live UI, when a step's output form includes `batch_number` |
| `workflow_parent_executions.execution_batch_id` | dead column | legacy schema, table created by `initialize.py`, read/written nowhere else in the app | nothing — vestigial |

Net effect: **only backfilled Whistlebird history has a batch id that shows up in the
trace today** (via `supplier_batch_number`, which `dagtraversal.py::_item_to_dict` already
returns). Anything completed live through the normal execution flow gets no batch
identifier at all on its WIP/final inventory rows — `Execution`/`ExecutionStep` have no
batch column, period. The one live field that exists (`extra_data.batch_number`) means
something different (a label print-run) and is unsuited to be the source-to-sale key.

### Recommendation
Add a single canonical field: **`Execution.batch_label`** (nullable `String(255)`).
Rationale: the whole domain already treats "one physical production batch = one
execution" (see `whistlebird_migration.py`'s own comment: *"Each production batch (one
VAT) is a single execution"*), so the batch identity belongs on `Execution`, not
duplicated onto every `InventoryItem` it produces. Trace/read paths resolve an item's
batch via its existing `source_execution_id` join — no denormalization needed for reads
that already load the execution (which `dagtraversal.py` does).

- Migration (Alembic, nullable — no backfill required to ship): add the column.
- One-time backfill script (separate from the migration, per this repo's
  migration-safety convention) copies `supplier_batch_number` /
  `extra_data.batch_label` into `Execution.batch_label` for existing Whistlebird
  executions, keyed by the existing `ExecutionStep.execution_data["batch_ref"]` marker
  so it's idempotent.
- Execution-start UI/API gets an optional `batch_label` input; if left blank, auto-suggest
  `f"{process.short_code}-{date:%Y%m%d}"` or similar so live executions aren't left blank
  by default.
- `InventoryItem.supplier_batch_number` stops being overloaded going forward — reserved
  for genuine incoming supplier batch codes on raw materials only, as originally named.
- `extra_data["batch_number"]` (the label lot count) is untouched — different concept,
  keep it, just don't conflate it with the new field in UI copy.

This is a decision the user should confirm before it's built — flagging it, not assuming
it: alternative is to keep overloading `supplier_batch_number` and just rename/document
it, which is less correct but touches nothing outside `dagtraversal.py`'s serializer.

---

## §2 — Execution metadata already available vs. what's exposed on the trace

**Implemented 2026-09-19.** Everything an org captured via its own custom `execution_prompts`
(anything on a step that isn't the reserved "Batch number"/"Evidence" prompts) now rides
along as `custom_prompts` on every trace item and temporal node, alongside `batch_id`.
`sourcemap.js`'s item-card detail grid renders each custom prompt as its own row. Not done:
`completed_by`/`execution_status` as dedicated trace fields (they're partly available today
via `execGroup.operator`/`step_data`, not touched here) — small enough to fold into this same
change later if wanted, but out of scope for what was asked this round.

`dagtraversal.py::_item_to_dict` (current-state trace) already returns, per item: name,
quantity, unit, inventory_type, supplier, purchase_date, `supplier_batch_number`,
expiry_date, `source_execution_id`/`source_execution_step_id`/`source_step_name`,
`process_name`, `created_at`, and `extra_data` (raw JSONB passthrough). `step_data`
(`completed_at`, `actual_inputs`, `actual_outputs`) is hydrated separately per AC5.
`completed_by` is already extracted for the Operators tab (sourcemap-v2 §7d) but not
attached to individual trace items.

`temporal_dag_tracer.py` carries **none** of this — non-root nodes are always
`state: None` by design (AC17), so a temporal ("as of a past date") trace today can't show
batch id, operator, or any execution metadata at all, even though the live trace can.

### Plan
- Add `batch_label` (via the new `Execution.batch_label`, §1) and `completed_by` to
  `_item_to_dict`'s output for the current-state trace — small, additive change, same
  bulk-fetch pattern already used for `process_name`/`step_data` (no new N+1).
  `execution_status` too, since "was this batch actually finished" is metadata a trace
  viewer will want.
- Add batch_label to `GET /api/core/sourcemap/objects` so WIP/final items become
  batch-searchable (today only raw materials reliably are, since only they have
  `supplier_batch_number` from live data entry).
- Temporal tracer: extend `_snapshot_at`/node hydration to resolve `batch_label` for
  every node with a pre-`as_of` event, not just the root — currently only the root gets
  any state at all. Scope this carefully against AC17's existing tenant-isolation fix
  (§AC9/F1 in `.agents/reports/traceability/security-audit.md`) — any new per-node lookup
  must stay `org_id`-scoped or it reopens that exact class of bug.
- Frontend (`sourcemap.js`): timeline/map/table item cards show the batch chip; the
  existing "Batches" autocomplete category (`smTraceByBatch`) switches from scanning
  `supplier_batch_number` across items to querying the canonical field.

---

## §3 — Wiring sales into the DAG (the real gap)

**Not touched here — a separate agent is building this in parallel (2026-09-19).** Left as
written for reference/context; do not build against this section without checking its
current state first, since it may already be superseded by that work.

Confirmed nothing links a sale to a specific batch/execution/inventory item today:

- `ProductMapping` links a **product name** to a **Xero invoice line-item description
  pattern** (string match), plus an optional `biz_e_source_output_id` — which identifies
  a *process step's output definition* ("step X of process Y produces Sourdough Loaf"),
  not any specific instance/execution/batch of it.
- `XeroInvoiceLineItem` has **zero FK** to `InventoryItem` or `Execution` — just Xero's
  own fields (description, item_code, quantity, tracking).
- `SalesTraceabilityConfig` (`matching_strategy` ∈ fifo/manual/hybrid, `matching_key`
  defaulting to `"batch_id"`) is a fully-built settings CRUD surface
  (`GET`/`PUT /api/crm/traceability-config`) — but grepping the entire repo for
  `matching_strategy` outside that config's own get/set code returns nothing. **No
  matching engine exists.** The settings page promises a capability the backend never
  delivers.

So today you can see "Sourdough Loaf sold $X this month" (product-level analytics) but
never "which physical VAT/batch fulfilled invoice #123, and which raw botanicals fed it."
That's the piece that needs building, and it's the part of this ask most likely to need
a proper spec (`/spec-first`) before code, since it adds new tables and crosses the
`traceability`/`core` slice and the `crm` slice — the feature-index's slice-boundary
convention (`.agents/feature-index.md`) treats those as separately owned.

### Proposed shape

1. **New table** `crm_sale_batch_link` (org-scoped, `TenantScoped`):
   `xero_invoice_line_item_id` FK, `inventory_item_id` FK (the specific final-product
   batch instance) or `execution_id` FK, `quantity_matched`, `matched_by`
   (`fifo_auto`/`manual`/`hybrid_auto`), `matched_at`, `matched_by_user_id`.
2. **New service** `app/features/crm/services/sales_batch_matcher.py`, driven by the
   already-existing `SalesTraceabilityConfig`:
   - `fifo`: for invoice line items already resolved to a product via `ProductMapping`,
     consume final-product `InventoryItem` rows of that output type oldest-first (by
     `created_at`) up to the line's quantity; write `crm_sale_batch_link` rows.
   - `manual`: unmatched lines go to a review queue (the config's existing
     `manual_review_days` field already anticipates this — currently unused for
     anything).
   - `hybrid`: auto-FIFO, flagged for confirmation when ambiguous (spans multiple
     batches, or `strict_mapping` is off with no `ProductMapping` match).
   - Hook into the sync points `crm_service.py` already has: after
     `XeroSyncService` full/incremental sync, and the best-effort incremental sync that
     already fires after a local invoice create/authorise.
3. **Trace-side surfacing**: a final product's forward trace response gets a `sales`
   array (customer name, invoice number/date, quantity, matched_by) sourced from
   `crm_sale_batch_link`. This is the literal "show sales that are wired up" ask — lands
   in `dagtraversal.py`'s final-item enrichment, reading (not writing) the CRM slice's
   new table, same cross-slice read pattern the spec for `traceability` already uses for
   `entity_events` (owned by `platform`).
4. **Frontend**: timeline/map "Sold to" chip on final-product cards, linking to
   `/crm/customers/<id>`.

### Open decisions (need your call before this gets built)
- Batch id source of truth: new `Execution.batch_label` column (recommended, §1) vs.
  continuing to overload `InventoryItem.supplier_batch_number`.
- Ship order: §1+§2 (batch id + richer trace metadata) is low-risk, additive, one slice
  (`core`/traceability) — could land as its own feature first. §3 (sales-to-batch
  matching) is bigger, adds a table, and crosses into `crm` — worth its own spec/feature
  rather than bundling, unless you want it all in one pass.
- Matching aggressiveness for the first release of §3: auto-FIFO-match on every sync
  (fast, but a wrong auto-match is now sitting in a compliance-relevant trace) vs.
  manual-confirm-only for v1 (slower to populate, zero false positives). Given this is
  used for audit/compliance-style traceability (per `compliance-project-assistant`'s
  domain), I'd lean manual-confirm-first with FIFO as a suggestion, not an autocommit —
  but that's your call to make, not mine.

---

## Suggested execution path
Given the scope and that it touches two owned slices (`traceability` in `core`, and
`crm`), route this through `/spec-first` → build, the same chain
`.agents/specs/traceability.md` and `.agents/specs/crm.md` were both produced under —
rather than a single ad hoc patch. §1+§2 could be spec'd and shipped as one feature;
§3 as a second, since it's the part with real design decisions (matching semantics)
still open above.
