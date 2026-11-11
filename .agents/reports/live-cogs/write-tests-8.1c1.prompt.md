# Write the tests FIRST for live-cogs 8.1c-1 (recording purchases into stock)

You may edit files in /home/johnny/wt-live-cogs-alloc (branch feat/live-cogs-alloc, stacked on
8.1b). You cannot commit (sandbox can't write .git): leave your files in the working tree;
Claude reviews and commits. Do NOT monitor or wait on any MR pipeline. Don't touch other worktrees.
Claude is writing the implementation in parallel — do NOT write or edit anything under `app/`.

Contract: `.agents/specs/live-cogs.md`, section "## 8.1c-1 build contract — recording purchases
into stock", plus the ACs it names (AC5–AC9, AC11, AC12, AC30, AC34, AC35 earlier in the spec,
as adjusted there) and AC74–AC80. Read the 8.1a/8.1b code it builds on (`app/features/costing/`,
`app/features/crm/services/xero_sync_service.py`) and the existing tests.

Write `tests/test_costing_allocations.py`:
- One or more tests per AC, named `test_acNN_...`, each falsifiable (it must go red if the
  behaviour broke). Recompute every expected number from the contract.
- Purchases come in through the real 8.1b sync: import `FakeXero`, `txn`, `line`, `account`,
  `connect`, `sync`, `live_lines`, `documents` from `tests.test_costing_purchases`; costs via
  `tests.costing_helpers` (`lot_cost`, `execution_cost`, `lot`, `price`, `flows`, `user_client`,
  `new_org`, `purge`, `workflow`, `complete`). Use the API routes the contract lists
  (`/api/core/costing/purchases...`) for actions; the model `PurchaseAllocation` in
  `app.features.costing.models` for direct DB assertions (columns as the contract names them).
- Cover the tab rule row by row, the line arithmetic (over-allocation 400 with nothing written),
  manual prices deactivated by record/link, refunds, review keep/unlink, the changes-later table
  (amount rescale incl. $60/$30→$66/$33, to-zero → orphaned, recoded, voided, superseded),
  permissions (incl. costs.manage without inventory.adjust), tenant isolation (404, nothing
  changed, candidates never cross orgs), idempotency replay, needs_rate → 400.
- Use fixture ordering `(flask_app, world, db)` when a test needs `flask_app` (so the app
  context outlives the world teardown).

Expect every test to fail now (the implementation doesn't exist yet): run
`PYTEST_XDIST_WORKER=cogsa env -u ENVIRONMENT uv run pytest tests/test_costing_allocations.py -q -p no:cacheprovider`
and confirm they fail for missing routes/models, NOT for setup errors in your fixtures (fix any
fixture error). Then `uv run --extra dev ruff check tests/test_costing_allocations.py && uv run --extra dev ruff format tests/test_costing_allocations.py`.

Final message: tests per AC, the run summary line, and any contract ambiguity you hit (quote the
spec line) — don't guess silently.
