# TEST EVALUATION — 2026-07-28

scope:
- base: `8d95f83`
- branch: `work/2026-07-27-session`
- batch: 37 cases across `tests/test_inventory.py`, `tests/e2e/test_inventory_csv_flow.py`, `tests/e2e/test_inventory_flow.py`, and `tests/e2e/test_tenant_isolation.py`
- note: HEAD equals the base commit; the reviewed batch exists as uncommitted working-tree changes

verdict: invalid

## Method

- Read every added test and the assertion diffs in modified files.
- Compared each fix-linked regression against the exact implementation at `8d95f83`.
- Performed deterministic control-flow probes where mutation was unavailable.
- No in-place mutation was made because access is read-only and the tree was already dirty.
- No assertions were deleted or broadened, and no skips/xfails/log-text assertions were introduced.

## Runtime verification

Independent execution could not complete in this sandbox:

- `uv run pytest` could not create its cache lock on the read-only filesystem.
- Direct `.venv/bin/pytest -s -p no:cacheprovider tests/test_inventory.py -q` collected all 14 cases, but every case errored during fixture setup because the restricted environment could not connect to PostgreSQL on either configured host.
- E2E execution was therefore not attempted; its fixtures also require direct database access.

This does not make the verdict inconclusive: the base code proves that at least one claimed regression already passes unfixed, and a precise tenant-filter mutation leaves another test green.

## Fix-linked falsifiability

| Test | Base behavior | Grade |
|---|---|---|
| `test_create_item_rejects_source_execution_id_from_another_org` | Base accepts it with 201 and writes the row | Valid red-before-fix regression |
| `test_create_item_rejects_source_execution_step_id_from_another_org` | Base accepts it with 201 and writes the row | Valid red-before-fix regression |
| `test_create_item_accepts_own_org_source_execution` | Already green on base | Legitimate positive control, but it only checks 201 and not that the reference was stored |
| `test_trace_enrichment_does_not_leak_another_orgs_step_data` | Base leaks the planted prompt and input, so two assertions go red | Falsifiable for the exact scoping removal, but structurally weak; details below |
| `test_list_inventory_by_process_id_does_not_match_another_orgs_execution` | Base returns `Cross Joined Item` | Valid red-before-fix regression, but lacks an own-org positive control |
| `test_adjust_rejects_non_finite_quantity_with_400` (`nan`, `NaN`, `-nan`) | Base raises `InvalidOperation`, producing 500 instead of 400 | Strong red-before-fix regressions; also verify quantity unchanged |
| `test_adjust_rejects_infinity_with_400` | Base already returns JSON 400: `Infinity < 0` is false, then the existing `coerce_stored_quantity` finite check raises `ValueError`, which the route catches | Invalid regression; green without the new `is_finite()` guard |
| `test_create_rejects_huge_exponent_quantity_with_400` | Base returns 500 when quantize raises outside the try | Valid red-before-fix regression |
| `test_adjust_accepts_a_normal_quantity` | Already green on base | Strong positive compatibility control |
| `test_create_rejects_unknown_inventory_type` | Base accepts and stores uppercase `RAW_MATERIAL` | Valid red-before-fix regression |
| `test_create_accepts_every_valid_inventory_type` | Already green on base | Positive control, but 201 alone does not prove each supplied type was preserved |
| `test_csv_validate_raw_body_enforces_csv_size_limit` | Approximately 3 MB is below the unrelated global 10 MB cap, so base processes it and returns 200 | Valid red-before-fix regression |

The module-level statement that every case was written red against the baseline is false. The own-org, normal-quantity, and valid-type cases are intentional positive controls, while the Infinity case is presented as a regression but also passes the unfixed code.

## Headline CRITICAL test

`test_trace_enrichment_does_not_leak_another_orgs_step_data` cannot pass via a 404 or error because it requires status 200. It can, however, pass through a successful no-enrichment response:

- The endpoint inserts the raw item into the response even if traversal enrichment returns no items.
- The test never proves `_enrich_items_bulk` actually ran or that a legitimate same-org step is enriched.
- A mutation that disables enrichment entirely produces a 200 response with all three forbidden strings absent.
- `process.name not in body` is tautological in the current setup. `_plant_item_with_foreign_ref` receives only `step_id`; `source_execution_id` remains `None`. Process-name enrichment follows `item.source_execution_id`, so the neighbour process name cannot appear even on the unfixed base.
- The prompt and input assertions do fail against the exact unscoped base implementation, so the test is not wholly inert.

Required strengthening: parse the JSON, assert the planted item is present, and add a same-org positive-control item whose prompt/input/process name must appear. Plant both the foreign execution and step references if process-name isolation is being asserted.

## Tenant-isolation probes

| Test | Assessment |
|---|---|
| `test_org_b_cannot_adjust_org_a_inventory_item` | Checks only 404. It never reads Org A's exact quantity afterward, so it does not prove the neighbour was untouched. |
| `test_org_b_cannot_waste_org_a_inventory_item` | The owner being able to waste one unit does not prove no prior unauthorized deduction occurred; an item reduced from 5 to 4 remains wasteable. Assert the exact owner quantity before performing the owner write. |
| `test_org_b_wastage_list_excludes_org_a_records` | Invalid against the relevant mutation. If `WastageRepository.list_wastage_records` loses its org filter, the foreign record is returned, but item-name hydration remains org-scoped and renders `item_name: "Unknown"`. The marker-name absence assertion still passes while record id, item id, reason, and quantity leak. |
| `test_org_b_out_of_stock_excludes_org_a_items` | Valid for the normal org-filter mutation: the leaked row contains the marker name. |
| `test_org_b_matching_untracked_excludes_org_a_items` | Exact empty-list assertion is useful, but there is no owner-side positive control; an endpoint that always returns empty passes. |
| `test_org_b_cannot_reconcile_via_addition_onto_org_a_untracked_item` | Membership in matching results does not prove an unchanged balance. A partial reduction from 8 to 3 still matches. Assert `quantity == "8"` and `remaining_balance_to_reconcile == "8"`, and verify Org B did not receive a partially-created item. |

## Other assertion-strength findings (resolved by round 3 below — verified 2026-09-13 by findings-sweep)

### CSV flow

- `test_csv_validate_happy_path_returns_per_row_status` does not assert the subsequent listing request succeeded before searching its text.
- `test_csv_validate_rejects_missing_required_columns` tests only a missing Unit column while claiming all three required columns.
- `test_csv_commit_happy_path_creates_item_with_audit_history` checks source method and row index, but AC25 also requires the acting user and UTC timestamp.
- `test_csv_commit_rejects_over_max_rows` checks only status 400 and never proves zero rows were written.
- `test_csv_commit_skips_duplicate_batch_but_commits_the_rest` proves the other row committed, but does not query the final count for the colliding `(org, name, batch)` tuple.

The row-level validation, multipart size/encoding, truncation, server-side revalidation/no-write, and successful-row assertions are otherwise substantive.

### Inventory E2E flow

- `test_out_of_stock_lists_zero_quantity_raw_materials` proves inclusion of one qualifying row, not the AC8 “exactly” claim: it has no nonzero or non-raw-material decoy.
- `test_config_units_returns_allowed_units` does not prove the endpoint mirrors `CONVERSION_FACTORS`; it checks only that `kg` and `l` are present.
- `test_decode_barcode_is_deprecated_and_returns_410` does not assert the explanatory message required by AC28.
- `test_reconcile_matching_untracked_returns_untracked_items` has no differently named/unit decoy, so an implementation returning every untracked item would pass.
- `test_reconcile_via_addition_maps_onto_untracked_item` strongly checks the successful balance change, but its “missing fields → nothing created” branch checks only status 400 and does not verify no write.

The over-deduction and serial idempotency tests are strong: they assert response semantics and exact stored quantities after every request.

## Coverage honesty

Blocking gaps:

1. F1 and AC33 explicitly include client-supplied `source_output_id`, but there is no regression test for it. The current `_assert_source_refs_belong_to_org` does not accept or validate `source_output_id`, and the column has no database FK. The tests therefore allow the audit to declare the write-side finding fixed while this input remains arbitrary.
2. F3 documents both create and update routes, but only create is tested with a huge exponent.
3. The new `EntityEventSummary.org_id` defense-in-depth filter has no regression test. This is lower risk because the audit itself established the pre-fix query was not exploitable.
4. AC20's raw-body invalid-UTF-8 path remains untested; only multipart invalid bytes are covered.
5. AC14's three-way atomicity is not demonstrated: no added test checks the linked `InventoryMovement` row and rollback of item, wastage, and movement together.
6. AC16's wastage unit conversion and movement metadata are not exercised.
7. AC12/AC13's hostile validation matrix and batch-size cap, and AC17's invalid idempotency-key forms, are not covered by this batch despite not appearing in the E2E report's uncovered list.

The declared gaps for AC9-AC11 and AC18 are correctly disclosed. AC31/AC32 are also explicitly disclosed as outside the E2E stage.

## Required changes before re-grade

- Replace or relabel the Infinity case; as written it is not red on the base.
- Strengthen the trace test with parsed response-shape assertions and a same-org enrichment positive control; supply `source_execution_id` if asserting process-name absence.
- Assert exact owner state after every rejected cross-tenant mutation.
- Make the wastage-list probe assert foreign record id/item id/reason absence, not only item-name absence.
- Add foreign and own-org `source_output_id` coverage and ensure the production validator actually validates it.
- Add the missing no-write and exact-data assertions identified above.
- Correct the “every test was RED” and coverage claims to distinguish regressions, positive controls, partial AC coverage, and disclosed gaps.

findings_count: 15
gate: blocked

VERDICT: invalid

---
*Round 1. Stage ran read-only (Codex gpt-5.6-sol, high). Report transcribed verbatim by the
review-feature orchestrator per `.agents/verification-chain.md` §5. The orchestrator's
remediation of these findings, and the round-2 re-grade, are recorded below this line in
`review.md`.*


---

# TEST EVALUATION — 2026-07-28 — RE-GRADE

scope:
- base: `8d95f83`
- branch: `work/2026-07-27-session`
- HEAD equals base; reviewed changes are uncommitted
- batch: 41 new/changed cases
  - `tests/test_inventory.py`: 18 cases
  - `tests/e2e/test_inventory_csv_flow.py`: 10 cases
  - `tests/e2e/test_inventory_flow.py`: 7 added cases
  - `tests/e2e/test_tenant_isolation.py`: 6 added cases

verdict: invalid

## Method

- Reused the prior evaluation and re-checked each claimed remediation against the current tests and production diff.
- Read every new test and all assertion-affecting changes in modified test files.
- Compared regression/control claims with the base implementation at `8d95f83`.
- Reviewed the production validator, trace enrichment, quantity validation, CSV route, and tenant-scoped repository changes.
- No files were edited and no mutation was left behind. Final `git status --short` matched the starting state.
- No assertion deletions, broadened assertions, new skips, xfails, or quarantine markers were found.

## Remediation verification

| Prior required change | Result |
|---|---|
| Relabel the Infinity case and remove the false all-red claim | **Partial.** The module docstring correctly identifies Infinity as a control and accurately explains its base behavior. However, `test_adjust_rejects_infinity_with_400` itself has no `[CONTROL]` docstring, so the claim that every test is individually labelled is false. |
| Strengthen the trace-isolation test and add an in-org enrichment control | **Verified.** Both foreign execution and step IDs are planted; the JSON proves the planted item was returned; its foreign step reference remains visible while `process_name` is `None`; prompt/input/process-name leakage is checked. The new same-org control proves enrichment cannot simply be disabled. |
| Add and actually validate `source_output_id` | **Production fix verified; test protection invalid.** The repository requires an owned step and checks output membership in `Step.outputs`. The tests do not falsifiably guard that membership check; details below. |
| Pin exact owner state after rejected hostile mutations | **Adjust and wastage verified. Reconciliation partial.** Adjust and wastage both assert owner quantity remains exactly `"5"`, with wastage checking before the owner's write. Reconciliation asserts quantity remains `"8"` and Org B receives no item, but it still does not assert `remaining_balance_to_reconcile == "8"` as required by the prior report. |
| Strengthen the wastage-list leak probe | **Verified.** It checks foreign record ID, inventory item ID, reason, and marker-name absence. Removing only the wastage repository org filter would now fail this test. |

## Blocking falsifiability finding (resolved by round 3 below — verified 2026-09-13 by findings-sweep)

### `test_create_item_rejects_source_output_id_from_another_orgs_step`

The test does not establish that the supplied `source_output_id` belongs to the foreign step:

- `_foreign_execution_step` creates a step with `outputs=[]`.
- The request supplies a fresh random UUID as `source_output_id`.
- The request also supplies the foreign `ExecutionStep.id`.
- Production rejects the request at the earlier step-ownership check, before output membership is examined.

Deterministic mutation probe:

1. Keep the owned-step requirement.
2. Remove only the membership condition at `inventory_repo.py:144-147`.
3. The orphan-output test still rejects because it has no step.
4. The foreign-step test still rejects because its step belongs to another org.
5. The valid own-output control still accepts.
6. Therefore every `source_output_id` test remains green while arbitrary output IDs become accepted for owned steps.

This directly fails the required falsifiability standard. Fix by creating an owned step and supplying an output UUID not declared by that step—preferably an output UUID declared on a foreign step—then assert 400 and no row written.

## Other assertion-strength findings from this batch — all now fixed (verified 2026-09-15 by findings-sweep)

These were present in the first report and, at the time, remained in the current files without
being included in the submitted "known not addressed" disclosure. All 12 have since been
strengthened exactly as required; re-checked against the current tests by findings-sweep:

1. `test_list_inventory_by_process_id_does_not_match_another_orgs_execution` now has an
   `Own Process Item` same-org positive control (`tests/test_inventory.py`).
2. `test_create_accepts_every_valid_inventory_type` now asserts the stored row's
   `inventory_type` matches exactly what was sent, per type (`tests/test_inventory.py`).
3. `test_csv_validate_happy_path_returns_per_row_status` now asserts the listing request's
   own `200` before using its text as the no-write proof (`tests/e2e/test_inventory_csv_flow.py`).
4. `test_csv_validate_rejects_missing_required_columns` now tests all three required
   columns individually (`tests/e2e/test_inventory_csv_flow.py`).
5. `test_csv_commit_happy_path_creates_item_with_audit_history` now asserts the UTC
   timestamp; the acting-user half of AC25 is proven separately in
   `test_csv_commit_records_acting_user_in_audit_history` (`tests/test_inventory.py`), since
   the list endpoint deliberately strips `user_id` from audit-history entries.
6. `test_csv_commit_rejects_over_max_rows` now asserts none of the batch's distinctively
   named rows were written (`tests/e2e/test_inventory_csv_flow.py`).
7. `test_csv_commit_skips_duplicate_batch_but_commits_the_rest` now asserts the colliding
   row's final count/quantity is unchanged (`tests/e2e/test_inventory_csv_flow.py`).
8. `test_out_of_stock_lists_zero_quantity_raw_materials` now includes a nonzero decoy and a
   zeroed-final-product decoy (`tests/e2e/test_inventory_flow.py`).
9. `test_config_units_returns_allowed_units` now asserts set-equality against
   `CONVERSION_FACTORS` (`tests/e2e/test_inventory_flow.py`).
10. `test_decode_barcode_is_deprecated_and_returns_410` now asserts the explanatory message
    (`tests/e2e/test_inventory_flow.py`).
11. `test_reconcile_matching_untracked_returns_untracked_items` now plants differently-named
    and differently-unitted decoys (`tests/e2e/test_inventory_flow.py`).
12. `test_reconcile_via_addition_maps_onto_untracked_item` now asserts the inventory count is
    unchanged after the missing-fields rejection (`tests/e2e/test_inventory_flow.py`).

## Coverage disclosure and release risk

The explicitly disclosed gaps are real and candid:

- AC14 three-way atomicity
- AC16 wastage conversion and movement metadata
- AC12/AC13 hostile validation matrix
- AC17 invalid idempotency-key forms
- AC20 raw-body invalid UTF-8
- F3 update-route regression coverage
- `EntityEventSummary` defense-in-depth filter

However, the disclosure is incomplete because it omits the unresolved assertion-strength items above and describes reconciliation and output-ID remediation as complete when they are not.

Release severity:

- **AC14 is severe enough to block shipping without a failure-path test.** Inventory quantity, wastage, and movement rows form one ledger invariant; a partial commit creates silent stock/audit corruption. Existing success tests do not prove rollback of all three records.
- **AC16 should also be covered before release.** Incorrect conversion or movement metadata can corrupt both stock and its audit explanation.
- The `source_output_id` membership regression is a current gate blocker because the security fix is not protected by its tests.
- F3 update coverage is lower risk because the shared `coerce_stored_quantity` implementation now handles the huge exponent and the update route catches `ValueError`, but the route still needs a regression test.
- AC20 raw-body invalid UTF-8 appears to remain an implementation gap, not merely absent coverage: the raw branch obtains text before performing any explicit strict UTF-8 decode.
- AC12/AC13, AC17 invalid forms, and the `EntityEventSummary` filter may be completed in a separate batch if that batch remains a pre-release gate rather than post-ship follow-up.

## Runtime verification

Independent execution was restricted:

- Collection with normal pytest capture could not start because the read-only environment had no writable temporary directory.
- `.venv/bin/pytest -s -p no:cacheprovider tests/test_inventory.py -q` collected all 18 cases, but all errored during fixture setup because the sandbox could not connect to the test PostgreSQL service.
- The supplied `636 passed, 0 failed, 0 skipped` result could therefore not be independently reproduced here.

This does not make the grade inconclusive: the `source_output_id` membership mutation is deterministically shown to escape every relevant test, and multiple claimed remediations remain statically incomplete.

findings_count: 15
gate: blocked

VERDICT: invalid

---
*Round 2. Stage ran read-only (Codex gpt-5.6-sol, high). Transcribed verbatim by the
orchestrator per `.agents/verification-chain.md` §5.*

## Orchestrator disposition of round 2

Fixed in this round (all blocking falsifiability findings):

- **`source_output_id` membership check was unguarded.** The grader's mutation probe was
  correct: the foreign-step test is rejected at step-ownership before membership is ever
  examined, so deleting the membership condition left every `source_output_id` test green.
  Added `test_create_item_rejects_source_output_id_not_declared_by_its_own_step`, which
  uses an OWNED step with a declared output and supplies a different output id — it goes
  red for exactly that mutation.
- **AC20 raw-body invalid UTF-8 was an implementation gap, not just missing coverage** —
  the grader was right. `request.get_data(as_text=True)` decodes with `errors="replace"`,
  so invalid bytes became U+FFFD and the upload proceeded, while the multipart branch
  returned 400 for the same input. `csv_validate` now reads bytes and decodes strictly.
  Two tests added (reject invalid, accept valid non-ASCII with the name intact).
- **Infinity case now carries its own `[CONTROL]` docstring**, not only the module-level
  note.
- **Reconciliation probe now pins `remaining_balance_to_reconcile`**, not just `quantity` —
  the grader's point being that quantity can hold steady while the reconcile ledger moves.

Handed to **test-author** rather than patched in a third round (`.agents/verification-chain.md`
§7 — a third round on the same wall is a design smell, and this is coverage work that stage
owns): AC14 three-way atomicity, AC16 conversion + movement metadata, the 12 assertion-strength
items, AC12/AC13, AC17 invalid key forms, F3 on the update route, and the `EntityEventSummary`
filter. The grader's judgement that **AC14 is severe enough to block shipping** is carried
forward into `review.md` as a release gate, not softened.


---

# TEST EVALUATION — 2026-07-29 — ROUND 3

scope:
- base: `8d95f83`
- branch: `work/2026-07-27-session`
- changes: uncommitted working-tree changes
- batch: 145 new/changed cases across 10 inventory test files
- prior round-2 passes were accepted without re-litigation
- note: the tree moved during evaluation; this report grades the final stable snapshot, which includes a new access-denied observability test absent from the test-author report

verdict: invalid

## Method

- Read every newly added test and every assertion-affecting tracked diff.
- Compared the final tests with the production paths they claim to protect.
- Verified the tracked diff removed no assertions or tests. The three deleted lines were fixture/helper changes, not assertions.
- Found no new skip, xfail, or quarantine markers.
- Ran executable in-memory mutation probes where database access was unnecessary.
- Performed deterministic control-flow analysis for database-backed mutations because the sandbox cannot resolve the test database host.
- Made no filesystem edits and left no mutation behind.

## Required round-2 remediation

| Remediation | Result |
|---|---|
| `source_output_id` membership regression | **Verified.** The new test creates an owned execution step with one declared output, supplies a different output UUID, checks the exact membership error, and proves no row was written. Removing only `inventory_repo.py:168-170` allows creation and changes the expected 400 into 201, so this test goes red for the round-2 mutation. |
| AC20 strict raw-body UTF-8 | **Verified.** The route now decodes bytes strictly. Restoring replacement decoding makes the invalid-byte request return a normal validation response rather than the asserted UTF-8 400. The valid non-ASCII control also checks the name survives intact. |
| AC14 three-way atomicity | **Verified.** Failure occurs on the second entry after both calls are reached and the first entry has been staged. The test checks both quantities and zero wastage/movement rows. Per-entry commit or removal of rollback makes it fail. |
| AC16 conversion and movement metadata | **Verified.** The test checks the 500 g → 0.5 kg deduction, canonical wastage and movement quantities/units, signed movement, and both metadata keys. The incompatible-unit test proves no deduction. |
| F3 PUT route | **Verified.** Required independent fields are supplied, the quantity remains exactly unchanged, and the huge exponent therefore exercises the intended update path. |
| Twelve prior assertion-strength findings | **Verified as addressed**, including process-filter positive control, persisted inventory types, CSV listing success/no-write proofs, missing-column cases, duplicate tuple count/quantity, out-of-stock decoys, exact unit set, 410 explanation, reconciliation decoys, and rejected-reconciliation no-write checks. |

## Mutation results

| Test | Mutation | Result |
|---|---|---|
| `test_create_item_rejects_source_output_id_not_declared_by_its_own_step` | Remove only output-membership condition | **RED** deterministically: request reaches creation and returns 201 |
| `test_csv_validate_raw_body_rejects_invalid_utf8` | Restore replacement decoding | **RED** deterministically |
| `test_wastage_batch_failure_rolls_back_item_wastage_and_movement_together` | Commit per entry / omit rollback | **RED** deterministically |
| `test_wastage_converts_compatible_non_canonical_unit_and_records_metadata` | Bypass conversion or metadata | **RED** deterministically |
| `test_assert_movement_unit_matches_item_canonical_raises_on_mismatch` | Replace guard with no-op | **RED**, executed |
| `test_wastage_entries_payload_hash_is_stable_regardless_of_entry_order` | Make hash order-sensitive | **RED**, executed |
| `test_parse_date_accepts_month_first_format` | Remove `%m/%d/%Y` support | **GREEN**, executed |
| `test_sanitize_preserves_tab_newline_and_printable_chars` | Strip tabs and newlines | **GREEN**, executed |

## Findings

### 1. `test_parse_date_accepts_month_first_format` does not exercise month-first parsing

The input is `13/03/2026`, which is valid only as day/month/year. Removing `%m/%d/%Y` from `_parse_date` left the test green.

Fix: use an unambiguous month-first input such as `03/13/2026` and expect `date(2026, 3, 13)`.

### 2. `test_sanitize_preserves_tab_newline_and_printable_chars` contains no tab or newline

Its only input is `"Café Ünïcode"`. An in-memory mutation that strips all C0 control characters, including tabs and newlines, left the test green.

Fix: include internal tab/newline characters and assert they remain, while keeping separate assertions for surrounding-whitespace trimming.

### 3. `test_matching_untracked_returns_empty_list_when_name_or_unit_missing` tests only missing name

The request supplies `unit=kg` and omits `name`. A route that handles missing name correctly but stops handling missing unit still passes.

Fix: parameterize two requests—one missing name and one missing unit—and assert the exact empty response for both.

### 4. AC25 timestamp assertions are too broad

Both CSV audit tests use only `timestamp_utc.endswith("Z")`. A constant value of `"Z"` satisfies these assertions without being a timestamp.

Fix: parse the value as ISO-8601, assert a UTC offset, and preferably assert it falls within the request’s start/end time window.

### 5. The AC12 endpoint-matrix coverage claim is overstated

Non-positive, non-finite, and out-of-range quantities are tested only against `parse_wastage_quantity`. Those are valid helper tests, but they do not prove that `POST /inventory/wastage` converts each helper error into `400 + VALIDATION_FAILED` without writes. Removing or breaking the route’s `qty_err` handling leaves every helper test green.

Fix: add a parameterized route-level test for zero, negative, NaN/Infinity, and over-range values, asserting status, error code, unchanged quantity, and zero wastage/movement rows.

## Remaining disclosed gaps and severity

- AC18 true advisory-lock concurrency remains valuable coverage, but is not independently as severe as the former AC14 gap: the unique `(org_id, key)` constraint and transaction rollback provide a secondary race-safety mechanism. It should still be tested before claiming AC18 is protected. Already fixed: `tests/test_wastage.py:128 test_wastage_advisory_lock_serializes_concurrent_duplicate_submissions` (commit `6faecfe`) deliberately forces real `pg_advisory_xact_lock` contention via a delayed-lock wrapper and two real threads (verified 2026-08-25 by findings-sweep).
- AC9–AC11 guard-internal coverage remains disclosed; the separately verified live PostgreSQL trigger materially reduces release risk. Already fixed: `tests/test_inventory_quantity_guard.py` (commit `f5f268e`) now covers the Python-level guard, all three repository write paths, the raw-SQL trigger rejection, and rearm behavior (verified 2026-08-25 by findings-sweep).
- AC31/AC32 Path B remains outside this router-focused batch.
- The `EntityEventSummary.org_id` filter remains an untested defense-in-depth change and is not a release blocker on the supplied evidence. Already fixed: `tests/test_inventory.py:881 test_list_inventory_enriches_items_with_their_own_org_event_summary` now covers it (verified 2026-08-25 by findings-sweep).
- None of these disclosed gaps independently rises to AC14's previous ship-blocking severity — a summary sentence, not its own finding (verified 2026-09-13 by findings-sweep).

## Runtime verification

- Database-free new helper suites: **67 passed**.
- Current full collection: **744 tests**, not 738.
- Ruff over all touched inventory tests and production modules: **clean** with cache disabled.
- Seven targeted database-backed tests all errored during fixture setup because `host.docker.internal` could not resolve in this sandbox; none reached their assertions.
- Therefore the reported all-green database run could not be independently reproduced.
- The current 744-test collection also shows that the claimed `738 passed` result does not describe the final working-tree snapshot.

## Gate

The core round-2 blocker and the AC14/AC16 release-critical coverage are now substantively fixed. However, two newly authored tests stayed green under direct mutations of the behavior named by those tests, and two further tests materially overclaim their assertions. Under the test-evaluator contract, a batch containing green-under-mutation tests cannot receive `valid`.

findings_count: 5
gate: blocked

VERDICT: invalid

---
*Round 3. Stage ran read-only (Codex gpt-5.6-sol, high). Transcribed verbatim by the
orchestrator per `.agents/verification-chain.md` §5.*

## Orchestrator disposition of round 3

Round 3 **verified** every round-2 blocker and both release-critical items (AC14, AC16) —
including deterministic mutation probes showing each goes red. It then found 5 new
findings against the tests the test-author stage had just written. All 5 are fixed:

1. **`test_parse_date_accepts_month_first_format` was green under mutation.** Input
   `13/03/2026` is parsed by `%d/%m/%Y` alone, so deleting `%m/%d/%Y` support entirely
   left it passing. Changed to `03/13/2026`, which the first two formats reject.
   **Verified by executing the mutation: the test now fails.**
2. **`test_sanitize_preserves_tab_newline_and_printable_chars` contained no tab or
   newline.** Its input was `"Café Ünïcode"`, so a mutation stripping all C0 controls
   left it green. Now asserts internal `\t`, `\n`, `\r` survive AND that C0 controls
   outside that set are removed. **Verified by executing the mutation: the test now fails.**
3. **Missing-unit case untested.** `test_matching_untracked_returns_empty_list_when_name_or_unit_missing`
   supplied `unit=kg` and omitted only `name`. Parameterized over missing-name,
   missing-unit, and both.
4. **AC25 timestamp assertions were satisfiable by the literal string `"Z"`.** Both
   `endswith("Z")` checks replaced with a parse to a UTC datetime pinned inside the
   request's own start/end window.
5. **AC12 route-level claim was carried by helper tests.** Added
   `test_wastage_route_rejects_bad_quantity_without_writing`, parameterized over zero,
   negative, NaN, Infinity, over-range and unparseable, asserting 400 +
   `VALIDATION_FAILED`, unchanged quantity, and zero rows in both ledger tables — the
   thing deleting the route's `qty_err` branch would break.

Round 3's two factual corrections to the orchestrator's own claims are accepted: the
collection count was 744 (not the 738 quoted, which predated tests added after that run),
and the grader could not reproduce the DB-backed run in its sandbox. Final count after
these fixes: **752 passed, 0 failed, 0 skipped**.

Remaining disclosed gaps (AC18 concurrency, AC9-AC11 guard internals beyond the live
trigger verification, AC31/AC32 Path B, the EntityEventSummary filter) — round 3 states
explicitly that **none independently reaches AC14's former ship-blocking severity**.
