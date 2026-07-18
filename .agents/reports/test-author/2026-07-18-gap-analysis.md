# TEST AUTHORING — 2026-07-18 (gap analysis, no tests written)

mode: gap-fill (analysis only — user asked for the plan before writing)
preflight: test_db=up, live_server_tests=skip (app server down — expected), app_server=down
map: structurally clean (21 test files, all mapped; no dangling rows)
verdict: gaps-open

This run stops at Step 3: it identifies what is missing and sequences the work. No tests
were written. Each batch below is one `test-author → test-evaluator → MR` cycle.

## Method

Walked every `none`/`partial` row in `.agents/test-map.md` down to the actual code to
confirm the gap is real and to characterise the specific tests each needs. Confirmed
against source, not the map's seeded guesses:

- `two_org_two_user` is used by **no test** — the isolation harness exists but is unwired.
- **19** org-scoped repositories exist; only **2** factories (`OrganisationFactory`,
  `UserFactory`). Most isolation and integration tests are blocked on missing factories —
  a `test-fixtures` dependency, not a `test-author` one.
- The inventory quantity-write guard (`app/core/domain/inventory_quantity_guard.py`) is a
  SQLAlchemy `before_flush` listener that raises `InventoryQuantityWriteForbiddenError`
  when `InventoryItem.quantity` changes outside `allow_inventory_quantity_write(...)`.
  Cleanly unit-testable; **zero** tests today.
- Wastage idempotency is real code (`wastage_entries_payload_hash` +
  `_pg_advisory_lock_wastage_idempotency` in `backend.py`); **zero** tests.
- Execution idempotency runs through the `ApiIdempotencyKey` model; **zero** tests
  (only CRM idempotency is tested today).

## Prerequisite: factories (test-fixtures)

Most batches below need factories that don't exist yet. These belong in
`tests/factories.py` per the test-fixtures skill, created as the first sub-step of the
batch that first needs them (not hand-rolled inline):

| Factory | Backs batches | Wraps repository |
|---|---|---|
| `InventoryItemFactory` | 1, 3, 5-iso | `InventoryRepository.create_inventory_item` |
| `ProcessFactory` (+ `ProcessStepFactory`) | 2, 4, 5-iso | `ProcessRepository.*` |
| `ExecutionFactory` | 4, 5-iso | `ExecutionRepository.create_execution` |
| `WastageFactory` | 3 | `WastageRepository.create_wastage_record` |

A `two_org_two_world` fixture composing `two_org_two_user` + one process/inventory item per
org would remove repeated seeding across the isolation batches — worth adding once Batch 2
proves the shape.

## The plan — prioritised by risk × exposure

### Batch 1 — Inventory quantity-write guard  (map row 14: none → covered) ✅ DONE 2026-07-18
**Why first:** it is the mechanism that prevents untracked inventory mutations — the guard
itself is unproven, so every "the guard protects us" claim elsewhere rests on faith. Small,
self-contained, no cross-tenant surface.
Tests written (`tests/test_inventory_quantity_guard.py`, 6 tests, all green):
- ✅ direct `item.quantity = X` + flush **outside** any `allow_` block → raises
  `InventoryQuantityWriteForbiddenError`, and the change never reaches the DB.
- ✅ each legitimate path succeeds under its reason: `create_inventory_item`
  (REPOSITORY_CREATE), `add_quantity_to_inventory_item` (REPOSITORY_ADD_QUANTITY),
  `set_inventory_item_quantity` (MANUAL_API_UPDATE).
- ✅ nested `allow_inventory_quantity_write(...)` → raises `RuntimeError` (ContextVar safety).
- ✅ the ContextVar re-arms after the block (a second unguarded write still raises) — the
  failure mode a leaked token would hide.
Factory added: `InventoryItemFactory` (tests/factories.py).

**🐞 Real bug found and fixed (separate commit).** The `set_inventory_item_quantity` test
failed on correct code: the method set `item.quantity` inside the `allow` block but emitted
its audit event (which calls `session.flush()`) *outside* it, so the guard had re-armed and
every call raised `InventoryQuantityWriteForbiddenError`. This is reachable —
`POST /api/core/inventory/<item_id>/adjust` (backend.py:3845) — so manual quantity
adjustment was broken in production, undetected precisely because row 14 had zero coverage.
Fix mirrors the working sibling `add_quantity_to_inventory_item`: move the emit + commit
inside the allow block. This is the gap analysis paying for itself on the first batch.

### Batch 2 — Tenant isolation harness  (map row 8: none → covered) ✅ DONE 2026-07-18
**Why:** multi-tenancy is the product's core security boundary; a cross-org leak is silent
and catastrophic, and there was *no* automated proof any scoped repo enforced it.
Tests written (`tests/test_multi_tenant_isolation.py`, 7 tests, all green):
- ✅ process get-by-id / list / delete each proven org-scoped.
- ✅ execution get-by-id / list each proven org-scoped.
- ✅ inventory get-by-id / list each proven org-scoped.
- ✅ every test pairs the hostile-org case (org A gets `None` / empty for org B's row)
  with a same-org control that succeeds, so none passes vacuously.
Factories added: `ProcessFactory`, `ExecutionFactory` (tests/factories.py); a `world`
fixture composes them on top of `two_org_two_user`.
Validity: mutation probe stripped the org filter from the process repo — exactly the 3
process tests went red, execution/inventory stayed green.
**Scope note:** wastage-repo isolation moves to Batch 3, where `WastageFactory` is built.
The manual `test_multi_tenant_api.py` script is left in place as a manual tool.

### Batch 3 — Wastage idempotency + entry  (map row 16: none → covered) ✅ DONE 2026-07-18
**Why:** duplicate wastage on a retry corrupts stock and audit numbers; the advisory-lock +
payload-hash idempotency was entirely unproven.
Tests written (`tests/test_wastage.py`, 4 tests, all green):
- ✅ records wastage and deducts the item quantity (201, one wastage row).
- ✅ same payload + same idempotency key twice → `idempotent_replay: True`, deducted once
  (not twice), still one wastage row.
- ✅ same key + different payload → `409 IDEMPOTENCY_PAYLOAD_MISMATCH`, only the first applied.
- ✅ wastage rows are org-scoped (completes the wastage isolation deferred from Batch 2).
Factory added: `WastageFactory`. Idempotency is a route-handler property, so those three
tests drive it through an authenticated Flask test client (the `test_crm` app_client
pattern); org-scoping is a repository property, tested directly.
Validity: mutation probe forcing `idem_key = None` (dedup fully off) turns both idempotency
tests red while the no-key and repo tests stay green. Disabling only the *upfront* lookup
did **not** break the replay test — the DB unique constraint on `(org_id, key)` plus the
commit-conflict handler still dedup, i.e. the behaviour is defended in depth and the test
asserts the observable contract, not one mechanism.

**Fixture lessons banked (paid for by three false starts here):**
- Test-client requests call `db_session.remove()`, detaching fixture-loaded ORM objects —
  capture ids as plain values before `yield` or teardown raises `DetachedInstanceError`.
- `organisations <- users` is `ON DELETE CASCADE` but `users <- audit_logs` is `NO ACTION`;
  delete the org (cascades users+audit), not the user directly.
- A teardown that raises leaves orphans, and `OrganisationFactory`'s sequence names then
  collide next run. Teardowns must be rollback-first and FK-ordered.

### Batch 4 — Execution idempotency  (map row 12) ✅ DONE 2026-07-18 — NO NEW TESTS (gap analysis was wrong)
**What I expected:** an `ApiIdempotencyKey`-guarded execution create/complete path, untested.
**What the code actually is:** there is no execution idempotency-key mechanism at all.
`ApiIdempotencyKey` is referenced only by the wastage route (row 16, covered in Batch 3);
`create_execution` does a plain insert with no dedup. Row 12 was a misdiagnosis in the
original analysis — it conflated the wastage idempotency key with executions.

Execution *replay-safety* is instead the `complete_step` state machine, and that is already
well covered by `test_executions.py` (45 tests): out-of-order completion rejected
(`test_cannot_complete_step_2_before_step_1`), double-completion rejected
(`test_complete_step_already_completed_raises`), step-failure does not advance
(`test_complete_step_failure_does_not_advance_execution`), full-lifecycle completion, and
wrong-org → None. Writing new tests here would duplicate existing coverage — the exact
padding `test-evaluator` exists to reject — so the honest action was to **correct the map**
(row 11 → covered, row 12 → struck as non-existent), not to invent tests.

This is the gap analysis being held to the same honesty standard as the tests: a `none`
that turns out to be `covered`-or-nonexistent on inspection gets corrected, not filled.

### Batch 5 — Org CRUD & membership  (map rows 6/7: none → covered) ✅ DONE 2026-07-18
**Why:** org settings and user add/remove had no direct coverage; membership changes are an
auth-adjacent surface where a broken role check lets a member escalate.
Tests written (`tests/test_org_routes.py`, 11 tests, all green) via authed ADMIN + MEMBER
Flask test clients:
- ✅ GET /org returns the org; unauthenticated GET → 302 login redirect (the HTML-route
  contract; /api/* would be JSON 401).
- ✅ PATCH /org name as admin persists; PATCH as member → 403.
- ✅ GET /org/users lists members; POST as admin → 201, as member → 403, duplicate email → 400.
- ✅ DELETE member as admin → 200; deleting self → 400; unknown id → 404.
Validity: mutation disabling `requires_role`'s 403 turns exactly the two member-forbidden
tests red, the other nine stay green — the role boundary is genuinely exercised.
**Correction to the plan:** unauthenticated → 302 (not 401) for HTML routes; the assertion
matches the app's real dual-mode 401 handler rather than the plan's guess.

### Batch 6 — Close the partials  (rows 5, 9, 11, 17, 20)
**Why last:** these already have happy-path coverage; the gap is the missing unhappy/hostile
cases. Lower risk per row, but this is where `partial` becomes honest `covered`.
- Row 20 dashboard: cross-org leak test (org A's dashboard never counts org B's rows).
- Row 9 process CRUD: org-isolation cases on create/update/delete.
- Row 11 execution lifecycle: failure + partial-completion paths.
- Row 17 unit conversion: server-side utils in `app/core/utils/` (JS side already covered).
- Row 5 session: `session-timeout` PUT, password-change server path (row 4).
Factory dep: covered by earlier batches. Effort: **M**, splittable.

## Sequencing & dependencies

```
Batch 1 (guard)  ─── independent, do first (smallest, highest-integrity, no factories shared)
Batch 2 (isolation harness) ─── build the factories + world here; everything below reuses them
   ├── Batch 3 (wastage)      ← needs InventoryItem/Wastage factories + isolation pattern
   ├── Batch 4 (execution idem) ← needs Process/Execution factories
   └── Batch 5 (org routes)   ← independent of factories, can run parallel to 3/4
Batch 6 (partials) ─── last; consumes all factories, converts partial→covered
```

Each batch = one MR, graded by `test-evaluator` before it ships (mutation spot-checks on
the guard, isolation, and idempotency tests are mandatory — those are exactly the
"always probe" class). Two-round circuit breaker per `.agents/autonomy.md`.

## What this plan deliberately excludes

- Browser/E2E journeys → `e2e-playwright` (own spec).
- The 2FA live-server suites (rows 1-3) — they're `live`-gated, run under
  `uv run workflow start`; coverage there is a suite-warden/e2e concern, not new unit work.
- Line-coverage percentages — the map is flow-based on purpose.
