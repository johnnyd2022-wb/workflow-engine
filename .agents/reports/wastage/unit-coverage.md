# UNIT COVERAGE: wastage
date: 2026-08-11

## Before
```
pytest tests/test_wastage.py --cov=app.core.utils.inventory_wastage_quantity \
  --cov=app.core.db.repositories.wastage_repo --cov=app.core.db.models.inventory_wastage
inventory_wastage.py           100%
wastage_repo.py                 96%  (missing: 88 — the inventory_item_id filter branch)
inventory_wastage_quantity.py   89%  (missing: 21, 29, 52, 55-56, 75)
TOTAL                            93%
```
`backend.py`'s wastage functions (record_wastage/list_wastage, lines 3046-3453) can't be
measured as a file-level percentage — the file is 2987 statements covering dozens of
unrelated routes — so gaps were found by diffing `--cov-report=term-missing`'s line list
against that range: `3055, 3100, 3176-3177, 3253-3254, 3264-3266, 3359-3373, 3423-3439`.

## Gaps closed (4 new tests, tests/test_wastage.py)
| gap (backend.py line) | AC | test added |
|---|---|---|
| 3253-3254 (`current_qty <= 0`) | AC15 | `test_wastage_rejects_wasting_from_zero_quantity_item` |
| 3176-3177 (non-string `quantity_unit`) | AC16 | `test_wastage_rejects_non_string_quantity_unit` |
| 3423-3426 (`list_wastage` malformed `inventory_item_id`) | AC19 | `test_list_wastage_rejects_malformed_inventory_item_id` |
| 3431-3435 (`list_wastage` item-id filter + name resolution) | AC19 | `test_list_wastage_filters_by_inventory_item_id` |

Side effect: closing the AC19 filter gap also closed `wastage_repo.py`'s only miss
(line 88, the `if inventory_item_id:` filter branch in `list_wastage_records`) — it went
96% → 100%, and `inventory_wastage_quantity.py`'s line 29
(`quantity_unit must be a string`) 89% → 91% via the same route-level test.

## After
```
inventory_wastage.py           100%
wastage_repo.py                100%
inventory_wastage_quantity.py   91%  (missing: 21, 52, 55-56, 75)
TOTAL                            95%
```
`tests/test_wastage.py`: 25 → **29 passed**, all green, 3 runs stable.

## Disclosed gaps, not closed (diminishing returns, noted rather than chased)
- `backend.py:3055` — the non-PostgreSQL no-op branch of
  `_pg_advisory_lock_wastage_idempotency`. Prod is always PostgreSQL; testing this branch
  means mocking the dialect name, which tests nothing about wastage's actual behavior.
- `backend.py:3264-3266` — `convert_to_inventory_unit_decimal` raising `ValueError` after
  `are_units_compatible` already returned true. Only reachable if the two functions
  disagree about compatibility, which would be a bug in `unit_conversion.py` itself, not
  wastage — out of this slice's scope per the spec's Out of scope section.
- `backend.py:3359-3373` — the `IntegrityError` commit-conflict retry path. Needs a
  genuine unique-constraint race (two commits landing on the same `(org_id, key)` after
  both passed the pre-check), which `test_wastage_advisory_lock_serializes_concurrent_duplicate_submissions`
  already proves the advisory lock prevents in practice — this is the defense-in-depth
  fallback for the case the lock somehow didn't serialize, structurally hard to trigger
  without disabling the lock deliberately.
- `inventory_wastage_quantity.py:21` (`quantize_wastage_quantity`) — grep shows no
  caller in `app/` outside its own module; either dead code or reserved for a future
  caller. Not a wastage-route gap either way.
- `inventory_wastage_quantity.py:52,55-56,75` — signed-zero (`"-0"`) and
  precision-overflow-on-quantize edge cases in `parse_wastage_quantity`, and one line in
  `wastage_entries_payload_hash`. Narrower than the `nan`/`Infinity`/`1e19` cases already
  covered by `test_wastage_route_rejects_bad_quantity_without_writing`; left as disclosed
  gaps rather than manufactured tests for inputs no real client sends.

VERDICT: patched
