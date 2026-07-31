# TEST AUTHORING — 2026-07-29

mode: gap-fill (unit-coverage sweep) + evaluator-remediation
preflight: test_db=up, live_server_tests=run (decisions taken as given by the router; not re-derived)
flows_touched: 15 (Inventory read/add/out-of-stock/update/delete), 16 (Wastage entry + idempotency), 25 (CSV bulk upload, new row), 26 (Untracked-item reconciliation, new row)

## Scope

Two workstreams, per the task brief:

1. Close unit-level coverage gaps the audit measured on `inventory_upload_routes.py`,
   `reconciliation_routes.py`, `inventory_repo.py`, `inventory_quantity.py`,
   `inventory_wastage_quantity.py` (priorities 1–4).
2. Land the items test-evaluator's two grading rounds explicitly deferred to test-author:
   AC14 three-way atomicity, AC16 wastage unit-conversion, and 12 named assertion-strength
   findings (2 in `tests/test_inventory.py`, 10 in the e2e-playwright files).

Browser-level flows were not duplicated — the e2e assertion-strength fixes are narrow
edits to existing Playwright tests (stronger assertions on data the request already
produced), not new browser scenarios.

## tests_added

**`tests/test_inventory_csv_validation.py`** (new, 32 tests) — pure unit tests, no DB/server,
for `inventory_upload_routes.py`'s shared preview/commit validators: `_allowed_units_list`,
`_unit_to_canonical`, `_parse_quantity`, `_validate_row`, `_parse_date` (all three accepted
formats + invalid), `_sanitize` (control-char stripping, 255/500-char truncation).

**`tests/test_inventory_quantity.py`** (new, 18 tests) — pure unit tests for
`inventory_quantity.py`: `coerce_stored_quantity` (None, quantize, non-finite, huge
exponent), `quantity_to_api_str` (None/non-finite fallback, trailing-zero trim),
`assert_movement_unit_matches_item_canonical` (match/mismatch/normalization),
`parse_stored_quantity_to_decimal` (None, passthrough, legacy string, non-finite).

**`tests/test_inventory_wastage_quantity.py`** (new, 17 tests) — pure unit tests for
`inventory_wastage_quantity.py`: `parse_wastage_unit_field` (non-string rejection),
`parse_wastage_quantity` (negative-zero, out-of-range magnitude, boundary value),
`wastage_entries_payload_hash` (order-stability — the AC17 idempotency contract itself —
non-Decimal quantity normalization, missing-vs-empty unit normalization).

**`tests/test_inventory_repo.py`** (new, 8 tests) — repository-level tests for
`InventoryRepository.update_inventory_item` (quantity vs no-quantity branch, each verified
against the emitted `EntityEvent` diff) and `delete_inventory_item` (tombstone event
persists with the pre-deletion snapshot after the row is gone — the actual point of AC6 —
plus org-scoping on both methods).

**`tests/test_reconciliation_routes.py`** (+9 tests) — AC29/AC30 400 request-validation
paths: malformed `process_id`, missing name/quantity/unit on via-addition, malformed
`untracked_item_id`, missing `untracked_item_id`/`process_id`/`step_id` on via-execution.

**`tests/test_wastage.py`** (+14 tests):
- `test_wastage_batch_failure_rolls_back_item_wastage_and_movement_together` — **AC14**.
  Monkeypatches `assert_movement_unit_matches_item_canonical` to raise on the second staged
  entry of a two-item batch, then asserts both items' quantity, and zero `InventoryWastage`
  / `InventoryMovement` rows survive — proving the first entry's already-flushed writes
  roll back with the batch, not just the second. **Mutation that turns it red:** committing
  per-entry inside the loop instead of once at the end (or removing the outer
  `except Exception: db_session.rollback()`).
- `test_wastage_converts_compatible_non_canonical_unit_and_records_metadata` — **AC16**.
  Wastes `500 g` against a `kg` item; asserts the deduction is the *converted* 0.5 kg, the
  `InventoryWastage`/`InventoryMovement` rows are stored in canonical `kg`, and
  `movement_metadata` carries `converted_from_unit`/`canonical_unit`. **Mutation:** storing
  the raw unconverted unit/quantity, or dropping the metadata keys.
- `test_wastage_rejects_incompatible_unit_with_400` — AC16's negative case (volume unit
  against a mass-tracked item), plus proves no deduction happened.
- `test_wastage_rejects_idempotency_key_over_128_chars` / `_empty_idempotency_key` /
  `_non_string_idempotency_key` — AC17's three invalid-key forms.
- `test_wastage_batch_rejects_more_than_max_entries` — AC13, plus proves zero writes.
- `test_wastage_rejects_duplicate_item_id_within_batch` — AC12.
- `test_wastage_rejects_wasting_more_than_on_hand` — AC15.
- `test_wastage_rejects_non_object_entry` / `_missing_item_id` / `_invalid_item_id` /
  `_missing_reason` / `_reason_over_500_chars` — the rest of AC12's hostile validation
  matrix (previously only duplicate-id was covered).

**`tests/test_inventory.py`** (+1 test): `test_csv_commit_records_acting_user_in_audit_history`
— the DB-level half of AC25 (see `tests_updated` below for why it isn't asserted via the
API in the e2e file).

## tests_updated

**`tests/test_inventory.py`** (existing regression file — extended, not restructured):
- `test_list_inventory_by_process_id_does_not_match_another_orgs_execution` — added a
  same-org positive control (`Own Process Item`) so absence of the foreign item proves
  filtering, not a globally-broken filter. *Justifying change: test-evaluator round 2
  finding — the test had no positive control.*
- `test_create_accepts_every_valid_inventory_type` — now asserts the stored row's
  `inventory_type` matches what was sent, not just a 201. *Same finding.*
- Added `test_update_rejects_huge_exponent_quantity_with_400` — F3 on the PUT route
  (previously create-only); included `name`/`unit` in the payload so the 400 is provoked by
  the quantity bug, not the route's independent required-fields check (verified this
  distinction by hand — an earlier draft of this test would have been vacuous).

**`tests/e2e/test_inventory_flow.py`** (assertion-strength fixes, test-evaluator round 2):
- `test_out_of_stock_lists_zero_quantity_raw_materials` — added a nonzero raw-material
  decoy and a zeroed final-product decoy, so "exactly" (AC8) is actually proven.
- `test_config_units_returns_allowed_units` — now asserts set-equality with
  `CONVERSION_FACTORS.keys()`, not membership of two values.
- `test_decode_barcode_is_deprecated_and_returns_410` — asserts the explanatory message
  (AC28), not just an `error` key's presence.
- `test_reconcile_matching_untracked_returns_untracked_items` — added differently-named and
  differently-unitted decoys that must be absent from the match set.
- `test_reconcile_via_addition_maps_onto_untracked_item` — its two 400 branches now prove
  no row was created (listing count unchanged), not just the status code.

**`tests/e2e/test_inventory_csv_flow.py`** (assertion-strength fixes, test-evaluator
round 2):
- `test_csv_validate_happy_path_returns_per_row_status` — asserts the follow-up listing
  request itself succeeded (200) before trusting its text as no-write proof.
- `test_csv_validate_rejects_missing_required_columns` — now drops each of the three
  required columns independently (previously only Unit).
- `test_csv_commit_happy_path_creates_item_with_audit_history` — asserts the UTC timestamp
  suffix. **Did not** add the `user_id` assertion here: `GET /api/core/inventory`
  deliberately strips `user_id` from audit-history entries for list responses
  (`_bound_inventory_extra_data_for_list_response`, backend.py:111–124, "operator UI
  only") — asserting it through this endpoint can never pass. Found this by actually
  running the test (see Runtime verification below), not by inspection alone. Moved that
  half of AC25 to a DB-level test instead (`test_csv_commit_records_acting_user_in_audit_history`,
  tests/test_inventory.py) and cross-referenced both docstrings.
- `test_csv_commit_rejects_over_max_rows` — proves zero rows of the batch were written
  (distinctive marker name absent from the listing).
- `test_csv_commit_skips_duplicate_batch_but_commits_the_rest` — now queries the colliding
  `(org, name, batch)` row's final count/quantity, proving it wasn't bumped or duplicated.

## map_rows_changed

- **Row 15** (Inventory read/add/out-of-stock) — `partial → covered`: update/delete repo
  mutations, CSV pure helpers, PUT-route F3, AC8/AC27 decoy strengthening.
- **Row 16** (Wastage) — stayed `covered`, note extended with AC14/AC16/AC12/AC13/AC17.
- **Row 25** (CSV bulk upload) — new row, `covered`.
- **Row 26** (Untracked-item reconciliation) — new row, `partial → covered`.

## Remaining lower-severity gaps (explicitly deprioritized by the task; not closed)

- `EntityEventSummary.org_id` defense-in-depth filter has no regression test (test-evaluator
  noted this is low risk: the pre-fix query was not exploitable).

## suite_result

`uv run pytest tests/ -q --ignore=tests/e2e`: **623 passed, 0 skipped** (dev server is up
per the router's `live_server_tests: run` decision, so no suites skip in this run) — plus
the 5 additional AC12 tests added after that run, individually verified green
(`uv run pytest tests/test_wastage.py -q`: 18 passed).

`uv run pytest tests/e2e/test_inventory_flow.py tests/e2e/test_inventory_csv_flow.py
tests/e2e/test_tenant_isolation.py -q`: **34 passed** (23 + 11; the tenant-isolation file
was pre-existing from an earlier stage, not touched by this batch — run as a sanity check
only).

`uv run ruff check` over every added/edited test file and the touched app modules: clean.
(9 pre-existing lint findings elsewhere in `tests/` — `test_perf_budgets.py`,
`test_corechecks.py`, `test_executions.py` — are untouched by this batch.)

## Runtime verification note

One authored assertion (`user_id` via the CSV commit e2e test) was caught by actually
running the suite, not just review: the live-server run raised `KeyError: 'user_id'`
because the list endpoint redacts it by design. Fixed by moving that assertion to a
DB-level test and documenting the redaction in both files' docstrings so a future reader
doesn't reintroduce the same wrong assumption.

## evaluator_verdict

Not yet re-submitted to test-evaluator — this report is the handoff point. Per the
test-author skill, the batch (`git diff --name-only main...HEAD -- 'tests/**'`) must go to
test-evaluator before shipping; ship is blocked on `valid`.

verdict: gaps-open
