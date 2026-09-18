# Whistlebird API-replay framework — execution plan

Working doc for building a replayable, API-driven loader for `whistlebird_test`, per
Johnny's direction on 2026-09-14. This file is the durable source of truth for this
build across however many sessions it takes — update the checklist as work lands, don't
just report progress in chat.

## Why this exists

The existing `scripts/whistlebird_migration.py` writes directly to the ORM/repository
layer and manually stamps `date_confidence`/`timestamp_policy` markers into
`execution_data`. That's fine for a one-off migration script, but Johnny wants more:

1. **Replay through the real system, not around it.** Every historical event (raw
   material purchase, execution step completion, trial, customs lodgement) should be
   created by calling the actual application code path — the same route → auth →
   validation → repository → ORM chain a real user's browser would hit — so a bad
   record can't get in that the live app itself would have rejected, and the load
   doubles as an end-to-end exercise of the whole system.
2. **No backdating capability added to the live API.** The app must keep behaving
   exactly as it does today — timestamps are always "now" at request time. That's
   correct for production and stays correct after this org goes live. Historical dates
   are applied by a **second, separate script** that runs after replay and rewrites
   timestamp columns directly, keyed off the same import markers used to identify each
   row. This script is explicitly an **internal-only tool for resetting demo tenants**,
   never something exposed to the live app.
3. **No "derived" language anywhere in the loaded data.** `date_confidence`,
   `timestamp_policy: derived_noon_pacific_auckland`, and similar internal-curation
   markers must not appear in anything written to `whistlebird_test` going forward. The
   curation trail (how we know a date is right) stays in `docs/whistlebird-import-*.md`
   and the JSON manifests — never in `execution_data`/`extra_data` on a live row. This
   is a record of truth, not a migration-tracking artifact.
4. **Free byproduct: a demo-reset framework.** Reset the tenant, run the replay, run the
   timestamp correction — same tenant is back to a clean, fully-dated historical state.
   Usable between client demos.

## Architecture

Two scripts, run in sequence:

### 1. `scripts/whistlebird_replay.py` — the replay client

- Drives the app through **Flask's `test_client()`**, not a live server + real network
  auth. This still executes the exact route function, its decorators
  (`@requires_auth`, `@requires_org_scope`), the Pydantic request-body validation, and
  the real repository/business logic — nothing about the code path is faked — while
  avoiding the complexity of managing a live server process, TLS, and external
  rate-limit/CSRF handling from outside the process. `with app.test_client() as
  client:` keeps a cookie jar across requests, so one login covers the whole replay.
- Logs in once as the deterministic test admin (`DEFAULT_TEST_ADMIN_EMAIL`), then issues
  every event as a real request against the real routes, in the order produced by the
  timeline compiler below.
- Every request carries the same `import_ref`/marker convention already established
  (`_import_marker` in `whistlebird_migration.py`) in whatever caller-supplied metadata
  field the route accepts (`execution_data` on step-complete, `metadata`/`extra_data`
  on inventory creation) — used both for idempotency (skip on rerun) and as the
  correlation key the timestamp-correction script uses afterward. **It must NOT
  include `date_confidence` or `timestamp_policy` keys** — only the marker and
  whatever business data the route needs.
- Idempotent: before issuing an event, check (via a lightweight query against the
  target DB, not an API round-trip) whether a row already carries that event's marker;
  skip if so. Re-running the whole script after a partial run (interruption, quota
  limit) must resume cleanly, not double-create or error.
- Fails loudly and stops on the first rejected request (real validation error) rather
  than skipping past it — a rejection means either the curated data is wrong or the
  ordering is wrong, and either needs fixing, not papering over.

### 2. `scripts/whistlebird_replay_correct_timestamps.py` — the after-script

- Runs only after a replay pass completes successfully.
- For every row the replay created (found via the same import markers), sets the real
  historical timestamp on every business-relevant column: `execution.started_at`,
  `execution_step.created_at`/`completed_at`, `inventory_item.created_at`,
  `inventory_movement.created_at`, and whatever compliance/customs record columns
  exist — mirroring the manual-override trick the current script already uses
  (`business_at = _derived_timestamp(...)`; direct ORM attribute assignment), just
  isolated into its own pass instead of interleaved with the writes.
- Also the one place allowed to touch `execution_data`/`extra_data` after the fact —
  only to strip the import marker back down to something clean if the route was forced
  to store anything transitional; in the common case there's nothing to strip because
  the replay client never wrote confidence/policy keys to begin with.
- Explicitly documented (in its own docstring and in `whistlebird-production-import.md`)
  as **internal tooling for resetting/populating demo tenants only** — never a
  capability the live app exposes to a user.

## Ordering algorithm — "date-prioritized topological sort"

Real-world ordering has two kinds of constraints that both matter:

- **Hard dependencies** (must never be violated, regardless of date): an execution must
  exist before any of its steps complete; step *N* of an execution must complete before
  step *N+1* of the *same* execution; a Rosella-linked execution's `rhubarb_maceration`
  step depends on its base Solstice execution's vat-producing step; a raw-material
  purchase must exist before the first execution step that consumes it.
- **Soft ordering** (everything else): process events in real chronological order.

Algorithm: build one master list of typed events, each carrying `real_date` and an
explicit `depends_on: list[event_id]`. Run a **date-prioritized Kahn's algorithm** — a
topological sort where, among all events whose dependencies are currently satisfied,
always pick the one with the earliest `real_date` next (stable tiebreak: purchases
before consumption, execution-creation before its own first step, lower global_vat
first). This guarantees every hard dependency holds while staying as close to true
chronological order as the data allows. Assert-and-fail loudly if the resulting order
ever violates a hard dependency (should be structurally impossible given the algorithm,
but verify it explicitly against the real curated dates before trusting it — some
inferred/derived dates are close enough together that a bug here would be easy to miss).

Event types feeding the timeline (sources already curated, see
`docs/whistlebird-import-decisions.md`):

1. Raw material purchases — legacy DB (`purchases_ingredients`, `purchases_gns`) +
   `docs/whistlebird-raw-material-source.json` (130 records).
2. Execution creation + N step completions — legacy DB batches +
   `docs/whistlebird-production-sheet-source.json` (VAT1–54, ~55 executions).
3. Trials — legacy DB `product_actions_flavor_experiments` (~28).
4. Customs lodgements — legacy DB customs table (13).

Wildflower is the first product historically (VAT1, 2024-01-22) — the timeline should
reflect that naturally once sorted by date; no special-casing needed beyond the
dependency edges above.

## Open questions being researched before implementation starts

- Exact login route, payload, CSRF/2FA behavior under `test_client()` (does 2FA gate a
  test-admin session created via `ensure_target_org_admin`, and does `test_client()`
  need an explicit CSRF token or does test config disable that check?).
- Whether a trial is just a regular execution of a "trial" workflow (reusing the same
  two endpoints) or has its own route.
- Whether completing a step with `actual_inputs` pointing at an inventory item actually
  decrements that item's quantity through the real route (confirms "replay exercises
  real logic" claim) or only via the direct-ORM path today.
- Customs/compliance lodgement route and payload shape.
- Whether Flask-Limiter rate-limits apply beyond `/auth/*` (matters for ~700+ calls in
  one process).

## Progress log (update this as work lands — this is the resume point after any
interruption, read it before re-deriving anything)

**2026-09-14, first pass:**
- Auth/CSRF/routes research done (see below) — login is plain POST /auth/login
  (test admin has 2FA disabled by construction), CSRF token comes from a `<meta>` tag
  on any authenticated page and does not rotate per request, org scope is derived
  purely from the logged-in user's session (no header/param needed), no rate limits on
  business routes, trials use the exact same execution/step endpoints as production
  batches (no separate trial API).
- **Key finding that changes the client design**: `complete_step`
  (`app/core/backend/backend.py:2234`) does NOT require outputs to be pre-created via
  `/api/core/inventory` — passing an `actual_outputs` entry with no `inventory_item_id`
  makes the route create the inventory item itself as part of the same transaction
  (`output_creations`, first seen ~backend.py:2790). This matters a lot: it means the
  replay client must NOT try to pre-create VAT-batch/bottled-product inventory items
  the way `apply_production_batches` does at the ORM level — it must describe the
  output on the `complete_step` call and then read the created item's id back out of
  the response for later steps (e.g. bottling needs the VAT item id from the aging
  step; a Rosella conversion needs the base VAT's item id) via the follow-up `GET
  /api/core/executions/<id>` call.
- Also confirmed (important, matches Johnny's whole thesis): inventory consumption for
  `actual_inputs` is real business logic that lives ONLY in this HTTP route, not in
  `ExecutionRepository.complete_step` — the existing ORM-direct script never actually
  exercises it. Going through the real endpoint is a genuine behavioural upgrade, not
  just a formality.
- Timeline compiler (`scripts/whistlebird_replay_timeline.py`) is written and tested:
  625 events, zero dependency-cycle errors, zero missing deps, Rosella-conversion
  ordering verified (base VAT's `aging` step lands before the linked conversion's
  `rhubarb_maceration`), first execution is a trial (2023-06-18) then Wildflower VAT1
  (2024-01-22) — matches "Wildflower is first product" once trials are set aside.
  44 "date inversions" were found (a raw-material purchase dated after something that
  depends on it) — these are all legacy-DB rows bought in bulk well ahead of need
  (e.g. a Dec-2024 restock nominally "after" an Oct-2024 batch that in reality drew
  from stock bought earlier); the topological sort still orders them correctly by
  dependency, this is just a note that the *soft* date-ordering isn't purely
  chronological where bulk restocking created lead time. Not a bug — expected.
- `scripts/whistlebird_replay.py` (the client) is a first-draft skeleton, NOT yet
  correct: it currently passes `actual_outputs: []` on every step, which is wrong for
  `aging`/`rhubarb_maceration` (must produce the VAT-batch item) and `bottling` (must
  produce the bottled-product item and consume the VAT item), and has a dead
  placeholder line for the Rosella base-vat input lookup. Second research pass
  dispatched to map the exact `outputs`/`inputs` schema per workflow step and the
  `complete_step` response shape before finishing this file — DO NOT trust its current
  contents as more than a skeleton.

**2026-09-14, second pass (research complete, design decisions locked in):**
- `complete_step`'s JSON response never returns a created output item's id — read it
  back via a direct DB query (same read-only pattern as `MarkerStore`, matched by
  `source_execution_step_id` + name), not via the API.
- Confirmed output shapes: Wildflower/Solstice aging -> "VAT batch" (L); Rosella
  rhubarb_maceration -> "VAT batch" (L); all four workflows' bottling -> "Bottled
  product" (units); trials' library_stock -> "Library stock" (mL). No step anywhere
  configures `custom_expiry`/`ready_date`, so `{"name": ..., "quantity": "..."}` is a
  fully valid output — no extra fields required. No "active_evidence" Compliant
  constraint is live for this org's current settings, and freshly-created inventory is
  never blocked by a ready-date cooldown. All confirmed by direct code reading, not
  assumed.
- **Real constraint that changes scope**: the live endpoint requires `actual_inputs`
  quantities to be genuine positive numbers (`Decimal(str(quantity))`, `>0`) to
  actually consume anything — unlike the existing ORM-direct script's `quantity: None`
  "link only, amount unknown" convention (which exists specifically because WB-018
  says legacy ingredient links have no quantity data and inventing one is exactly the
  kind of allocation the decisions log says never to do).
  **Decision**: real per-batch ingredient consumption is only reported through the API
  where an exact quantity is actually known — the 110 `resolved_by_context`-sourced
  raw-material records already carry a precise per-batch quantity (2x-multiplied
  recipe amount) by construction. Legacy-DB ingredient links (`product_actions_flavors
  .ingredient_codes`, real evidence, no quantity) and clean-tier Alembics receipts (not
  allocated to a specific batch, WB-018) stay **ordering-only**: the purchase-before-
  consumption dependency edge is still enforced in the timeline (a real purchase must
  still exist before the batch that used it), but no `actual_inputs` entry is sent for
  them, since fabricating a split would be exactly the invented-allocation WB-018
  already ruled out — just now via the API instead of the ORM. Documented here instead
  of anywhere in the loaded data itself.
- **VAT-batch output volume**: not every VAT27+ manifest record has a curated
  `vat_volume_l` (the sheet has it in places but it was never systematically pulled
  into the manifest). The real endpoint silently drops an output whose quantity is
  `<=0`, which would break the chain (bottling has nothing to consume). Fallback order:
  (1) `batch.vat_volume_l` when curated, (2) total bottles x recorded bottle size in L
  when both are known (a real computation from real recorded numbers, not a guess),
  (3) `Decimal("1")` as a last-resort non-zero placeholder **only when neither real
  number exists**, tracked here as a known gap, never labelled as anything but a plain
  quantity in the actual API payload (no confidence flag written to the app).
- Bottling consumes the *entire* VAT-batch item (the whole intermediate is used up by
  definition) and produces the real recorded bottle count. Labelling consumes the
  entire bottled-product item. Both are exact, real numbers already in the curated
  data — no fabrication needed for these two.

## Build checklist

- [x] Research round 1: auth/CSRF/2FA, trial route, inventory-consumption side effect,
      customs route, rate limiting
- [x] Timeline compiler, tested against real legacy DB + both manifests
- [x] Research round 2: exact `outputs`/`inputs` schema per process-step template,
      `complete_step` response shape, no custom_expiry/ready_date/active-evidence
      constraints apply to these four workflows
- [x] Replay client rewritten with real output/input semantics per round 2's findings
- [x] Unit tests for the ordering algorithm (8 tests, dependency-over-date precedence,
      cycle/missing-dep detection, deterministic tiebreak)
- [x] Local dev server (`uv run workflow start`, port 8005, HTTPS) used instead of the
      shared `workflow-engine-test` Docker container -- that container bakes its image
      at build time and doesn't pick up local edits, which would have hidden every fix
      below
- [x] **Full 624-event replay succeeds end-to-end against a real running server.**
      Verified idempotent (second full run: 0 issued / 624 skipped) and verified clean
      from a fresh reset (624 issued / 0 skipped, zero leftover orphans)
- [x] Timestamp-correction after-script
      (`scripts/whistlebird_replay_correct_timestamps.py`), keyed off the same import
      markers via a second call to `build_timeline()`
- [x] Verification: `--verify-import` reports every count exact
      (raw_material_items 200/200, Rosella/Solstice/Wildflower 3/14/38 each exact,
      customs 13/13, date_mismatches 0/0, incomplete_batch_steps 0/0, wording_leaks
      all 0) -- extended `build_import_verification`'s expected raw-material baseline
      to include the new manifest (it only knew about the legacy DB before)
- [x] Direct SQL sweep for "derived"/"date_confidence"/"timestamp_policy" across every
      `execution_data`/`extra_data`/`details` column in the org: **zero matches**
- [x] Regression test (`tests/test_executions.py::TestConsumptionOnlyStepCompletion`)
      for the flush-timing bug found in `complete_step` -- verified it fails without
      the fix and passes with it
- [x] Update `docs/whistlebird-production-import.md` to describe the new two-pass
      approach
- [x] Open the MR (!247)

## Real bugs found and fixed by going through the real API (not a complete list of
work -- see git log for the full story; this is the "why this was worth doing" summary)

1. **`app/core/backend/backend.py`'s `complete_step`**: a step that only consumes
   inventory (no `actual_outputs` -- e.g. a terminal step like "labelling") never
   re-enters `allow_inventory_quantity_write` via `create_inventory_item`, so the
   earlier quantity update sat dirty and unflushed until the plain
   `db_session.commit()` outside any guard -- `before_flush`'s authorization check
   correctly rejected it as unauthorized. This affects any real user completing a
   consumption-only step, not just this replay. Fixed with a `db_session.flush()`
   while still inside the guard.
2. Four Alembics batch numbers are reused across separate orders and tripped a real
   `(org_id, name, supplier_batch_number)` uniqueness constraint the ORM-direct script
   never exercised (disambiguated per WB-017's existing pattern).
3. One legacy raw-material row (`purchases_ingredients` id 17, "liquorice root") has a
   genuine zero recorded quantity -- the real endpoint's positive-quantity check caught
   it; the ORM-direct script had silently written a zero-quantity row.
4. The ORM-direct script's "link only, quantity unknown" `actual_inputs` convention
   (`quantity: None`, used for legacy ingredient links with no recorded amount) fails
   the real endpoint's `Decimal(str(quantity))` parse outright -- real consumption can
   only be reported where an exact amount is actually known.

## Recipe and finished-stock accounting added 2026-09-16

The API replay now records the inputs and outputs that were previously absent from the
historical load, using the founder-confirmed per-VAT process rather than invented
allocations:

- **Neutral grain spirit (NGS):** every Wildflower/Solstice maceration consumes 0.746 L
  of the real 96.4% NGS stock to prepare two 1.8 L, 20% ABV flasks (and records 2.854 L
  of water as an untracked `other material`). Batches before 2025-04-02 draw from the
  nine real `purchases_gns` receipts. From that date onward, the compiler creates one
  formula-sized NGS receipt per VAT, dated three days before maceration and explicitly
  dependent on by the consuming step, so the historical pool is not double-counted.
- **VAT fill:** Wildflower uses 24.456 L NGS + 30.397 L water, then a 1.260 L 66.6% NGS
  top-up. The replay resolves that top-up to the real underlying stock draw (0.870 L NGS
  and 0.390 L water), yielding 25.326 L NGS and 30.787 L recorded water at aging.
  Solstice uses 17.776 L NGS and 25.064 L water. The historic bottled quantities remain
  the final output; no yield is manufactured from the recipe figures.
- **Foraged and dilution inputs:** water plus the six founder-supplied foraged botanical
  quantities are recorded as `other materials` inputs (no inventory identifier, so no
  phantom purchased stock): Wildflower's lemon juice/grapefruit juice/lemon peel and
  Solstice's kawakawa/orange peel/orange juice. Each per-flask amount is doubled for a
  VAT.
- **Finished stock:** labelling consumes the bottled-product item and produces a clear
  product-line final item with the identical recorded quantity. Historical breakages are
  already included in those bottle counts, so the replay does not invent separate
  wastage.

## Label-batch numbering and FIFO sales drain added 2026-09-17/18

See `docs/whistlebird-import-decisions.md`'s Stage 7 for the full writeup. Summary:

- Whistlebird buys pre-printed label rolls of 500 -- bottles 1-500 ever labelled for a
  product are "batch 1", 501-1000 "batch 2", etc., across VATs. Checked first (per
  Johnny's request) whether the CRM module's existing `SalesTraceabilityConfig`
  (`matching_strategy: fifo`, `matching_key: batch_id`) already implements this: it does
  not -- it is a settings row with no draining engine behind it anywhere in the app.
- `scripts/whistlebird_replay_timeline.py`'s `_assign_label_batches` computes the split
  per product line from real labelling dates and bottle counts; `complete_step`
  (`app/core/backend/backend.py`) now accepts a generic per-output `batch_number`,
  stored on the created item's `extra_data`; `scripts/whistlebird_replay.py`'s labelling
  branch posts one output per label batch a VAT's bottles fall into.
- `InventoryRepository.consume_final_product_fifo` + `POST
  /api/core/inventory/consume-fifo` (both new) drain a named final product oldest-batch
  first, splitting across items at a boundary, refusing (no partial consumption) when
  stock is short. This is the landing point for a future Xero-invoice sales sync -- not
  built yet, and out of scope for this pass.
- Verified against a full reset -> replay (654 events) -> timestamp-correction ->
  `--verify-import` cycle on the live target, all counts exact (unchanged from Stage 6).
  Batch totals: Wildflower 6 batches (five full 500s, one 413.5-bottle open batch),
  Solstice 2 (one full 500, one 178.75-bottle open batch), Rosella 1 (162.5 bottles).
  A live `consume-fifo` call for 600 Wildflower units correctly drained batch 1 (500)
  then 100 units of batch 2; the target was then reset and replayed again so no test
  consumption was left in what represents real, sales-free production history.

## Real NGS receipts backfilled from source correspondence, 2026-09-18

The nine real `purchases_gns` rows only covered orders through 2025-04-01; every
Wildflower/Solstice VAT after that date was funded by a formula-sized synthetic
shortfall receipt (see "Recipe and finished-stock accounting" above and the
`reconcile replay raw stock` allocator work merged the same day). Read every
Southern Grain Spirits order thread in the founder's Gmail and found eight further
completed orders (invoiced, paid, dispatched) the legacy purchase register was
missing, from 2025-06-18 through 2026-09-08 -- all 100 L at 96.4% ABV. Added them to
`purchases_gns` (same `Purchase of GNS` convention as the existing nine), dated by
each order's invoice-issue date (NZ local), since the existing rows' own date
convention is inconsistent across payment/dispatch/receipt and this was the only
anchor consistently present in every thread.

Ran a full `--confirm-reset-whistlebird-test` -> replay (632 events) ->
timestamp-correction -> `--verify-import` cycle on the live target. Result: every
one of the 17 `Neutral grain spirit` inventory items now carries a real
`supplier_batch_number` -- the real receipts fully cover demand through the present,
so the allocator generated zero dedicated shortfall purchases this run (down from 24
in the prior build). `--verify-import` reports exact matches on every count
(batch executions, customs lodgements, raw-material items, date mismatches, wording
leaks all clean).

**Follow-up, same day:** those 17 rows only lived in the legacy `purchases_gns` table --
not reproducible from this repo alone, and the founder wants this system to replace that
legacy DB, not keep depending on it. Moved all 17 (the original 9 plus the 8 above) into
`docs/whistlebird-raw-material-source.json` as `clean_records`, and taught
`whistlebird_replay_timeline._ngs_allocations` to pool NGS receipts from there
(`manifest_ngs_receipts`) instead of from `wm._raw_material_records`'s legacy-DB read --
`build_timeline` now filters `purchases_gns` rows out of the legacy pool entirely so
they're never double-purchased across both sources.  `build_import_verification` was
updated to match (drops `purchases_gns` from its expected-count sources and pools NGS
from the manifest too when `include_replay_ngs_purchases=True`). The ORM-direct
`--rebuild-whistlebird-test` path is untouched and still reads `purchases_gns` directly --
it's the lesser-preferred pathway already documented as missing the dedicated-NGS
behaviour, not the one this independence was requested for.

Re-ran the full reset -> replay -> timestamp-correction -> `--verify-import` cycle:
identical result to the legacy-DB-sourced run (632 events, 17 real NGS receipts, zero
synthetic shortfalls, 281.956 L remaining across all lots, every verify-import count
exact) -- confirming the refactor is behaviour-preserving. Added
`tests/test_whistlebird_replay_timeline.py::test_manifest_ngs_receipts_converts_only_ngs_records_and_ignores_other_ingredients`
and `::test_ngs_allocation_pools_manifest_receipts_the_same_way_as_legacy_ones` to lock
this in.
