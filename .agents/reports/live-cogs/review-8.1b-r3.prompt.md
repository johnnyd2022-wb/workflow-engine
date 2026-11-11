# build-review round 3 (FINAL, of max 3) — live-cogs 8.1b Xero purchases in

Read-only. Worktree /home/johnny/wt-live-cogs-xero. Your round-1 report:
`.agents/reports/live-cogs/review-8.1b-r2.md`; the fixes are in HEAD
(`git -C /home/johnny/wt-live-cogs-xero show HEAD --stat`); regression tests are the
"build-review round 2 regressions (8.1b)" section of `tests/test_costing_purchases.py`; the
contract (spec "## 8.1b build contract") was updated for voids, null amounts, token expiry and
the anchor. Do NOT monitor any MR pipeline.

1. Each round-1 finding: resolved / partially / not, with evidence.
2. A fresh adversarial pass over `git diff feat/live-cogs...HEAD -- app/` for anything still
   HIGH or MEDIUM, especially the new `_anchor_purchases` (it now runs inside the job-create
   transaction — any way it can fail the whole sync or lock), the voided-document early
   `continue`, `retire_account_lines`, and the `sales_phases_ok` partial rule's effect on
   existing CRM sync semantics.

Each finding: file:line, failing scenario, fix. End with exactly one line:
`VERDICT: pass` or `VERDICT: fail`.
This is the final round: report only HIGH/MEDIUM defects still present; anything lower goes in the MR as a known limitation.
