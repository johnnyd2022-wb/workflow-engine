---
name: lean-change
description: "Lean front door for code work (bug, feature or review): picks a risk tier first (scripts/risk_tier.py sets the floor), builds with one implementer, ties test evidence to the tree (scripts/receipt.py), and gets ONE consolidated independent review for ordinary and high-risk changes instead of a stage per grader. Use when /entrypoint routes code work here (.agents/workflow-mode.json mode 'lean'), or when the user asks for the lean flow. Not when the user names /new-feature, /fix-bug or /review-feature: those keep the full chain."
---

# lean-change

The lean flow from !671, running next to the original chain, not replacing it. The contract
is `.agents/verification-tiers.md`; read it first. The switch is `.agents/workflow-mode.json`.

## Steps

1. **Understand the ask.** Bug: symptom, where, request_id. Feature: one-line outcome and
   acceptance criteria. Review: the area. Check `docs/source-to-sale-plan.md` for the item ID.
   Use the worktree and preflight report `/entrypoint` handed you.
2. **Tier it before building.** `python3 scripts/risk_tier.py --base origin/main --json` on the
   files you expect to touch (`--paths ...`), then on the real diff. Write the tier and reasons
   at the top of `.agents/templates/handoff.md` (copy it to `.agents/tmp/handoff.md`).
3. **Spec only when it earns it.** Tier C or an ambiguous ask: a short spec via `spec-first`.
   Tier A/B with clear acceptance criteria: the criteria in the handoff are the spec.
4. **Build.** One implementer. Bug: failing test first, keep its failing output for the
   reviewer. Migrations: `migration-safety` on a private DB (`PYTEST_XDIST_WORKER=<x>`).
5. **Check with receipts**, e.g.
   `python3 scripts/receipt.py run --name unit -- env -u ENVIRONMENT uv run pytest <files> -q`,
   plus `ruff`, and a browser test only if rendering or interaction changed.
   `python3 scripts/receipt.py status` must be all `passed` (fresh) before review.
6. **Review (Tier B/C).** Fill `.agents/templates/lean-review.md` and send it to one reviewer:
   Codex read-only (`python3 scripts/agent_launch.py launch lean-review --scope <slug> --prompt-file <file>`,
   or the Breaker pane via `herdr-multi-agent-collab`). Codex out of quota: an independent Claude
   pane that didn't write the diff, named in the MR. Tier A: read your own diff carefully; no reviewer.
7. **Fix, re-review only the fixes.** At most 3 rounds; list anything left in the MR.
8. **MR** via `merge-request`: tier + reasons, receipts, reviewer and rounds.
9. **Record for the trial:**
   `python3 scripts/skill_metrics.py record --skill lean-change --run-type <interactive|chained|scheduled> --verdict <clean|patched|findings-open|error> --ref '!<n>' --findings <review findings> --duration <seconds> --notes "workflow=lean kind=<bug|feature|review> tier=<A|B|C> rounds=<n> reviewer=<codex|claude|self>"`.
   Classic runs can add `workflow=classic tier=<A|B|C> rounds=<n>` to their notes the same way, so the two compare.

## Never

- Go below the script's tier, or call a Tier C change "small".
- Let the author review its own diff for Tier B/C.
- Quote a stale or no-tests receipt as a pass.
- Change `.agents/verification-chain.md` or the classic front doors; this flow sits beside them.
