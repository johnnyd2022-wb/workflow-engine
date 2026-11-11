## Summary

Roadmap **8.1c-2 — purchase rules, pre-fill, bulk, historical runs** ("8.1c-2 build contract"), stacked on 8.1c-1. `purchase_rules` with normalised matchers and complete deterministic precedence (round-2 gap 13); the winning rule decides a line's treatment (`treatment_rule_id`); rule changes re-classify only open/skipped lines with no allocation. Cards pre-fill from the rule's template, else last time for this payee, else one empty row. **Remember this** and **not stock, always** create rules. **Bulk** skip / not stock / apply rule with per-line results. **Historical runs** always refetch their date range from Xero with the start date lifted (round-2 gap 10) and a historical list mode. API only.

Spec: `.agents/specs/live-cogs.md` (see the build contract named above). Draft: stacked on the MR below it; retargets as each one merges.

## Acceptance criteria

`tests/test_costing_rules.py` (written before the code): AC10, AC13–AC20, AC81–AC86.

## Verification

| Stage | Verdict |
| --- | --- |
| tests written first | 33 pass |
| regression (all costing, CRM, registries) | 468 passed |
| build-review (Codex) round 1 | **queued** (Codex usage limit; runs tonight) |
| full suite | not yet run on this branch |

## Known limitations / open

- No Codex review yet; full suite pending.
- Historical runs are synchronous, like the existing sync.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_012K4jB79TxztZobCHJU3cVj
