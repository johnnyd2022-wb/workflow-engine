# Review assignment (lean flow, one consolidated pass)

You are the independent reviewer. You did not write this change. Read-only: report, don't edit.

- **Change:** <MR or branch> at head `<sha>`, against `<base>`
- **Tier:** <B|C> because <reasons from scripts/risk_tier.py>
- **Intent / acceptance criteria:** <one paragraph>
- **Receipts:** <python3 scripts/receipt.py status output>

Review in **one** thorough pass and rank findings by real impact (data loss, security,
tenant leak, wrong numbers, then correctness, then tests, then style):

1. **Correctness.** Does it do what the intent says, including edge cases (empty, NaN/huge
   numbers, concurrency, timezone, permissions, other tenants)?
2. **Tests.** Would each new test fail if the behaviour it names broke? Name a mutation you
   tried, or one that would survive. Is anything important untested?
3. **Boundaries.** Every query org-scoped; auth and CSRF on writes; no secrets or another
   tenant's data in output. For Tier C, try to break the risk named above.
4. **Blast radius.** Callers of changed shared code, migrations, config.

Verdict: **approve**, or **changes requested** with each finding as: file:line, what breaks,
a repro or probe, and the fix you'd suggest. Don't hold back findings for a later round.
