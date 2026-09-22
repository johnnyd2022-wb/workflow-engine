# Whistlebird API-replay framework — execution plan

Working doc for building a replayable, API-driven loader for `Whistlebird Ltd`, per
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
   markers must not appear in anything written to `Whistlebird Ltd` going forward. The
   curation trail (how we know a date is right) stays in `docs/whistlebird-import-*.md`
   and the JSON manifests — never in `execution_data`/`extra_data` on a live row. This
   is a record of truth, not a migration-tracking artifact.
4. **Free byproduct: a demo-reset framework.** Reset the tenant, run the replay, run the
   timestamp correction — same tenant is back to a clean, fully-dated historical state.
   Usable between client demos.

## Architecture

Two scripts, run in sequence:

### 1. `scripts/whistlebird_replay.py` — the replay client

- Drives a **running app server over HTTP**: `ReplayClient`
  (`scripts/whistlebird_replay.py:70`) wraps a `requests.Session` pointed at `--base-url`,
  not Flask's `test_client()` as this plan first proposed. Every call still executes the
  exact route function, its decorators (`@requires_auth`, `@requires_org_scope`), the
  Pydantic request-body validation, and the real repository/business logic — nothing
  about the code path is faked — and because the client is a real one, the real CSRF and
  rate-limit handling apply (see "Resolved questions"). The session's cookie jar means
  one login covers the whole replay. (verified 2026-09-19 by findings-sweep)
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

- Whether a trial is just a regular execution of a "trial" workflow (reusing the same
  two endpoints) or has its own route.
- Whether completing a step with `actual_inputs` pointing at an inventory item actually
  decrements that item's quantity through the real route (confirms "replay exercises
  real logic" claim) or only via the direct-ORM path today.
- Customs/compliance lodgement route and payload shape.

## Resolved questions

Answered from the code rather than from the research notes in the progress log below, and
pinned by `tests/test_replay_app_contract.py`, so a change that breaks the replay fails
there instead of partway through a run. (verified 2026-09-19 by findings-sweep)

- **Login route, payload, CSRF and 2FA.**
  - Login is `POST /auth/login` with JSON `{"email", "password"}`
    (`app/api/routes/auth_routes.py:255`; client at `scripts/whistlebird_replay.py:79-93`).
  - A 2FA-enabled account answers `{"requires_2fa": true}` (`auth_routes.py:573`) and
    `ReplayClient.login` stops on it (`whistlebird_replay.py:85`), so the replay admin
    must have 2FA off. A newly created admin does: `User.two_factor_enabled` defaults to
    `False` (`app/core/db/models/user.py:39`) and `ensure_target_org_admin` creates the
    admin without setting it (`scripts/whistlebird_migration.py:2078-2084`). An admin that
    already exists is left untouched (`:2088`), so its 2FA setting is whatever it was.
  - The app never turns CSRF off: it installs `CSRFProtect(app)` unconditionally
    (`app/api/app_factory.py:473`; only a missing Flask-WTF degrades it, and only in
    local/test) and sets no `WTF_CSRF_ENABLED`. Many test fixtures do set
    `WTF_CSRF_ENABLED = False` on their own app instances (27 test files mention it, e.g.
    `tests/test_auth_login_security.py:58`), so a `test_client()` built like those needs
    no token, while one on a plain `create_app()` does. Every `/auth/*` view and the two
    `/telemetry*` ingest routes are exempt (`app_factory.py:478-479`), so login needs no
    token. Every other mutating route needs it in `X-CSRFToken` (`app_factory.py:469`); the
    client also sends a same-origin `Referer` because Flask-WTF requires one over HTTPS
    (comment at `whistlebird_replay.py:96-99`). The token is the `<meta name="csrf-token">`
    on the authenticated SPA shell at `/core/dashboard` (`/` is the public page and has
    none), fetched once per login (`whistlebird_replay.py:50,86-100`). Flask-WTF expires a
    token after 3600 s (`WTF_CSRF_TIME_LIMIT`, not overridden in `app/`) and the client
    never refreshes it, so a single run longer than an hour would start getting 400s.
- **Do Flask-Limiter limits apply beyond `/auth/*`? No — and `/auth/*` is only partly
  covered.** The limiter is built with no `default_limits` (`auth_routes.py:131-132`), so
  only routes with an explicit `@limiter.limit` are throttled: `/auth/signup` (`:159`) and
  `/auth/login` (`:256`) at 5/min per IP+email, and the public `/telemetry` and
  `/telemetry/posthog/<path>` ingest routes at 120/min (`app_factory.py:308,331`). The
  5/min is relaxed to 1000/min in the test environment and local-under-CI, never in
  production (`USE_RELAXED_AUTH_RATE_LIMITS`, pinned by
  `tests/test_auth_rate_limit_gating.py`). Business routes are never throttled, so ~700
  calls from one process cannot trip a limit. The remaining `/auth/*` routes carry no
  limit either: `/auth/verify-2fa` has neither a limit nor an attempt counter — only
  `/auth/login` touches `failed_login_attempts` / `lock_account` (`auth_routes.py:378-459`)
  and `verify_totp` is a bare `pyotp` check (`app/core/security/auth_service.py:188-193`).
  **Unfixed**; tracked as F6 in `.agents/reports/auth/security-audit.md`.

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

## Real in-progress batches (VAT55/56/57/58/59) and the pending-step mechanism, 2026-09-18

See `docs/whistlebird-import-decisions.md`'s Stage 10 for the full writeup (what changed
in the sheet, why the fix needed a real code change and not just more manifest rows, a
real `_enrich_ingredient_codes` bug the first live run caught, and the botanical-stock
backfill it also needed). Summary: `ProductionBatch.pending_steps` + a manifest step spec
of `{"pending": true}` lets a batch be imported with only the steps that have really
happened completed, leaving the rest genuinely PENDING in the target -- same as a real
user mid-process. Only the API-replay path supports this; `--rebuild-whistlebird-test`
skips a pending batch entirely rather than falsely complete it.

Verified against a full reset -> replay (684 events) -> timestamp-correction ->
`--verify-import` cycle, all counts exact. 63 whistlebird tests pass, including 5 new
ones covering the pending-step parsing, the suffix-validation error, `_batch_events`
truncation, and the `_enrich_ingredient_codes` regression.

## NP3 food-control evidence, 2026-09-19

The NP3 evidence the business enters in the Compliant workspace (attestations, control
logs, review intervals, NP3 profile settings, the staff the training/illness logs name)
lives only in the database, and the scoped reset deletes `compliance_records`. It is now
replayable the same two-pass way as the Core history. Code: `scripts/whistlebird_np3.py`;
source of truth: `docs/whistlebird-np3-evidence-source.json`.

**Workflow**

1. Enter evidence in the app (text and selections only).
2. `uv run python scripts/whistlebird_np3.py snapshot --target-url ...` writes it into the
   manifest (`--dry-run` first to see what changes). Commit the JSON.
3. `scripts/replay_whistlebird.sh --confirm` derives the local target database
   connection and rebuilds Whistlebird Ltd through the API. Use
   `--discard-unsnapshotted-np3` only when intentionally replacing NP3 evidence
   that has not been snapshotted into the committed manifest. It rebuilds
   everything: ensure tenant -> admin password -> scoped reset -> workflows -> Compliant
   setup -> replay (Core, then NP3) -> timestamp pass -> verify. Without the confirm flag
   it is a read-only preflight.

**Decisions (founder, 2026-09-19)**

- Text and selection evidence only. A record linking Core entities (`source_refs`) or an
  uploaded evidence file is refused by the snapshot, never silently dropped.
- Dates are set explicitly in the manifest (`signed_on`, `due_date` on an attestation; a
  log's `event_date`). The NP3 routes stamp "now" and compute an attestation's due date
  from today, so the timestamp pass sets `created_at`/`updated_at`/`due_date` from the
  manifest. A snapshot keeps dates already in the manifest for unchanged records; a new
  attestation takes today's date until edited.
- UUIDs are not preserved. A log's employee is keyed by email, and staff are created
  through `POST /org/users` (active, random discarded password -- nobody signs in as them)
  before their logs are replayed.
- Identity/idempotency is a content fingerprint (the routes build `details` server-side, so
  no `import_ref` marker can ride along). Two identical entries in one manifest are
  rejected.
- The NP3 phase runs after every Core event, so an `np3_execution_evidence_mode: required`
  profile in the manifest cannot block the Core step completions.

**Safety guard.** Before anything destructive the rebuild validates the manifest and
refuses to continue if the database holds NP3 evidence, staff or profile settings the
manifest lacks (`--discard-unsnapshotted-np3` overrides). `--verify-import` now also
checks NP3 record count, content, staff, profile and dates.

**Derived NP3 evidence needs nothing stored.** Traceability, supplier and receiving
evidence is projected live from the Core DAG once the Core replay has run.

The committed `whistlebird-np3-evidence-source.json` carries Whistlebird's real NP3 answers:
each of the 38 checks' `how_we_meet` text is the founder's own wording (2026-09-21), and
the annual training register is a declarative schedule. `annual_training` lists the dates
and the training `categories` (keys from `NP3_TRAINING_CATEGORIES` in
`app/features/compliant/modules/nz_alcohol/np3_audit.py`); the replay expands them for
each `staff` member into one log per category, person and date, in the staff-competency
register's format (`training_topic` category, `employee_name` as a human name, `event_date`).
Staff therefore need a `name`; the timestamp pass sets it as the user's first/last name.
Evidence fields the answers do not state are left blank rather than invented, and the old
`REVIEW PLACEHOLDER` example logs are gone -- real events are entered in the app and
snapshotted.

**Not yet exercised end to end.** Verified by tests against the real routes and DB on a
throwaway org (replay, dating, snapshot round-trip, delete-and-replay reproduces the
evidence) and a read-only smoke test of the CLI against `Whistlebird Ltd`. The full
`scripts/whistlebird_rebuild_api.py` run against `Whistlebird Ltd` has NOT been done --
rehearse it (snapshot, commit, rebuild, confirm `--verify-import` is clean) well before
relying on it.

## CRM product mappings and matching config, 2026-09-19

The scoped reset deletes `product_mappings` and `crm_sales_traceability_config`. Neither is in
the legacy database, so before this a rebuild silently lost every mapping (and the Xero
connection), and none of the ~460 synced sale lines could allocate against stock until someone
re-entered them by hand.

`docs/whistlebird-crm-config-source.json` now holds them, and `scripts/whistlebird_crm.py`
replays them through the real CRM API (`PUT /api/crm/traceability-config`, then
`POST /api/crm/product-mappings/bulk`) after the Core history, before NP3:

- **Config first.** Every mapping is "Xero line contains phrase", which never matches while
  exact-only matching is on, so `strict_mapping: false` is replayed first, in the same order
  the Configuration page uses. The manifest loader refuses a manifest that asks for a
  contains/alias mapping with `strict_mapping: true`.
- **Name-only mappings.** They carry no `biz_e_source_output_id`, exactly as created in the
  UI, because output UUIDs change on every rebuild.
- **Refuses a typo.** The replay reads `/api/crm/final-products` and stops before writing
  anything if a mapping names a product the tenant does not have; the API would accept it and
  it would simply never match.
- **Resumable.** Mappings already present (name and phrase, ignoring case) are skipped.
- **Verified.** `--verify-import` on the API-replay path reports
  `crm_product_mappings_missing` and `crm_traceability_config_mismatch`, both expected 0. It
  counts *missing* manifest mappings rather than comparing row totals, so a mapping added
  later in the CRM does not fail a later verify. The ORM-direct rebuild does not load them.
- Skip with `--skip-crm-config`.

Reviewed mapping decisions: `Bin stock` -> Rosella (founder reviewed INV-0247/INV-0248 on
2026-09-19: the generic "Whistlebird Gin - Bin stock" lines carry Rosella item code
`WBRS01-4625`). Shipping and the generic `SAMPLE` minis are deliberately unmapped.

## Legacy database snapshot, 2026-09-19

The replay used to read twelve tables straight from the prior inventory database
(`whistlebird_inventory` on :5401), so it could only run where that database was also running.
Those rows now live in `docs/whistlebird-legacy-source.json` and the replay reads the file:
clone the repository, start the app, run `scripts/whistlebird_rebuild_api.py`.

- **What is stored.** Exactly the rows *and columns* the loaders read (12 tables, ~234 rows);
  `uid`, `action` and the like are not exported. `LEGACY_TABLES` in `scripts/whistlebird_legacy.py`
  is the single registry that drives both the export and every loader, so there is no SQL to
  keep in sync. Values round-trip exactly (dates ISO, integers stay integers, floats as
  recorded), and one row is written per line so a git diff shows which rows changed.
- **Same result as the database.** The timeline built from the file is identical, event for event
  and payload for payload, to the one built from the live database (692 events), and
  `--verify-import` produces an identical report with zero mismatches against the loaded tenant.
- **Purchases from 2025-05-13 onward** are not in the old database; they were always curated in
  `docs/whistlebird-raw-material-source.json`.
- **Refreshing it.** `uv run python scripts/whistlebird_legacy.py snapshot --legacy-url <url>`
  rewrites the file; `verify --legacy-url <url>` reports any row that differs (including an
  integer that became a float, since the loaders format values with `str()`). Commit the JSON.
- **Live database still works.** Pass `--legacy-url postgresql://...` to the replay, timestamp
  pass or rebuild to read the live database instead of the file.
- **The rebuild checks the source before it deletes anything.** Its preflight loads the snapshot
  (or connects to the URL) first, so an unreadable source stops the run instead of leaving a
  wiped tenant.
- **Not converted.** The older ORM-direct path (`--dry-run-core`, `--dry-run-production`,
  `--rebuild-whistlebird-test`) runs aggregate SQL and `SHOW TimeZone` against the live
  database and still needs `WB_LEGACY_DATABASE_URL`.
- **Still outside version control by design.** The admin password (KeePassXC entry
  `workflow-engine/Whistlebird Ltd`) and the app's own Xero/PostHog credentials.

## Expired ingredients: none used, expired stock written off, 2026-09-19

The old allocator drew botanical lots oldest-purchase-first and ignored both the lot's expiry and the
date of the step. Against the recorded expiry dates, **139 uses across 20 lots and 14 ingredients
came after the lot had expired** (up to 739 days), and 12 expired lots still held stock.

- **Date-aware allocation.** `allocate_fifo_lots` (`scripts/whistlebird_replay.py`) skips a lot whose
  expiry is *before* the step's business date; a lot is still usable on its expiry date. It also never
  draws a lot pinned to a specific batch (an exact-quantity `resolved_by_context` purchase, listed in
  every maceration event's `reserved_ingredient_codes`). The reservation was found the hard way: with
  expired lots skipped, an earlier batch's fallback moved on to a newer lot and emptied VAT53's pinned
  lots before VAT53 ran.
- **Modelled restock purchases** *(sizing superseded 2026-09-19: see "Real pack sizes" below)*. Skipping expired lots leaves the demand only they could have met
  (1,384 g over 58 batch/ingredient pairs, mostly dried apple ring, cardamom, sumac, orris root). Each is
  a `resolved_by_context` purchase in `docs/whistlebird-raw-material-source.json`, in the existing
  style: sized to exactly that batch's shortfall, dated 3 days before its maceration, from the
  ingredient's usual supplier, labelled `derived:` with no purchase evidence. They are modelled history,
  not receipts. The 30 recipes that predate every receipt (and Green tea, which has no lots) are unchanged.
- **Disposals.** `docs/whistlebird-disposals-source.json` lists the 25 lots left with stock once
  nothing draws an expired lot (6.9 kg), each with the quantity the replay expects and a date (the later
  of the lot's expiry and its last use, which is always the expiry now). `scripts/whistlebird_disposals.py`
  replays them through the real wastage API after the Core history and refuses to dispose a quantity
  other than the curated one; the timestamp pass then sets each recorded date. Lots expiring on or
  before 2026-09-19 are included ("before they expire").
- **Proven without a database.** `scripts/whistlebird_replay_simulation.py` runs the replay's own
  functions against in-memory lots, driven by `build_timeline()`. With the old rules it reproduces the
  live tenant exactly (139 late uses, 20 lots); with the new rules there are 0 late uses, 0 stock
  errors and no expired-only gaps. `plan --write` regenerates the restock records and the disposals;
  a test fails if either committed file is stale.
- **Verified on rebuild.** `--verify-import` reports `expired_lot_uses`, `disposals_missing` and
  `disposal_date_mismatches`, each expected 0.
- **Not evidence.** If the recorded expiry dates are conservative best-before dates and the herbs were
  in fact used past them, the modelled restock purchases replace a real (if late) use of an old lot.
  Correct the expiry at the source (the legacy snapshot) to undo that for a given lot.

## Real pack sizes, not per-batch sizes, 2026-09-19

The `Whistlebird Ltd` source-map trace showed each botanical as dozens of tiny lots -- Sumac as 54 lots of
at most 7.2 g -- instead of the bag actually bought. Two causes: the manifest held a `resolved_by_context`
purchase per (batch, ingredient), sized to exactly that batch's use and *pinned* to it (`consumed_by`, and
reserved from the FIFO fallback), so one lot traced to exactly one batch; and an intermediate replay
(`192cdd01`) had also minted an `Expiry replacement` lot per step. The tracer was never at fault -- real
lots (Juniper, Coriander) fanned out to 6-16 batches.

- **`restock_packs`** in `docs/whistlebird-raw-material-source.json` is the size each botanical is really
  bought in, with its supplier and code prefix: Sumac 500 g, Persian black lime 500 g, Dried mango 1 kg,
  Szechuan pepper 500 g, Dried orange peel 200 g, Green tea 20 bags (a box; 2 bags per flask, 4 per VAT), Cardamom 500 g,
  Hibiscus 500 g, Dried apple ring 1 kg, Orris root 500 g, Lemon myrtle 200 g. Founder-confirmed for the
  first six; the rest are the size of every real receipt of that botanical (legacy rows and the VAT59
  supplier lots).
- **The planner buys a whole pack only when stock runs out.** `plan_restock` (in
  `scripts/whistlebird_replay_simulation.py`) takes the earliest unbacked demand per ingredient, buys one
  pack dated 3 days before it, and `plan --write` re-simulates until nothing is short. A recipe that
  predates every receipt (before 2025-04-02, with no earlier lot) stays an unbacked "other material"
  line, as before. A demand larger than one pack is an error, never a bigger lot.
- **Restocks are ordered, not pinned.** `first_needed_by` puts the purchase before the batch that first
  needs it; nothing reserves it, so every later batch draws it down FIFO and the trace shows one
  purchase feeding many batches, then the sales mapped to them. Only the three VAT59 supplier lots
  (real receipts) keep `consumed_by`.
- **Result:** 301 lots become 126 -- 20 modelled pack purchases in place of ~200 per-batch ones -- and
  each feeds 5-28 batches (the newest box, opened for the latest batch, feeds 1 so far). The timeline is
  575 events (was 750).
- **Sumac carries a shelf life and a real-looking lot number.** Its one real bag (SBG001) lasted 285 days,
  so each modelled Sumac pack expires 285 days after purchase (`shelf_life_days`); the planner buys another
  when it runs out of date and the leftover is written off through the disposals manifest, so no expired
  Sumac is used or left in the tenant. Each pack has a six-digit supplier batch number that counts up with
  time from the real Moore Wilson lot 392314 (`lot_label`) -- invented ids in that style, labelled `derived:`
  in the manifest. Other modelled packs have no expiry (no evidence for one) and use their code.
- Dried orange peel is tracked stock. Only *fresh* orange peel (Solstice) is an untracked other material.
- Rebuild preflight now fails a manifest whose packs are not bought, pointing at `plan --write`.

## Replay audit-date completion, 2026-09-20

The timestamp pass now dates the whole replay trail: process definitions/versions/steps,
execution and inventory events plus their cached summaries, purchase audit-history JSON,
customs/NP3 audit logs, wastage ledger rows, CRM configuration/mappings, and NP3 staff.
It clears false completion dates left on in-progress executions and pending steps by
the previous pass. Setup records without source dates use deterministic dependency
anchors; see `docs/whistlebird-production-import.md`.

The current source has 45 purchase-before-use dependency conflicts involving 23 receipts.
Following the founder's choice, the source `purchase_date` stays as recorded while
creation/audit timestamps move before first use. Actual FIFO links get a final check.
VAT53's inferred September preparation/aging date also conflicted with the documented
31 July Green Gold diversion; those prerequisite audit events move to 31 July in
topological order, while the later Wildflower bottling keeps 1 September.

Validation: 39 replay/rebuild unit tests passed, two NP3 route/database tests passed,
and a rollback-only database exercise dated 569 of 575 currently present Core events
and their linked audit rows. The six missing events are newer than the existing test
tenant; a full rebuild is needed to apply the latest manifest. The existing tenant
also holds a Xero connection, 381 synced invoices and 507 FIFO allocations, so no
reset was run during this change.

## Trace dates pass, 2026-09-22

The timestamp pass leaves three things stamped with the day the tenant was rebuilt, and the
audit list and batch sheets showed that day as the date of the action:

- `extra_data.execution_trace.completed_at` on every produced lot (and the copies of it in the
  lot's events);
- `process_version_date` on `execution.created` events;
- the FIFO sales draws (`sales_fifo_consumption`) a Xero sync makes after the rebuild, stamped at
  sync time.

`scripts/whistlebird_trace_dates.py` sets them from the facts the tenant already holds: the
completing step's date, the process version's date, and the Xero invoice date. A sale draw is never
dated before its lot existed or before that lot's previous draw, so a lot's quantity history stays in
order (on the current tenant 497 of 507 draws land within a day of their invoice, none more than 11
days). It runs at the end of `whistlebird_rebuild_api.py`, and on its own it is idempotent, so re-run
it after every Xero sync (`apply`, then `verify`, which plans the pass and rolls back).

This is replay tooling for `Whistlebird Ltd` only (the org name is checked). The application is
unchanged: real actions are still stamped when they happen.

## Suppliers, 2026-09-22

Core now has a per-organisation suppliers address book (Inventory tab, below "Open live
inventory"): add, edit and delete, and import the supplier names already on inventory items. "View
suppliers" opens a dedicated page (`/core/suppliers`) styled like the NP3 page: status cards that
filter the register, a search box and the table.
Every create, edit and delete writes an audit event and audit-log row with the supplier's details
and what changed.

`docs/whistlebird-suppliers-source.json` holds Whistlebird's nine suppliers, named exactly as the
`supplier` text on the inventory lots so "import from inventory" never adds a duplicate. Details
come from each business's own website; a field a business does not publish (Davis Trading's and HB
Malt Station's email, HB Malt Station's phone, JingBo's street address) is left empty, not guessed.
No supplier has a main contact.

`scripts/whistlebird_suppliers.py` replays the manifest through the real API after the Core history
(`whistlebird_replay.py`), and the rebuild then dates each supplier's creation and audit entries to
the first purchase from them (their earliest inventory lot) and verifies that every inventory
supplier has a record. It is also runnable alone and idempotent, so it can populate an existing
tenant without a reset:

    uv run python scripts/whistlebird_suppliers.py apply --base-url https://localhost:8005 --insecure

Dating is replay tooling for `Whistlebird Ltd` only; in the app a supplier action is stamped when it happens.

## Recent batches (real, in-progress production), 2026-09-22

The historical timeline (`whistlebird_replay_timeline.py`) replays batches that already
finished every step, per the founder's spreadsheet. A batch that started recently and has
NOT finished every step yet -- a maceration put on tonight, whose distilling/aging/bottling
genuinely haven't happened -- doesn't fit that model: it has no known outcome to derive
dates from, and it must draw its tracked ingredients from whatever real stock the tenant
currently holds, not a historical purchase ledger.

`scripts/whistlebird_recent_batches.py` + `docs/whistlebird-recent-batches-source.json` cover
this. Only the maceration step is supported so far, on Wildflower or Solstice (the recipe
already defined in `whistlebird_migration.py`); it draws every tracked ingredient FIFO
(oldest `purchase_date` first) via `MarkerStore.consume_available_raw_material` -- the same
read-only live-inventory lookup the historical replay itself uses for its NGS shortfall
draws. Idempotent via the same `execution_data->>'batch_ref'` marker convention as the
historical replay, so a rebuild replays a given batch's maceration exactly once. Unlike
NP3/CRM/suppliers, it is never dated by the timestamp-correction pass -- it's a real event
happening now, so it keeps the timestamp the API call itself stamps.

First entry: a Solstice maceration put on the night of 2026-09-22, applied to the live
tenant and verified (226.8g Macedonian juniper from lot JBM006, 97.2g Himalayan juniper from
lot PO786MAR22-1-JBH005, 21.6g nutmeg, 5.76g cinnamon, 21.6g liquorice root, 3.6g Szechuan
pepper, 0.746L NGS from lot GNS-2026-06-03-16 -- all drawn from real stock; the execution is
`IN_PROGRESS`, Distilling now `READY`). Extending this to later steps (distilling, aging,
bottling) as the founder actually performs them is a deliberate follow-up, not something
this script should guess at -- `load_recent_batches_manifest` refuses any other step name.
