# E2E Playwright — inventory (gap-fill)

Scope: `.agents/specs/inventory.md`, review-feature (not new-feature). Dev server was
confirmed listening on `:5000`/`:8005` and the test DB on `:8401` before running — every
test below executed for real, none skipped.

## Step 1: existing suite, run for real

| Suite | Result |
|---|---|
| `tests/e2e/test_inventory_flow.py` (pre-existing 6) | 6 passed |
| `tests/e2e/test_tenant_isolation.py` (inventory-relevant: update/delete/list) | 3 passed |

No skips, no server-down false negatives. `test_tenant_isolation.py` also has 2 non-inventory
tests (barcode read, dashboard summary) which were left alone.

## Step 2: gap-fill — new coverage

Confirmed via `scripts/e2e_coverage.py --check` before and after: all six named endpoints
(csv-validate, csv-commit, out-of-stock, config/units, decode-barcode,
reconcile/matching-untracked, reconcile/via-addition) were gaps beforehand and are now
covered. Remaining inventory gaps (`trace`, `trace-backward`, `expired-materials`,
`output-expiry`, `output-ready-date`, `untracked-items`, `reconcile/via-execution`) are
out of scope per the spec (lineage tracing is audited separately; Path B / untracked-items
listing were not in this stage's target list).

### (a) Cross-tenant probe (AC33) — added to `tests/e2e/test_tenant_isolation.py`

| Test | Route | Asserted failure mode |
|---|---|---|
| `test_org_b_cannot_adjust_org_a_inventory_item` | `POST /inventory/<id>/adjust` | 404 |
| `test_org_b_cannot_waste_org_a_inventory_item` | `POST /inventory/wastage` | 400, "not found or access denied"; owner still able to waste afterward (proves untouched) |
| `test_org_b_wastage_list_excludes_org_a_records` | `GET /inventory/wastage` | org A's record/name absent |
| `test_org_b_out_of_stock_excludes_org_a_items` | `GET /inventory/out-of-stock` | org A's zeroed item absent |
| `test_org_b_matching_untracked_excludes_org_a_items` | `GET /inventory/reconcile/matching-untracked` | empty result |
| `test_org_b_cannot_reconcile_via_addition_onto_org_a_untracked_item` | `POST /inventory/reconcile/via-addition` | 400 "not found"; org A's untracked balance provably unchanged |

Combined with the 3 pre-existing probes (update/delete/list) and 2 more (barcode, dashboard
summary), the inventory surface now has 9 cross-tenant probes, all asserting 404/400 — never
a distinguishable 403, matching AC33's contract as implemented (`backend.py` returns 404 for
every cross-org lookup; reconciliation returns 400 "not found" via its service layer).

### (b) CSV upload — new file `tests/e2e/test_inventory_csv_flow.py` (10 tests)

| AC | Test |
|---|---|
| AC20/21 | `test_csv_validate_happy_path_returns_per_row_status`, `test_csv_validate_row_level_errors` (blank name, non-numeric qty, zero qty, disallowed unit — each with its exact message) |
| AC20 | `test_csv_validate_rejects_missing_required_columns`, `test_csv_validate_rejects_oversized_file` (>2MB via multipart), `test_csv_validate_rejects_non_utf8_file` (invalid UTF-8 byte via multipart) |
| AC22 | `test_csv_validate_truncates_over_max_rows` (501 rows → `truncated: true`, 500 validated), `test_csv_commit_rejects_over_max_rows` (501-row commit → 400, unlike validate) |
| AC23 | `test_csv_commit_happy_path_creates_item_with_audit_history` (+ AC25: `inventory_audit_history` entry with `source_method: csv_upload`, row index), `test_csv_commit_revalidates_server_side_and_writes_nothing_on_failure` — sends a row the client never validated (negative quantity) alongside a good one; commit rejects with 400 and the good row is **not** written either, proving server-side re-validation is real and all-or-nothing on failure |
| AC24 | `test_csv_commit_skips_duplicate_batch_but_commits_the_rest` — pre-creates an (org, name, batch) collision, commits two rows: the colliding one is skipped with a per-row error, the other commits, response explains "skipped" |

Note: the 2MB and non-UTF-8 checks only apply to the multipart `file` upload path
(`inventory_upload_routes.py`'s `if file:` branch) — the raw-text-body path has no size/
encoding check, so those two tests specifically exercise multipart uploads.

### (c) Wastage over-deduction and idempotency — added to `tests/e2e/test_inventory_flow.py`

- `test_wastage_rejects_over_deduction` (AC15): wasting 10 from an item with 5 on hand → 400
  `VALIDATION_FAILED`, error names the 5-on-hand quantity, item quantity unchanged.
- `test_wastage_idempotent_replay_does_not_double_deduct` (AC17): same key+payload replayed
  → `idempotent_replay: true`, quantity deducted exactly once (20→15, not 20→10); same key
  with a different payload → 409 `IDEMPOTENCY_PAYLOAD_MISMATCH`, still no further deduction.
  Already done: present at `tests/e2e/test_inventory_flow.py:350` (verified 2026-08-25 by
  findings-sweep).

### (d) Remaining endpoints — shape checks in `tests/e2e/test_inventory_flow.py`

- `test_out_of_stock_lists_zero_quantity_raw_materials` (AC8)
- `test_config_units_returns_allowed_units` (AC27)
- `test_decode_barcode_is_deprecated_and_returns_410` (AC28)
- `test_reconcile_matching_untracked_returns_untracked_items` (AC29, incl. the
  both-params-required empty-result case)
- `test_reconcile_via_addition_maps_onto_untracked_item` (AC30, incl. missing-fields and
  malformed-UUID unhappy paths)

## Flake check

Ran `test_inventory_flow.py` + `test_inventory_csv_flow.py` + `test_tenant_isolation.py`
together 3/3 clean (34 tests each run, 0 flakes). Full `tests/e2e/` suite: 115 passed, 0
skipped, 0 failed — no regressions elsewhere.

## Gotcha worth recording

`_create_item`'s existing helper in `test_inventory_flow.py` passes
`inventory_type: "RAW_MATERIAL"` (uppercase). The column is a plain unconstrained
`String(50)` — nothing normalizes it — so it's stored literally uppercase. That's invisible
everywhere else because no other route does an *exact* string match on it, but
`out-of-stock` does (`InventoryItem.inventory_type == InventoryType.RAW_MATERIAL.value`,
i.e. lowercase `"raw_material"`). Both new out-of-stock tests (the direct one and the
cross-tenant one) create their item with the correct lowercase value explicitly rather than
reusing the existing helper as-is, with a comment explaining why — did not touch the
existing helper's default since every other passing test relies on its current behavior
and this is out of scope for a gap-fill pass.

## ACs with no E2E coverage (by design)

- AC9-AC11 (quantity guard internals — DB trigger, before_flush hook): unit/integration
  territory, not browser-observable behavior.
- AC18 (concurrent duplicate wastage submissions via advisory lock): needs true
  concurrency, not a serial Playwright test — belongs in a concurrency-focused
  integration test.
- AC26 (barcode lookup for a *known* code): already covered by the pre-existing
  `test_org_b_cannot_read_org_a_item_by_barcode`, which also proves the owner's-own-lookup
  path works.
- AC31/AC32 (Path B / reconcile via-execution): out of scope for this stage per the
  router's target list; `reconcile/via-execution` remains an open gap in
  `scripts/e2e_coverage.py`.

Suite handed to ci-gate as a required check (per skill §3) is out of scope for this stage —
not run here.
