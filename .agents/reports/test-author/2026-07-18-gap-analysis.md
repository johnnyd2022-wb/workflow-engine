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

### Batch 1 — Inventory quantity-write guard  (map row 14: none → covered)
**Why first:** it is the mechanism that prevents untracked inventory mutations — the guard
itself is unproven, so every "the guard protects us" claim elsewhere rests on faith. Small,
self-contained, no cross-tenant surface.
Tests (`tests/test_inventory_quantity_guard.py`, new area file):
- direct `item.quantity = X` + flush **outside** any `allow_` block → raises
  `InventoryQuantityWriteForbiddenError`.
- each legitimate path succeeds under its reason: `create_inventory_item`
  (REPOSITORY_CREATE), `add_quantity_to_inventory_item` (REPOSITORY_ADD_QUANTITY),
  `set_inventory_item_quantity` (MANUAL_API_UPDATE).
- nested `allow_inventory_quantity_write(...)` → raises `RuntimeError` (ContextVar safety).
- the ContextVar resets after the block (a second unguarded write still raises) — proves
  the guard re-arms, the failure mode a leaked token would hide.
Factory dep: `InventoryItemFactory`. Effort: **S**.

### Batch 2 — Tenant isolation harness  (map row 8: none → covered)
**Why:** multi-tenancy is the product's core security boundary; a cross-org leak is silent
and catastrophic, and there is currently *no* automated proof any scoped repo enforces it.
This batch also establishes the reusable pattern rows 9/11/20 will copy.
Tests (`tests/test_multi_tenant_isolation.py` — a real pytest suite; the existing
`test_multi_tenant_api.py` is a manual `main()` script and stays as a manual tool):
- parametrised across the high-value scoped repos (process, execution, inventory, wastage):
  user in org A requesting org B's record by id → `None`/404; `list_*` for org A never
  returns org B's rows; a write/update targeting org B's id from org A is rejected.
- one negative control: same-org access **succeeds**, so the test proves scoping, not a
  blanket-deny bug.
Factory dep: `ProcessFactory`, `ExecutionFactory`, `InventoryItemFactory` + the
`two_org_two_world` fixture. Effort: **L** (foundational; unblocks later isolation cases).

### Batch 3 — Wastage idempotency + entry  (map row 16: none → covered)
**Why:** duplicate wastage on a retry corrupts stock and audit numbers; the advisory-lock +
payload-hash idempotency is entirely unproven.
Tests (`tests/test_wastage.py`, new area file):
- same wastage payload + same idempotency key submitted twice → one record, second returns
  the first (no double-decrement).
- different payload, same key → the conflict behaviour the code actually implements
  (characterise it, then assert it).
- wastage record is org-scoped (org A cannot list/read org B's wastage) — reuses Batch 2's
  harness.
Factory dep: `InventoryItemFactory`, `WastageFactory`. Effort: **M**.

### Batch 4 — Execution idempotency  (map row 12: none → covered)
**Why:** a retried execution that double-applies is a data-integrity bug; `ApiIdempotencyKey`
guards it and is untested outside CRM.
Tests (extend `tests/test_executions.py`):
- create-execution with a repeated idempotency key → same execution id, no duplicate row.
- complete-step replay with the same key → idempotent, no double state advance.
Factory dep: `ProcessFactory`, `ExecutionFactory`. Effort: **M**.

### Batch 5 — Org CRUD & membership  (map rows 6/7: none → covered)
**Why:** org settings and user add/remove have no direct coverage; membership changes are an
auth-adjacent surface.
Tests (`tests/test_org_routes.py`, new area file):
- GET/PATCH org settings happy path + wrong-org rejection.
- add user, list users, remove user; removing a user in another org → 404/forbidden.
- unhappy paths: unauthenticated → 401, non-member → 403, invalid payload → 400.
Factory dep: none beyond existing. Effort: **M**.

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
