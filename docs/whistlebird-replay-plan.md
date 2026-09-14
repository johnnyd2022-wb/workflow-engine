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

## Build checklist

- [ ] Research: auth/CSRF/2FA under test_client, trial route, inventory-consumption
      side effect, customs route, rate limiting (dispatched, awaiting results)
- [ ] Timeline compiler (`_build_replay_timeline()` or new module): pure function,
      legacy DB + both manifests in, ordered typed-event list out. Unit-testable
      without touching a database.
- [ ] Unit tests for the ordering algorithm itself (hard-dependency violations must be
      caught; date-tiebreak behavior; resumability of a partial run)
- [ ] Replay client: auth session bootstrap, per-event-type dispatch to the right route,
      idempotency check, fail-loud on rejection
- [ ] Verify real inventory decrement happens on step completion (or add the missing
      write if the route doesn't do it — this would be a real app bug worth fixing
      separately, not worked around)
- [ ] Timestamp-correction after-script, keyed off the same markers
- [ ] End-to-end run against `whistlebird_test` (reset -> replay -> correct -> verify)
- [ ] Verification: same checks the current script already has
      (`build_import_verification`) plus a new check that NO row anywhere in the org
      contains `date_confidence`/`timestamp_policy`/"derived" in its `execution_data`
      or `extra_data`
- [ ] Update `docs/whistlebird-production-import.md` / decisions log to describe the
      new two-pass approach and retire the "derived" language from anything
      user-facing in the app
- [ ] Open the MR
