---
name: review-feature
description: "Orchestrator that audits an EXISTING feature with the same verification chain new-feature uses (migration audit, security-audit, e2e-playwright, observability, unit coverage, ci-gate) and patches what it finds. Use this skill when the user asks to review, audit, harden, or health-check a feature, blueprint, or area of the app, or says 'is <feature> solid', 'check <feature> before launch', or wants existing code brought up to the guardrail standard."
---

# Review Feature

Same gates as new-feature, pointed backwards: instead of verifying fresh work, you measure an existing feature against the standard and close the gaps. The output is the same set of reports and verdicts, so a reviewed feature and a newly built one end up provably equivalent.

## Step 1: Identify the target (inline, interactive)

Ask the user which feature. Offer the candidates rather than making them type: list registered blueprints (grep the app factory for `register_blueprint`, or `ls app/features/`). Confirm the slug and scope (a blueprint, or a wider slice the user names).

## Step 2: Establish or reconstruct the spec

The chain needs acceptance criteria to audit against.

- Spec exists at `.agents/specs/<slug>.md`: read it, confirm with the user it still matches reality, note drift.
- No spec: reconstruct one by reading the code. Routes become behavior statements, validations become criteria, models become the data section. Write it in the spec-first format with `status: reconstructed` and one `ASSUMPTION:` line per inference, then show the user for a quick confirm. Reviewing against criteria the code trivially satisfies is circular, so flag any AC you derived purely from what the code already does.

Baseline before touching anything: `git status` clean, `pytest tests/unit/<slug> tests/integration/<slug> -q` result recorded in `.agents/reports/<slug>/baseline.md`. If tests are already red, that is finding number one and gets fixed before the audit stages run, or the stage reports drown in pre-existing noise.

## Step 3: Run the chain via subagents

Same subagent prompt template as new-feature (skill path, slug, spec, report path, `VERDICT:` line). Spawn in this order:

1. **migration audit** (migration-safety skill, only if the feature has models/migrations): verify every revision touching its tables has a real downgrade and survives up/down/up; flag any historical destructive change with no permit file.
2. **security-audit** and **e2e-playwright** in the same turn, parallel:
   - security-audit scoped to the slug; on existing code expect findings, that is the point.
   - e2e-playwright in gap-fill mode: run whatever exists under `tests/e2e/<slug>`, then write tests for every AC with no coverage, including the mandatory cross-tenant probe and unhappy paths.
3. **unit coverage check** (inline, no dedicated skill): `pytest --cov=app/features/<slug> --cov-report=term-missing`; every uncovered branch in routes/service is a gap; write the missing tests or delegate to the builder step.
4. **observability** in instrument mode: add the event logging the feature is missing, especially `access_denied` warnings.
5. **ci-gate verify** last, always: everything added above must be collected and enforced or it evaporates.

## Step 4: Aggregate, patch, re-verify

Merge all reports into `.agents/reports/<slug>/review.md`:

```markdown
# REVIEW: <slug>
date: <date>
baseline: tests green | <n> pre-existing failures
verdict: clean | patched | findings-open | escalated

| stage | verdict | findings | report |
|-------|---------|----------|--------|
```

Patch priority: security `fix` items first, then broken/missing tests, then observability gaps. After each patch batch, re-run the affected stage plus the unit suite. Same circuit breaker as new-feature: a finding that survives two full patch rounds gets escalated to the user with hypotheses, not a third round.

## Step 5: Report honestly

Present the table, the before/after (coverage %, findings fixed, tests added, rules added to `.semgrep/`), and what remains open with your recommendation. Set the spec `status: reviewed`. If the review changed code, it ships like any change: branch `review/<slug>`, CI green, no direct commits to main.

## Rules

- A review that only reads code and writes prose is half a review; the deliverables are tests, rules, and patches that outlive the conversation.
- Do not refactor beyond what findings require. Reviews that turn into rewrites lose the baseline that made their verdicts meaningful.
- Pre-existing failures are reported as found, never quietly fixed and forgotten; the user should learn their feature was red.
- If the reconstructed spec reveals the feature has no coherent criteria at all, say so; that is a product conversation, not a patch.
