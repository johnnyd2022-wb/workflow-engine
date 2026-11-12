## Summary

Roadmap **8.1c-1 — recording purchases into stock** ("8.1c-1 build contract"), stacked on !690. Line state and `purchase_allocations`; **record** (creates lots from a purchase), **link** (to lots entered by hand — a purchase replaces any typed price), **refund**, **not stock**, **skip**, **reopen**, **review** keep/unlink, **edit allocations**; candidate lots; the purchases list with one tab rule; and what happens when Xero later changes, voids, supersedes or recodes a recorded line (rescale, orphan → estimated, review, restore). The cost engine now prices lots from allocations; orphaned ones (and orphaned refunds) are estimated; refunds apply once. API only — no UI.

Spec: `.agents/specs/live-cogs.md` (see the build contract named above). Draft: stacked on the MR below it; retargets as each one merges.

## Acceptance criteria

All in `tests/test_costing_allocations.py` (written by Codex from the contract, plus a rounding-remainder case): AC5–AC9, AC11, AC12, AC30, AC34, AC35, AC74–AC80, and the build-review round 1 regressions.

## Verification

| Stage | Verdict |
| --- | --- |
| tests (Codex-written) | mutation-checked; a gap (rescale remainder) found and closed |
| build-review (Codex) round 1 | fail, 6 high / 5 medium → all fixed (`.agents/reports/live-cogs/review-8.1c1-r1.md`) |
| round 2 | **queued** (Codex usage limit; runs tonight) |
| full suite | 4373 passed, 31 skipped, 1 failed: `test_changes_feed.py::test_head_query_uses_the_partial_index` — known flaky on main (planner choice), unrelated |

## Known limitations / open

- Build-review rounds 2–3 still to run; findings will be fixed on this branch.
- Rescaling to 0 / other sign / needs-rate orphans rather than rescales (by design).

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_012K4jB79TxztZobCHJU3cVj
