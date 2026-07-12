---
name: fix-bug
description: "Third front door for the biz-e code suite, alongside new-feature and review-feature. Triage a bug report using the observability stack, write a failing test that reproduces it FIRST, fix it, run the relevant verification chain subset, then hand off to merge-request. Use this skill whenever the user reports a bug, an error, unexpected behavior, a regression, or pastes a stack trace/request_id and wants it fixed — not for building new capability (new-feature) or auditing existing code with no reported symptom (review-feature)."
---

# Fix Bug

The third front door. Where `new-feature` starts from a spec and `review-feature` starts
from existing code with no complaint, `fix-bug` starts from a **symptom**: a report, a
stack trace, a request_id, a "this used to work." The discipline that makes a bug fix
trustworthy is proving it was actually a bug before touching anything, and proving it's
actually fixed after — both via a test, not narration.

## The chain

```
1. triage          (inline, via observability skill's Triage mode) -> root cause + evidence
2. repro test      (inline, written FIRST, proven red)              -> tests/test_<area>.py
3. fix             (inline)                                          -> minimal patch
4. verify          (inline)                                          -> repro test green,
                                                                         full suite still green
5. chain subset    (subagents, only the stages the fix touches)      -> reports
6. merge-request   (inline/subagent, always last)                    -> MR
```

## Step 1: Triage

Run the **observability** skill's Triage mode against the report. You need, before
writing any code: the request_id (if there is one), the log thread it pulls, the
traceback or the last-known-good behavior, and a hypothesis for root cause correlated
with recent commits (`git log --since`) or migrations (`alembic history`). If the report
has no request_id or timeframe, ask for one before guessing — triage without evidence is
just a different way of writing narration instead of a diagnosis.

If the bug is a tenant-isolation leak (org A sees org B's data) or an auth bypass, stop
triage and escalate to **security-audit** immediately alongside the fix; those get a
security report even when the "bug" framing undersells the severity.

## Step 2: Write the failing test first

Before changing any production code, write the test that reproduces the bug and confirm
it's red:

```bash
ENVIRONMENT=test uv run pytest tests/test_<area>.py::test_<bug>_repro -v   # must fail
```

- Name it for the bug, not the fix (`test_dashboard_summary_leaks_across_org` not
  `test_fix_for_ticket_123`) — the test should still make sense read cold in a year.
- Use the **test-fixtures** skill's factories/`two_org_two_user` for any org/user setup
  rather than hand-seeding; most cross-tenant bugs are exactly what that fixture exists
  to catch.
- If you cannot make the test fail on the current code, you have not reproduced the bug
  yet — go back to triage. A fix without a red test first is a guess that happens to
  look like a fix.
- Colocate in the existing flat `tests/test_<area>.py` for that area (see
  `.agents/conventions.md` §6) rather than a new bug-specific test file, unless no
  existing file covers the area.

## Step 3: Fix

Minimal patch that turns the test green. Read `.agents/conventions.md` for the pattern
to follow (repository method shape, org-scoping, naming) — a bug fix is not licence to
introduce a new idiom next to the one already in use nearby. Resist scope creep: fix the
reported bug, don't refactor the surrounding function unless the refactor is the fix.

## Step 4: Verify

```bash
ENVIRONMENT=test uv run pytest tests/test_<area>.py -v   # repro test green
ENVIRONMENT=test uv run pytest tests/ -v                 # nothing else broke
```

## Step 5: Chain subset, not the whole chain

Unlike `new-feature`, don't run every verification stage — run only what the fix
plausibly affects:

- Touched a query or auth check → **security-audit**, scoped to the changed file(s).
- Touched a user-visible flow → **e2e-playwright**, the relevant existing flow's test
  (don't write a new E2E suite for a bug fix unless the bug was E2E-only reproducible).
- Touched the data model or added a migration → **migration-safety**.
- Always: **ci-gate** in verify mode, last.

State which stages you skipped and why in the report, same rule as `new-feature` — silent
skips are not allowed, stated ones are fine.

## Step 6: Hand off

Call **merge-request** to write the MR description (bug summary, root cause, repro test,
fix, chain subset results), watch the pipeline, and handle review. Do not write the MR
yourself once `merge-request` exists — this is the one-line wiring point.

## Report

Write `.agents/reports/fix-bug/<date>-<slug>.md`:

```markdown
# FIX: <one-line bug summary>
date: <date>
symptom: <what was reported>
root_cause: <what triage found, with file:line>
repro_test: tests/test_<area>.py::test_<bug>_repro (red before fix, green after)
fix: <file:line, one-line description of the change>
chain_subset: [security-audit: pass, e2e-playwright: skipped (API-only bug)]
verdict: fixed | fixed-with-followup | could-not-reproduce
```

`could-not-reproduce` is a valid, honest outcome — report it with what you tried rather
than closing the loop with an unverified guess.

## Rules

- No fix without a red-then-green test. If the bug genuinely can't be reproduced in test
  (e.g. a timing race only seen under load), say so explicitly and propose what evidence
  would be needed instead of writing an untested patch.
- Never touch the report or the escalation history when it disagrees with you — if a
  prior fix attempt is in `.agents/reports/`, read it before re-diagnosing from scratch.
- Same circuit breaker as `new-feature`: if the same finding from the chain subset
  survives 2 rounds, stop and escalate rather than grinding a third.

## Handoffs

- ← **observability** (Triage mode): root cause and evidence chain.
- ← **security-audit**: escalated in for tenant/auth-class bugs.
- → **test-fixtures**: new factory needed if the bug's repro needs a model nothing
  seeds yet.
- → **security-audit / e2e-playwright / migration-safety**: chain subset, scoped.
- → **merge-request**: final step, always.
