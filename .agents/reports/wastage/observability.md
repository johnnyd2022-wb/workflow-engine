# OBSERVABILITY: wastage
date: 2026-08-11
mode: instrument

## Gap found
Neither of wastage's two cross-tenant rejection paths logged anything — the same class of
gap the inventory review fixed elsewhere ("the new rejections return an ordinary 400, so a
tenant-boundary probe left no trace at all"):

- `record_wastage`'s `inventory_repo.get_inventory_item_by_id_for_update` returning `None`
  (backend.py, now ~3248-3261) — a cross-org or nonexistent `inventory_item_id` both fall
  into the same silent `validation_errors.append(...)`.
- `inventory_dispose_confirm`'s equivalent branch (backend.py, now ~778-791) — same
  ambiguity, same silence.

`record_wastage`'s **success** path already logs `inventory_wastage_recorded` — only the
rejection path was blind.

## Fix
Added `logger.warning("access_denied", reason="inventory_item_not_found_or_cross_org",
feature="wastage", org_id=..., inventory_item_id=..., path=...)` at both sites, matching
the exact event name and field shape `inventory_repo.py`/`permissions.py`/
`_log_process_access_denied`/`_log_trace_access_denied` already use elsewhere in this
codebase — one `access_denied` query now covers wastage too. Deliberately logs the
**requesting** org_id, not the target item's org, and does not distinguish
"cross-org" from "genuinely nonexistent" in the response (AC15/AC-D3 both require that
ambiguity) — the log doesn't try to distinguish them either, same rationale
`_log_trace_access_denied`'s docstring gives.

## Regression tests (2 new, tests/test_wastage.py)
- `test_wastage_cross_org_rejection_emits_access_denied`
- `test_dispose_confirm_cross_org_item_emits_access_denied`

Both assert the requesting org's id appears in the log record (not the foreign org's), and
both were mutation-tested live: reverted the `logger.warning(...)` call in
`record_wastage`, reran `test_wastage_cross_org_rejection_emits_access_denied` (**failed**,
as expected), restored the code (`git diff` confirmed only the two intended access_denied
blocks remain), reran the full suite (**31/31 green**).

## Suite total
`tests/test_wastage.py`: 25 → 31 tests (4 unit-coverage + 2 observability), all green,
stable.

VERDICT: patched
