# SPEC: reconciliation
status: reconstructed
name: Untracked Inventory Reconciliation
slug: reconciliation
blueprint: app/core/backend/reconciliation_routes.py, reconciliation_service.py (attached to
core_bp via register_routes(bp) — no dedicated blueprint object)
url_prefix: /api/core/inventory/reconcile

## Description
Untracked inventory items are `InventoryItem` rows flagged `extra_data.untracked = true`
(created via the general inventory-create route, `backend.py:3599`, when the caller marks
an addition as `untracked`). They represent physical stock discovered without a clean
system-of-record link to the process/execution that produced it. Reconciliation is the
process of matching an untracked item's remaining balance against a live-system event,
reducing the untracked balance and creating only the surplus (if any) as a normal, fully
sourced inventory item. There are three reconciliation paths, only two of which are
directly HTTP-facing:

- **Path A (`via-addition`)**: user manually adds a quantity to inventory and optionally
  maps it against one untracked item as they add it.
- **Path B (`via-execution`)**: user maps an untracked item to a specific process/step by
  retroactively running that step (creating a new execution, silently auto-completing any
  earlier incomplete steps with empty input/output, then completing the target step with
  one declared output).
- **Path C (internal, not a route)**: triggered from inside `execution`'s `complete_step`
  (`backend.py:2499-2538`) when the user tags a step's declared output with an
  `untracked_item_id` at completion time — the normal execution-output flow, but the
  output is reconciled against the untracked item first and only the surplus becomes a new
  inventory row. This is the same underlying math as Path B but invoked by the execution
  slice, not this one; it's in scope for this review because the function that implements
  it (`reconcile_output_to_untracked_reduce_only`) lives in `reconciliation_service.py`.

A companion read endpoint (`matching-untracked`) lets the frontend look up untracked items
by name/unit (optionally scoped to a process or execution) to populate the reconciliation
UI (`add-inventory-reconciliation.js`, `map-to-execution-reconciliation.js`, called through
`core-api.js`).

`reconcile_output_to_untracked` (no `_reduce_only` suffix) is present in the service module,
explicitly marked `DEPRECATED` in its own docstring, and has **no caller anywhere in
`app/`** (confirmed by grep) — dead code, not part of any current path. Flagged under
Assumptions/Out of scope rather than treated as a live AC.

## Users & permissions
- roles: any authenticated org member (`@requires_auth` on all three routes; no elevated
  role check observed)
- tenant_scoped: yes — every entry point takes `org_id` (from `g.org_id`) explicitly and
  every repository call in the service filters on it inline (`get_untracked_items`,
  `get_inventory_item_by_id_for_update`, `create_inventory_item`, `update_inventory_item`,
  and `ExecutionRepository.create_execution`, which additionally raises if `process_id`
  doesn't belong to `org_id`)

## Acceptance criteria

- AC1 (`GET matching-untracked`): given `name` and `unit` query params, returns
  `{"matching_untracked": [...]}` of untracked items (`extra_data.untracked == true`) for
  the caller's org whose name matches case-insensitively and unit matches exactly. Missing
  `name` or `unit` returns an empty list with 200, not a 400. Items with `quantity <= 0`
  are excluded **unless** `execution_id` is also given, in which case a zero-quantity item
  is still included if it was consumed within that execution or still carries
  `remaining_balance_to_reconcile > 0`. Each returned item is enriched with
  `process_name`, `step_name`, `source_step_completed_by`, `source_step_execution_prompts`,
  and `producing_step_name`/`producing_step_id` (the step whose declared output matches
  the item's name+unit, used to drive the "run this step" reconcile-via-execution UI).
- AC2 (`POST via-addition`): requires `name`, `quantity` (> 0), `unit`; `untracked_item_id`
  is optional. Always creates one new `InventoryItem` for the full `quantity` given (not
  reduced by any reconciliation). When `untracked_item_id` is given: 404s as
  `{"error": "Untracked item not found"}` if it doesn't resolve under the caller's org;
  400s if the resolved item's `extra_data.untracked is not True`, or if it has
  `quantity <= 0` (nothing left to reconcile), or if `unit` is not compatible with the
  untracked item's unit (`are_units_compatible`). Otherwise reduces the untracked item's
  balance by `min(added_qty_in_untracked_unit, untracked_balance)`, appends one
  `reconciliation_history` entry (`method: "add_to_inventory"`), and sets
  `resolved`/`resolved_at` on the untracked item once its balance reaches 0. The response
  echoes the new item plus `reconciled_amount`, `surplus`, `remaining_untracked_balance`.
- AC3 (`POST via-execution`): requires `untracked_item_id`, `process_id`, `step_id`,
  `output_name` (or `name`), `output_quantity` (or `quantity`, > 0), `output_unit` (or
  `unit`). 400s on any missing field, non-numeric quantity, or a `process_id`/`step_id`
  combination where the step doesn't belong to that process (returned as
  `{"error": "Step not found in this process"}`) or an ID that fails `UUID(...)` parsing
  (400 with a fixed message — **not** the raw parse-exception text; regression-tested in
  `tests/test_reconciliation_routes.py`). 404-equivalents (item/step not found) are
  returned as `{"error": ...}` with **200 status by the service, remapped to 400 by the
  route** (see Notes — this conflates "not found" and "bad request" under one status). On
  success: creates one new `Execution` against `process_id`, auto-completes (with empty
  actual_inputs/outputs) any step before the target step that isn't already `COMPLETED`,
  completes the target step with exactly one declared output
  (`{name: output_name, quantity: str(output_quantity), unit: output_unit}`), creates one
  new `InventoryItem` for that output (type `FINAL_PRODUCT` if the step `is_terminal_step`
  else `WORK_IN_PROGRESS`), and reduces the untracked item's balance by
  `min(output_qty_in_untracked_unit, untracked_balance)`. **Idempotency**: rejects with
  `{"error": "This untracked item has already been reconciled against this process
  step."}` if `reconciliation_history` already contains a `method: "map_to_execution"`
  entry for the same `(process_id, step_id)` pair on this untracked item — re-submitting
  the identical request a second time is a no-op rejection, not a duplicate execution.
- AC4 (Path C, internal — `reconcile_output_to_untracked_reduce_only`): given an
  execution-step output tagged with `untracked_item_id` at completion time, reduces the
  untracked item's balance by `min` of (output quantity converted to the untracked unit,
  effective on-hand balance, and any previously stored
  `remaining_balance_to_reconcile`) and returns `reconciled_amount`/`surplus` to the
  caller (`complete_step` in `backend.py`), which creates a live inventory row **only for
  the surplus** (skipped entirely if surplus is ~0, threshold `Decimal("0.0001")`).
  Additionally validates the output's `name` matches the untracked item's `name`
  case-insensitively (AC2/AC3 do not require a name match; this path does) and unit
  compatibility. Persists `remaining_balance_to_reconcile` in `extra_data` so a partially
  reconciled item (on-hand quantity already fully consumed elsewhere) still shows the
  correct outstanding amount.
- AC5 (cross-cutting validation): every path rejects non-positive/unparseable quantities,
  rejects unit-incompatible pairs (`are_units_compatible`), and — for the two write
  paths that mutate an untracked item — takes a row-level lock
  (`get_inventory_item_by_id_for_update`, `SELECT ... FOR UPDATE`) before reading its
  balance, so two concurrent reconciliations against the same untracked item cannot both
  read a stale balance and double-spend it.
- AC6 (invariant guard): before any reconciliation write commits, quantities are asserted
  non-negative in `_assert_reconciliation_invariants` — the stored `quantity` and any
  `remaining_balance_to_reconcile` in `extra_data` must both be `>= 0`, raising `ValueError`
  (not silently clamping) if a bug would otherwise persist a negative balance.
- AC7 (audit trail): every successful reconciliation (Paths A, B, C) appends one entry to
  the untracked item's `extra_data.reconciliation_history` list — never overwrites prior
  entries — recording timestamp, acting user (id + email), method, and the amounts
  involved, so `matching-untracked`'s `source_step_execution_prompts` / activity views can
  reconstruct who reconciled what and when.
- AC8 (tenant isolation): a request naming an `untracked_item_id`, `process_id`, or
  `step_id` that exists but belongs to a different org must fail exactly as if it didn't
  exist (`"Untracked item not found"` / `"Step not found in this process"` /
  `ExecutionRepository.create_execution`'s org-membership check on `process_id`) — no path
  reveals whether the ID exists in another org. **Not yet covered by any test** — this is
  the primary target for the security-audit + e2e-playwright stages below, since the index
  flags reconciliation as untested and org-scoped mutation of another tenant's inventory
  balance is the highest-severity failure mode this slice could have.

## Data model
- changes: none — this slice defines no models of its own; it reads/writes
  `InventoryItem.extra_data` (a JSON column) and reads `Execution`/`ExecutionStep` via
  existing repositories.
- destructive: no (all writes are quantity/JSON field updates or new-row inserts; nothing
  is deleted)

## External surfaces
- none (no third-party APIs, uploads, or background jobs; all three routes are synchronous
  request/response behind `@requires_auth`)

## Out of scope
- `reconcile_output_to_untracked` (non-`_reduce_only` variant) — dead code, no caller;
  flagged for removal as a finding, not exercised or specified further here.
- The `matching-untracked` process/execution filtering logic's exact semantics beyond
  "narrows results" — read-only convenience endpoint, lower risk than the two write paths.
- Anything in `execution`'s own `complete_step` flow beyond the one call it makes into this
  service (AC4) — that function's broader correctness is the execution slice's concern.

## Assumptions (reconstructed from code — flag for confirm)
- ASSUMPTION: the 404-shaped errors ("not found") in `via-execution` are returned with
  HTTP 400 rather than 404, because the route uniformly does
  `if "error" in result: return ..., 400`. Read this as existing, intentional-by-omission
  behavior, not a bug to silently "fix" during this review — call it out as a finding
  instead, since normalizing it changes a public API's status codes.
- ASSUMPTION: "no dedicated role check" is intentional — every org member can reconcile
  inventory, matching the rest of the inventory API's permission model (no elevated role
  concept exists elsewhere in `core_bp` either).
- ASSUMPTION: the AC8 tenant-isolation claim (no path leaks cross-org existence) is stated
  as a requirement to verify, not a fact already proven by a passing test — the only
  existing test in `tests/test_reconciliation_routes.py` checks error-message content
  (no exception-text leakage), not cross-org access. This spec's "reconstructed from code
  reading, not test coverage" caveat applies most strongly here; treat AC8 as unverified
  until the audit stage proves it.
