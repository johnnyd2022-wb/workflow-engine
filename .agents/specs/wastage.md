# SPEC: wastage
status: reviewed
name: Inventory Wastage (disposal recording, batch, idempotency)
slug: wastage
blueprint: core_bp — app/core/backend/backend.py (record_wastage, list_wastage,
  inventory_dispose, inventory_dispose_confirm)
url_prefix: /api/core, /core

## Description
Records inventory quantity written off as waste/disposal: a batched API
(`POST /api/core/inventory/wastage`) that deducts on-hand quantity and writes an
`InventoryWastage` row plus a signed `inventory_movements` ledger row in one transaction,
a listing API for sourcemap/trace, and two HTML pages that drive the operator-facing
disposal flow (`/core/inventory/dispose`, `/core/inventory/dispose/confirm`).

Distinct from an inventory adjustment (`/adjust`, absolute correction): wastage is a
signed deduction with its own compliance meaning and its own idempotency mechanism — a
PostgreSQL transaction-scoped advisory lock (`_pg_advisory_lock_wastage_idempotency`,
keyed on `org_id`+`idempotency_key`), separate from the app's other `ApiIdempotencyKey`
consumers, which rely on the row's unique constraint alone.

## Provenance
No standalone spec existed for this slice before this review (feature-index:
`reviewed: never`). Its acceptance criteria were largely already written and reviewed as
part of `.agents/specs/inventory.md` (AC12–AC19, AC33) during the **inventory** slice
review (2026-07-27→29, commits `e748618`/`ac49b2c`, confirmed merged ancestors of this
branch) — inventory.md's F2 fix (`InvalidOperation` on `?quantity_wasted=nan`) already
touches `inventory_dispose_confirm`, one of this slice's own routes. AC12–19/AC33 below
are extracted from that spec, re-verified against the current code (matches — see
baseline.md), not re-derived from scratch. AC-D1–D3 (the two HTML pages) are new: they
were never given AC numbers in inventory.md and are ASSUMPTION lines here.

## Users & permissions
- roles: any authenticated user of the org (no `@requires_role` gate) — consistent with
  the rest of the inventory surface.
- tenant_scoped: yes. `InventoryWastage` inherits `TenantScoped`
  (`app/core/db/models/inventory_wastage.py:14`, adopted in commit 35e4ec9 on this
  branch's own tenant-scoping effort). All four routes resolve `org_id` from `g.org_id`.
- ASSUMPTION: routes carry `@requires_auth` only, not `@requires_org_scope` — same
  pattern as the rest of `backend.py` (0 usages of `@requires_org_scope` in the file);
  not a wastage-specific gap.

## Acceptance criteria

### Wastage API (extracted from inventory.md, re-verified against current code)
- AC12: `POST /api/core/inventory/wastage` accepts a batch of entries
  (`inventory_item_id`, `quantity_wasted`, `reason`, optional `quantity_unit`), and
  rejects with 400 + `VALIDATION_FAILED`: a non-object entry, a missing/invalid item id,
  a duplicate item id within the batch, a non-positive/non-finite/out-of-range quantity,
  a missing reason, or a reason over 500 characters.
- AC13: A batch larger than `MAX_WASTAGE_BATCH_ENTRIES` (100) → 400 `BATCH_TOO_LARGE`.
- AC14: Each entry deducts from the item under a `SELECT … FOR UPDATE` row lock, and the
  whole batch is written in **one** transaction: `inventory_items.quantity`,
  `inventory_wastage`, and `inventory_movements` (signed `WASTAGE` row linked by
  `source_wastage_id`) all commit together or not at all. No partial apply.
- AC15: Wasting more than is on hand → 400 with the on-hand quantity named; wasting from
  an item with zero quantity → 400; wasting from an item in another org → 400 "not found
  or access denied" (indistinguishable from a nonexistent id).
- AC16: When `quantity_unit` is supplied it must be compatible with the item's unit
  (`are_units_compatible`), is converted with `convert_to_inventory_unit_decimal`, and
  the ledger row is written in the item's canonical unit with
  `converted_from_unit`/`canonical_unit` recorded in `movement_metadata`. An
  incompatible unit → 400.
- AC17: Replaying the same `idempotency_key` with the same canonical payload hash returns
  the **stored** response with `idempotent_replay: true` and does not deduct twice; the
  same key with a different payload → 409 `IDEMPOTENCY_PAYLOAD_MISMATCH`; an
  `idempotency_key` that isn't a non-empty string ≤128 chars → 400.
- AC18: Concurrent duplicate submissions of the same org+key are serialized by a
  transaction-scoped PostgreSQL advisory lock, and a losing commit race is resolved by
  re-reading the stored response rather than double-deducting.
- AC19: `GET /api/core/inventory/wastage` lists the caller's org's wastage records
  (optionally filtered by `inventory_item_id`, 400 on a malformed one) and resolves item
  names only from items in the caller's org.

### Disposal pages (new — not previously given AC numbers)
- AC-D1 (ASSUMPTION): `GET /core/inventory/dispose` renders the full-page disposal flow
  and accepts an optional `item_ids` CSV query param to preselect items; requires
  `@requires_auth` only, does no server-side ownership check of the passed ids at render
  time (the page's own JS/API calls are the security boundary — matches the route
  docstring "Confirm/dispose UI pages are not a security boundary").
- AC-D2 (ASSUMPTION): `GET /core/inventory/dispose/confirm` computes a remaining-quantity
  preview from `inventory_item_id` + `quantity_wasted` query params, scoped to the
  caller's org (`InventoryItem.org_id == org_id`); a missing/invalid item id, a
  non-finite/negative/unparseable quantity, or an item not resolving in-org all set a
  page-level `error` string and render 200 (not 500, not 404) — confirmed fixed for the
  `NaN` case by the inventory review's F2 (commit e748618).
- AC-D3 (ASSUMPTION): an item belonging to another org, referenced via
  `inventory_item_id`, must not leak its name/unit/quantity onto the confirm page — falls
  back to the default `"item"` name and empty unit/quantity, same as a nonexistent id.

### Cross-tenant isolation (the probe every route must survive)
- AC33 (wastage scope): a user authenticated into org A cannot read, list, waste, or
  preview-dispose any inventory item or wastage record belonging to org B, on all four
  routes above. Failure mode must be 404/400 "not found", never 403-with-detail or
  partial disclosure. Covered by `tests/e2e/test_tenant_isolation.py`
  (`test_org_b_wastage_list_excludes_org_a_records`, the wastage-on-foreign-id case, and
  `test_org_b_dispose_confirm_page_does_not_leak_org_a_item` for the AC-D2/D3 HTML page).

## Data model
- tables: `inventory_wastage` (org-scoped via `TenantScoped`, FK to `inventory_items`,
  `reason` nullable — pre-field-addition rows have none, new API-layer writes require it).
- changes: none proposed by this review.
- destructive: no.

## External surfaces
- none. Handler docstring explicitly forbids external I/O inside the wastage transaction.

## Out of scope
- `WastageRepository.create_wastage_record` — defined but has no production caller; used
  only by `tests/factories.py` to seed wastage rows for fixtures. Not a route, not a
  finding — flagged for awareness, not remediation.
- Item CRUD, CSV upload, reconciliation, barcode — covered by the `inventory` slice.
- Lineage/trace of wastage records — `traceability` slice.

## Notes for the audit
AC12–19/AC33(API) are shape-checks already exercised by `tests/test_wastage.py` (25/25
green) and `tests/e2e/test_tenant_isolation.py`. AC-D3's cross-tenant probe is now covered
(`test_org_b_dispose_confirm_page_does_not_leak_org_a_item`), and AC18's advisory-lock
concurrency claim is proven under true two-thread concurrency
(`tests/test_wastage.py::test_wastage_advisory_lock_serializes_concurrent_duplicate_submissions`).
Remaining gap: AC-D1 (`GET /core/inventory/dispose`) still has no dedicated test file.
