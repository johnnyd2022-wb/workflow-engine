# test-evaluator + build-review round 1 (of max 3) — live-cogs 8.1e-1 readiness and total paid

Read-only. Worktree /home/johnny/wt-live-cogs-ready, branch feat/live-cogs-readiness (stacked on
feat/live-cogs-rules). Do NOT monitor any MR pipeline. Contract: spec section
"## 8.1e-1 build contract". Diff: `git -C /home/johnny/wt-live-cogs-ready diff feat/live-cogs-rules...HEAD`.
Code: `app/features/costing/readiness.py` (new), routes.py (readiness), `app/core/backend/inventory_routes.py` (total_paid). Tests: `tests/test_costing_readiness.py` (written before the code).

One thorough pass, ranked: wrong readiness (a material missed or double-listed, the walk
not terminating, legacy vs output-id buckets, declared-inputs basis); total_paid writing an
entry without permission / feature, or a lot without its price (transaction), or breaking the
existing Add Inventory paths (barcode add-quantity, untracked, multi-site); tenant isolation;
performance (readiness list walks every product — N+1 at realistic sizes); and tests that would
stay green if the behaviour broke.

Each finding: file:line, failing scenario, fix. End with exactly one line:
`VERDICT: pass` or `VERDICT: fail`.
