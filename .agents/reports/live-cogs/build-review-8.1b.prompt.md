# build-review — live-cogs 8.1b Xero purchases in

Worktree: /home/johnny/workflow-engine/.claude/worktrees/live-cogs-b, branch feat/live-cogs-b,
stacked on feat/live-cogs (8.1a cost engine). You are read-only: do NOT edit files.

Review `git diff feat/live-cogs...HEAD` plus the uncommitted working tree (`git status`; the
builder could not commit, so some files are untracked or staged: read them directly) against
`.agents/specs/live-cogs.md` v5. Scope is 8.1b only: "Deciding what is a stock purchase" (Layer 1),
"Xero sync changes", "When Xero changes later" (line side only; allocations are 8.1c's, reached
through `purchase_sources.hooks`), data model `xero_accounts` / `purchase_documents` /
`purchase_lines`, ACs AC1–AC4 and AC64–AC74, and decisions B1–B9 (read them: they are the
choices the builder made and you may overturn any with a reason). Tests:
`tests/test_costing_purchases_{sync,jobs,access}.py`, `tests/test_xero_purchases_client.py`,
`tests/costing_purchase_helpers.py`; all 113 pass and three mutation spot-checks (currency
direction, reclassification on chart change, reason precedence) each made tests fail.

Assume the code is guilty. Hunt for, in order:

1. Wrong money: ex-GST conversion per `LineAmountTypes`, foreign currency (Xero's CurrencyRate is
   foreign per ONE base unit, so base = foreign / rate), rounding, refund sign, header totals,
   anything that could make a stored amount differ from what Xero says
   (`app/features/costing/purchase_sources.py`, `normalise_bank_transaction`).
2. Change detection: any sequence of Xero edits (amount, recode, delete/void, vanished line key,
   reappearing line, positional keys, a document going voided → active) where
   `_update_line` / `_retire_line` / `upsert_document` flag the wrong thing, flag twice, miss a
   hook call, leave `superseded_at` / `review_reason` inconsistent, or violate the table check
   constraints (e.g. `not_stock_amount` rescale breaking
   `abs(not_stock_amount) <= abs(amount_ex_tax)`).
3. Sync jobs (`app/features/crm/services/xero_sync_service.py`): job status (completed /
   partial / failed) in every combination, the shared `last_successful_sync_at` resume point
   (must not move for purchases-only or history jobs, must not move when purchases fail),
   the `costing` feature gate, exceptions that could leave the DB session unusable for the
   sales half, `XeroTokenExpiredError` handling, savepoints.
4. Xero client (`xero_api_client.py`): pagination, `where` syntax, `if_modified_since`, DELETED
   rows, retry reuse, anything the real Xero API would reject that the fakes accept.
5. Tenancy and data: every query org-filtered, composite FKs, the migration vs the models
   (`costing_purchases_001.py`), constraints, cascade, downgrade guard, the data-export secret
   column allowlist, access-policy coverage of `GET /api/core/costing/purchases` (default deny,
   404 without `costing`, 401/403 ordering), input validation on the route.
6. Layering: crm ↔ costing imports (no cycle at import time), 8.1a code reused not forked.
7. Anything a user would hit that the tests don't cover.

Known and not yours to flag: `cost_flows.source_key` failing
`tests/test_data_export.py::test_every_secret_looking_column_is_dropped_or_declared_safe` is an
8.1a defect already on the base branch; the allocation side of "changes later", rules, record /
link actions and the Purchases page UI are 8.1c/d.

You may run read-only commands (grep, git, python -c for arithmetic).

Output: markdown, findings ranked high→low, each with file:line, a concrete failing input or
scenario (observed vs expected), and the fix. End with exactly one line:
`VERDICT: pass` or `VERDICT: fail`.
