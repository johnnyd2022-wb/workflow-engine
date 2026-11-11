# build-review round 2 (of max 3) — live-cogs 8.1c-1 recording purchases into stock

Read-only. Worktree /home/johnny/wt-live-cogs-alloc. Do NOT monitor any MR pipeline. Your round-1
report: `.agents/reports/live-cogs/review-8.1c1-r1.md`; fixes in HEAD
(`git -C /home/johnny/wt-live-cogs-alloc show HEAD --stat`); regressions in the
"build-review round 1 regressions (8.1c-1)" section of `tests/test_costing_allocations.py`.
Contract: spec section "## 8.1c-1 build contract".

1. Each round-1 finding: resolved / partially / not, with evidence.
2. Fresh adversarial pass over `git diff feat/live-cogs-xero...HEAD -- app/` for anything still
   HIGH or MEDIUM — especially the new lock order (get_line locks document then line; the sync
   locks document then lines; lots sorted), on_document_restored, the rescale split, and
   derive_state now flushing.

Each finding: file:line, failing scenario, fix. End with exactly one line:
`VERDICT: pass` or `VERDICT: fail`.
