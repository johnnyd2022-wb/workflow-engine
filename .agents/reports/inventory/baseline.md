# BASELINE: inventory
date: 2026-07-27
branch: work/2026-07-27-session (rebased onto review-feature @ 8d95f83, open MR !133)

## Working tree
`git status` clean at audit start.

## Suite
```
uv run pytest tests/ -q
569 passed, 30 skipped, 98 warnings in 247.70s
```

Green. The 30 skips are the `live_server` 2FA suites, expected per preflight
(`decisions.live_server_tests: skip` — no app server listening). No pre-existing
failures, so every finding this audit raises is attributable to the inventory surface,
not to inherited noise.

Note (not a finding against this feature): `CLAUDE.md` documents "Expect `252 passed, 30
skipped`". The real count is 569. Documentation drift for **docs-truth**, out of scope
here.

## Scope under audit
Routes:
- `app/core/backend/backend.py` — `list_inventory`, `create_inventory_item`,
  `update_inventory_item`, `adjust_inventory_item_quantity`, `delete_inventory_item`,
  `record_wastage`, `list_wastage`, `list_out_of_stock_raw_materials`
- `app/core/backend/inventory_upload_routes.py` — `barcode_lookup`, `get_allowed_units`,
  `csv_validate`, `csv_commit`, `decode_barcode`
- `app/core/backend/reconciliation_routes.py` — `get_matching_untracked_for_add`,
  `reconcile_via_addition_route`, `reconcile_via_execution_route`

Domain / data layer:
- `app/core/domain/inventory_quantity_guard.py`
- `app/core/db/repositories/inventory_repo.py`, `wastage_repo.py`
- `app/core/utils/inventory_quantity.py`, `inventory_wastage_quantity.py`,
  `unit_conversion.py`

Spec reconstructed at `.agents/specs/inventory.md` (`status: reconstructed`, 33 ACs).

## Existing test coverage (pre-audit)
| file | tests |
|---|---|
| tests/test_wastage.py | 4 |
| tests/test_unit_conversion.py | 11 |
| tests/test_inventory_quantity_guard.py | 6 |
| tests/test_reconciliation_routes.py | 1 |
| tests/test_multi_tenant_isolation.py | 7 (not all inventory) |
| tests/e2e/test_inventory_flow.py | 6 |

Endpoints referenced by any test: `/api/core/inventory` (list/create), `/wastage`,
`/<item_id>`, `/<item_id>/adjust`, `/barcode/`, `/reconcile/via-execution`.

**Endpoints with zero test references**: `/csv-validate`, `/csv-commit`,
`/out-of-stock`, `/config/units`, `/decode-barcode`, `/reconcile/matching-untracked`,
`/reconcile/via-addition`. These are the coverage gaps the chain must close.

## Orchestrator pre-findings (to be confirmed or falsified by the stages)
Raised from reading the code before launching stages; recorded here so the stages can
falsify them rather than inherit them as assumptions.

- **A — cross-tenant FK injection (tenant isolation).** `create_inventory_item`
  (backend.py:3591-3599) reads `source_execution_id`, `source_execution_step_id`,
  `source_output_id` straight from the request body and writes them to FK columns with
  no org-ownership check. `inventory_items.source_execution_id` FKs to `executions.id`
  globally (inventory_item.py:48-49) — nothing constrains the referenced row to the
  caller's org. Contradicts AC33.
- **B — `nan` reaches the DB layer as a 500.** `adjust_inventory_item_quantity`
  (backend.py:3807-3810) validates with `float(...)`, and `float("nan") <= 0` is False,
  so `"nan"` passes. `set_inventory_item_quantity` then evaluates `target < 0` on
  `Decimal("NaN")`, which raises `InvalidOperation` — not `ValueError`, so the route's
  handler misses it. Verified locally: `Decimal('NaN') < 0` raises. Contradicts AC5.
- **C — missing org filter on a join.** `list_inventory_items` (inventory_repo.py:334)
  outer-joins `Execution` with no `Execution.org_id == org_id` predicate, unlike
  `get_untracked_items` (inventory_repo.py:314-317) which has it. Defense-in-depth gap
  that Finding A makes reachable.
- **D — wrong entity in error path.** `create_inventory_item` logs
  `"Error creating process"` and returns `"Failed to create process"` (backend.py:3677-3678).
  Cosmetic, but it misdirects triage from the observability stack.
