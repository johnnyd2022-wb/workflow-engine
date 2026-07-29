# SPEC: inventory
status: reviewed
name: Core Inventory (items, quantity, wastage, CSV upload, reconciliation)
slug: inventory
blueprint: core_bp — routes split across
  `app/core/backend/backend.py` (item CRUD, adjust, wastage, out-of-stock),
  `app/core/backend/inventory_upload_routes.py` (units config, CSV validate/commit, barcode),
  `app/core/backend/reconciliation_routes.py` (untracked reconciliation Path A/B)
url_prefix: /api/core

## Description
The stock ledger of the app: inventory items (raw materials, intermediates, final
products) owned by an org, their on-hand `quantity` stored as `NUMERIC(18,4)`, and every
authorized path that mutates it.

Three layers matter, and the design intent is that the lower two are not bypassable:

1. **Routes** — CRUD over `inventory_items`, absolute-value quantity correction
   (`/adjust`), batched wastage disposal (`/wastage`), CSV bulk upload
   (validate → commit), barcode product lookup, and reconciliation of "untracked" items
   into either plain stock (Path A) or an execution output (Path B).
2. **Repositories** — `InventoryRepository` / `WastageRepository`: every read and write
   takes an explicit `org_id`, and every mutation emits a domain event through
   `EventWriter` (`inventory_item.created` / `.updated` / `.quantity_adjusted` /
   `.deleted` / `.wasted`).
3. **The quantity guard** — `app/core/domain/inventory_quantity_guard.py`. Defense in
   depth against *untracked* quantity mutation: a SQLAlchemy `before_flush` hook raises
   `InventoryQuantityWriteForbiddenError` unless the write happens inside
   `allow_inventory_quantity_write(<InventoryQuantityWriteReason>)`, a `before_execute`
   hook sets the transaction-local GUC `app.inventory_qty_guard` for Core INSERT/UPDATE
   on `inventory_items`, and a PostgreSQL trigger rejects the statement when neither the
   guard nor migration mode is on.

Quantity arithmetic is Decimal end to end (`coerce_stored_quantity`,
`parse_stored_quantity_to_decimal`, `quantity_to_api_str`); unit handling goes through a
single conversion table (`app/core/utils/unit_conversion.py`), and wastage batches are
made idempotent by a canonical SHA-256 of the normalized entries
(`wastage_entries_payload_hash`) stored against an `ApiIdempotencyKey` row.

## Users & permissions
- roles: any authenticated user of the org. No `@requires_role` gate anywhere in this
  surface — a MEMBER can create, edit, adjust, waste, and delete stock.
- tenant_scoped: yes. Every route resolves `org_id = UUID(g.org_id)` and passes it into
  the repository, which filters `InventoryItem.org_id == org_id` on every query.
- ASSUMPTION: the absence of role gating is deliberate (manufacturing floor operators
  need to record stock and wastage), not an oversight. Derived purely from the code —
  flagged for confirmation, since `/adjust` and `DELETE` are destructive and every other
  admin-ish surface in the app (`org`) does gate on `UserRole.ADMIN`.
- ASSUMPTION: these routes carry `@requires_auth` but **not** `@requires_org_scope`, and
  rely on `g.org_id` being populated by tenant-context middleware. Derived from the
  decorators present as of this review.

## Acceptance criteria

### Item lifecycle
- AC1: `POST /api/core/inventory` creates an item scoped to the caller's org with a
  quantity strictly greater than zero, a non-empty name and unit, and returns 201 with
  the created id, quantity (as an API string), and unit. Missing/zero/non-numeric
  quantity, missing name, or missing unit → 400.
- AC2: `POST /api/core/inventory` with a `barcode` that already exists **in the caller's
  org** does not create a second row: it adds the quantity to the existing item (200,
  `quantity_added: true`) and appends an `inventory_audit_history` entry recording
  operator, timestamp, source method, and the stock-level supplier/dates/batch. A
  supplied `name` or `unit` that disagrees with the existing product → 409.
- AC3: `POST /api/core/inventory` with `untracked: true` requires non-empty `notes` (400
  otherwise) and always sets `extra_data.remaining_balance_to_reconcile` alongside
  `extra_data.untracked` — the invariant the reconciliation and sourcemap banners read.
- AC4: `PUT /api/core/inventory/<item_id>` updates an item that belongs to the caller's
  org and returns 200 with the new values; an id belonging to another org (or no org) →
  404, never 200 and never a mutation.
- AC5: `POST /api/core/inventory/<item_id>/adjust` sets an absolute new quantity,
  requires `new_quantity` (400 if absent/blank), rejects a non-numeric or negative value
  with 400, emits `inventory_item.quantity_adjusted` with before/after/delta, and returns
  404 for an item outside the caller's org.
- AC6: `DELETE /api/core/inventory/<item_id>` emits an `inventory_item.deleted` tombstone
  event carrying a full snapshot **before** the row is removed, returns 200 on success
  and 404 when the item doesn't resolve within the caller's org.
- AC7: `GET /api/core/inventory` lists only the caller's org's items, omits items whose
  quantity is `<= 0` (or `< 0.0001`), and supports `?type=` and `?process_id=` filters;
  a malformed `process_id` → 400.
- AC8: `GET /api/core/inventory/out-of-stock` returns exactly the caller's org's
  raw-material items whose quantity is exactly zero (for recall tracing), and never
  another org's.

### Quantity guard (the invariant this feature exists to protect)
- AC9: Any code path that changes `inventory_items.quantity` outside
  `allow_inventory_quantity_write(...)` raises `InventoryQuantityWriteForbiddenError` at
  flush time — ORM assignment alone is not enough to persist a change.
- AC10: Every authorized write names its reason from `InventoryQuantityWriteReason`, and
  the reason is visible in the emitted event (`reason` on `.quantity_adjusted`) or the
  span attributes.
- AC11: On PostgreSQL, a raw `INSERT`/`UPDATE` against `inventory_items` outside the
  guard is rejected by the DB trigger even if it bypasses the ORM (migrations exempted
  via `app.migration_mode`).

### Wastage
- AC12: `POST /api/core/inventory/wastage` accepts a batch of entries
  (`inventory_item_id`, `quantity_wasted`, `reason`, optional `quantity_unit`), and
  rejects with 400 + `VALIDATION_FAILED`: a non-object entry, a missing/invalid item id,
  a duplicate item id within the batch, a non-positive/non-finite/out-of-range quantity,
  a missing reason, or a reason over 500 characters.
- AC13: A batch larger than `MAX_WASTAGE_BATCH_ENTRIES` → 400 `BATCH_TOO_LARGE`.
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

### CSV upload
- AC20: `POST /api/core/inventory/csv-validate` accepts a multipart `file` or a raw CSV
  body, rejects a file over 2 MB (400) and non-UTF-8 content (400), requires the columns
  Item Name / Quantity / Unit (case-insensitive, 400 listing what's missing), and returns
  a per-row `status`/`message` without writing anything.
- AC21: Validation is row-level and shared with commit (`_validate_row`): a blank name, a
  blank/non-numeric/non-positive quantity, or a unit outside `CONVERSION_FACTORS` marks
  that row `error` with a specific message.
- AC22: More than `CSV_MAX_ROWS` (500) rows are truncated at validate time with
  `truncated: true`, and rejected outright at commit with 400.
- AC23: `POST /api/core/inventory/csv-commit` **re-validates every row server-side** and
  returns 400 with no writes if any row fails — the client's validate result is never
  trusted.
- AC24: On commit, a row that collides with the (org, item name, batch number) unique
  constraint is skipped with a per-row error while the remaining rows still commit
  (each row in its own savepoint), and the response explains which case occurred (some
  skipped vs none committed).
- AC25: Every CSV-created item records an `inventory_audit_history` entry with the
  acting user, UTC timestamp, `source_method: csv_upload`, and the CSV row index.

### Barcode & units
- AC26: `GET /api/core/inventory/barcode/<code>` returns `{exists: false}` for an unknown
  or blank code and, for a known one, the canonical name/unit/supplier/quantity of the
  matching item **in the caller's org only**.
- AC27: `GET /api/core/config/units` returns the allowed unit list derived from
  `CONVERSION_FACTORS` — the same single source of truth the validators use, so the
  dropdown cannot offer a unit the backend rejects.
- AC28: `POST /api/core/inventory/decode-barcode` is deprecated and returns 410 with an
  explanatory message (decoding happens in the browser).

### Reconciliation of untracked stock
- AC29: `GET /api/core/inventory/reconcile/matching-untracked` returns untracked items in
  the caller's org matching `name` + `unit` (both required; empty result otherwise),
  optionally narrowed by `process_id` (400 if malformed) and `execution_id`.
- AC30: `POST /api/core/inventory/reconcile/via-addition` (Path A) requires name,
  quantity and unit (400 otherwise), validates `untracked_item_id` as a UUID (400
  otherwise), and adds stock optionally mapped onto an untracked item.
- AC31: `POST /api/core/inventory/reconcile/via-execution` (Path B) requires
  `untracked_item_id`, `process_id`, `step_id`, output name, quantity and unit, rejects
  malformed UUIDs with 400, and maps the untracked item onto a newly created execution
  output.
- AC32: Both reconciliation paths operate only on rows in the caller's org; ids belonging
  to another org must not resolve.

### Cross-tenant isolation (the probe every route must survive)
- AC33: A user authenticated into org A cannot read, list, create-referencing,
  update, adjust, waste, delete, reconcile, or barcode-look-up any inventory row,
  wastage record, or movement belonging to org B — on **every** route above. Failure
  mode must be 404/400 "not found", never 403-with-detail or a partial disclosure of the
  other org's data.

## Data model
- tables: `inventory_items` (`quantity NUMERIC(18,4)`, org-scoped, unique
  (org, name, supplier_batch_number) when batch is set; unique (org, barcode)),
  `inventory_wastage`, `inventory_movements` (append-only ledger, `source_wastage_id`
  unique), `api_idempotency_keys` (unique (org_id, key)).
- changes: none proposed by this review.
- destructive: no. `DELETE /api/core/inventory/<id>` is a hard row delete but emits a
  tombstone event first — the event log, not the row, is the audit trail.

## External surfaces
- none. No outbound HTTP; the handler docstring explicitly forbids external I/O inside
  the wastage transaction (it would break the dual-write guarantee under rollback).

## Out of scope
- Lineage tracing (`/api/core/inventory/trace/<id>`, `/trace-backward/<id>`,
  `dagtraversal`) — belongs with the workflow-engine surface, audited separately.
- Execution-step inventory consumption
  (`InventoryQuantityWriteReason.EXECUTION_STEP_INVENTORY`) — the write is authorized
  from the executions surface; only the guard contract is in scope here.
- `resetdb` demo seeding (`RESETDB_DEV`), which is gated to local/test environments.
- The vanilla-JS inventory frontend (`app/core/frontend/`), except where an E2E flow
  proves an AC above.

## Notes for the audit
Every AC above except the ASSUMPTION lines was derived by reading the implementation, so
each one is trivially satisfied by construction. The audit's job is therefore **not** to
re-confirm them, but to attack them: the ACs are the contract that the security,
tenant-isolation, and E2E stages get to falsify. AC9–AC11 (the guard), AC14/AC17/AC18
(atomicity + idempotency), and AC33 (cross-tenant) are the ones worth real adversarial
effort; the rest are shape checks.
