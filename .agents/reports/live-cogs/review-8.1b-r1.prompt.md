# test-evaluator + build-review round 1 (of max 3) — live-cogs 8.1b Xero purchases in

Read-only. Worktree /home/johnny/wt-live-cogs-xero, branch feat/live-cogs-xero (stacked on
feat/live-cogs, MR !689). Contract: the section "## 8.1b build contract — Xero purchases in" of
`.agents/specs/live-cogs.md` (v2, written after your spec-critic report
`.agents/reports/live-cogs/spec-critic-8.1b.md`).

Diff to review: `git -C /home/johnny/wt-live-cogs-xero diff feat/live-cogs...HEAD`. Main code:
`app/features/costing/purchase_sources.py`, `app/features/crm/services/xero_sync_service.py`
(_run_purchases and its callers), `xero_api_client.py` (get_base_currency, get_accounts,
get_bank_transactions), models + `costing_purchases_001`, `routes.py` accounts endpoints.
Tests: `tests/test_costing_purchases.py` (written against the contract; all pass).

One thorough pass, ranked by impact:
A. Tests: falsifiability (would each go red if the behaviour broke?), tautologies, setups that
   don't reach the path, expectations that contradict the contract, missing ACs.
B. Code: every place the code diverges from the contract; wrong amounts or signs; line
   identity bugs (supersede/insert/update, the partial unique index, LineItemID moving
   position); start_date / cursor / tenant handling; the savepoint and commit boundaries
   (could sales work be lost or committed wrongly? could a failed phase leave partial rows?);
   scope gating; tenant isolation; anything that will hurt 8.1c (allocations on these lines).

Each finding: file:line, concrete failing scenario, fix. End with exactly one line:
`VERDICT: pass` or `VERDICT: fail`.
