# test-evaluator + build-review round 1 (of max 3) — live-cogs 8.1c-2 rules, pre-fill, bulk, historical runs

Read-only. Worktree /home/johnny/wt-live-cogs-rules, branch feat/live-cogs-rules (stacked on
feat/live-cogs-alloc). Do NOT monitor any MR pipeline. Contract: spec section
"## 8.1c-2 build contract". Diff: `git -C /home/johnny/wt-live-cogs-rules diff feat/live-cogs-alloc...HEAD`.
Code: `app/features/costing/rules.py` (new), actions.py (prefill, historical tabs),
purchase_sources.py (classify_line with rules), routes.py, xero_sync_service.historical_purchases,
xero_api_client to_date, models + `costing_rules_001`. Tests: `tests/test_costing_rules.py`
(written by Claude before the code; all pass).

One thorough pass, ranked: wrong treatment or pre-fill numbers; precedence holes; rule changes
touching lines they mustn't (recorded / allocated / superseded); historical runs (savepoint,
idempotency, start-date lift leaking into normal syncs, scope gating); bulk savepoints and
isolation; validation; tenant isolation; migration (the expression unique index, FK SET NULL,
downgrade guard); and tests that would stay green if the behaviour broke.

Each finding: file:line, failing scenario, fix. End with exactly one line:
`VERDICT: pass` or `VERDICT: fail`.
