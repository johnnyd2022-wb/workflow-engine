## Summary

Roadmap **8.1e-1 — cost readiness and Add Inventory "total paid"** ("8.1e-1 build contract"), stacked on 8.1c-2. Readiness per product keyed by step output definition id with a legacy name bucket (round-2 gap 15): from the latest batch, walked back through earlier batches each once, or the process's declared inputs when there's no batch yet. Add Inventory accepts `total_paid`, written with the lot in one transaction for `costs.manage` users in costing orgs (ignored otherwise; invalid → 400, no lot). API only; the panels are 8.1e-2.

Spec: `.agents/specs/live-cogs.md` (see the build contract named above). Draft: stacked on the MR below it; retargets as each one merges.

## Acceptance criteria

`tests/test_costing_readiness.py` (written before the code): AC38, AC39, AC40 (no cost fields on existing payloads), AC87–AC90.

## Verification

| Stage | Verdict |
| --- | --- |
| tests written first | 12 pass |
| regression (inventory, multi-site, costing, policy, registries) | 243 passed |
| build-review (Codex) round 1 | **queued** (Codex usage limit; runs tonight) |
| full suite | not yet run on this branch |

## Known limitations / open

- No Codex review yet; full suite pending.
- The readiness list evaluates every product on each call; fine at current sizes, worth a cache if catalogues grow.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_012K4jB79TxztZobCHJU3cVj
