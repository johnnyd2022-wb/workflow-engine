# build-review round 2 (of max 3) — live-cogs 8.1a cost engine

Worktree /home/johnny/wt-live-cogs, branch feat/live-cogs, read-only (do NOT edit files).
Your round-1 report is `.agents/reports/live-cogs/build-review-r1.md`. Commit f085e7df addresses it
(`git -C /home/johnny/wt-live-cogs show f085e7df --stat`). Contract: `.agents/specs/live-cogs.md` v4,
8.1a scope.

1. For each round-1 finding, verify the fix in the code and its regression test in
   `tests/test_costing_engine.py` (section "build-review round 1 regressions"): resolved,
   partially resolved, or not resolved, with evidence. Finding #8 (downgrade refusal) was
   deliberately kept: the refusal protects user-typed prices, matching the repo's migration
   convention (e.g. planning_replan_001); say if you think that's wrong and why.
2. The engine (`app/features/costing/engine.py`) was rewritten from recursion to an explicit
   stack over ("lot", id) and ("step", execution, position) nodes. Attack the rewrite: wrong
   dependency lists, values read before they're computed, cycle handling (`_active`), memo
   keyed wrongly, the per-step carry/absorb bookkeeping, `_split_weights` grouping by logical
   output, the node budget.
3. A fresh adversarial read of the whole 8.1a diff for anything round 1 missed.

Report only real defects, ranked, each with file:line, a concrete failing scenario and the fix.
End with exactly one line: `VERDICT: pass` or `VERDICT: fail`.
