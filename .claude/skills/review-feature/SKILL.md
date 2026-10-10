---
name: review-feature
description: "Orchestrator that audits an EXISTING feature with the same verification chain new-feature uses (migration audit, security-audit, e2e-playwright, observability, unit coverage, ci-gate) and patches what it finds. Use this skill when the user asks to review, audit, harden, or health-check a feature, blueprint, or area of the app, or says 'is <feature> solid', 'check <feature> before launch', or wants existing code brought up to the guardrail standard."
---

# Review Feature

Same gates as new-feature, pointed backwards: instead of verifying fresh work, you measure an existing feature against the standard and close the gaps. The output is the same set of reports and verdicts, so a reviewed feature and a newly built one end up provably equivalent.

## Step 1: Identify the target (inline, interactive)

Run **preflight** first (`python3 scripts/preflight.py --json`, or use the report the caller passed you). Repair `blockers` per its table; take `verification_mode` and `live_server_tests` from `decisions` instead of probing. An audit that opens by misreading a down test DB as a broken feature wastes the whole chain.

**Then sweep the index before offering or picking anything**: `python3 scripts/feature_index_sweep.py --json`. This reconciles `.agents/feature-index.md`'s `reviewed:` lines against ground truth — a `.agents/reports/<slug>/review.md` that proves a slice was actually reviewed (even if whoever finished it forgot to hand-edit the line), and a live `review/<slug>` worktree that proves one is already in flight (even though it can't have written `review.md` yet) — and self-updates the file in place. Run this every time, including when entrypoint already ran it moments ago as part of dispatch: it's a fast, idempotent re-check, and if this run *is* the one in that freshly-cut worktree, sweeping again costs nothing. Take the picklist from its output, not a hand-sort of the raw file:

- `picklist_order` — every slice not currently in flight, sorted never-reviewed-first (oldest audits next), most-recently-reviewed last.
- `excluded_in_review` — slices with a live worktree and no `review.md` yet. Never offer or auto-pick one of these; a review is already running there. If the user names one of these by area, say so and ask if they want to check on that run instead (via `herdr worktree list`/`agent_queue.py list`) rather than starting a second one.
- Per-slice `computed_status: partial` — a report dir with `baseline.md` but no `review.md`: a review started and stalled (crashed, was abandoned, or a worktree was cleaned up mid-run). Worth surfacing as the highest-priority pick, not just another "never" — the work is half-done and the baseline/security-audit/e2e artifacts already there are reusable, not garbage to discard.

Ask the user which feature. Offer the candidates from **the feature index** (`.agents/feature-index.md`) rather than making them type or re-deriving the map yourself: it already breaks the app into 14 named slices + platform, each with subscription tier, layer, routes, and `depends on` / `depended on by`. Use its "Quick routing table" to match a vague ask ("the CRM sync", "the wizard") to a slug, and present the matching slice(s) as the picklist. Confirm the slug and scope (one slice, or an explicitly wider set the user names), and read the index block's `depended on by` line so the audit scope accounts for blast radius before Step 3 starts — a slice six others depend on gets reviewed differently than a leaf.

If the index is missing, or its `Last verified` date looks old, spot-check one `routes:` or `backend:` line from the candidate slice against the live code before trusting it. On a genuine miss, fall back to the old mechanism — grep the app factory for `register_blueprint`, or `ls app/features/` — and tell the user the index is stale or absent rather than silently trusting it; a stale index compounds the same way a stale spec does (Step 2). Refreshing the index is not this skill's job — the sweep above handles routine drift, and a miss the sweep can't explain is **docs-truth**'s finding to fix, not something to patch inline here.

**Unattended** (scheduled sweep, or called by another skill — `.agents/autonomy.md`): take the scope from the caller's input. If none was given, pick from the sweep's `picklist_order` rather than asking, and never from `excluded_in_review`: prefer any `partial` (stalled) slice first — finishing started work beats starting new work — then check the index's "Known coverage gaps" table, then breadth of `depended on by` (more dependents = higher blast radius), then fall back to most recently changed (`git log --since=30d --name-only -- app/features/ app/core/backend/`) if still tied — and state the choice and why in the report. Review one feature well; don't sweep the whole app in one unattended run.

## Step 2: Establish or reconstruct the spec

The chain needs acceptance criteria to audit against.

- Spec exists at `.agents/specs/<slug>.md`: read it, confirm with the user it still matches reality, note drift.
- No spec: reconstruct one by reading the code. Routes become behavior statements, validations become criteria, models become the data section. Write it in the spec-first format with `status: reconstructed` and one `ASSUMPTION:` line per inference, then show the user for a quick confirm. Reviewing against criteria the code trivially satisfies is circular, so flag any AC you derived purely from what the code already does.

Baseline before touching anything: `git status` clean, `uv run pytest tests/test_<slug>.py -v` (see `.agents/conventions.md` §6 — flat `tests/test_<slug>.py`, no `tests/unit`/`tests/integration` split in this repo) result recorded in `.agents/reports/<slug>/baseline.md`. If tests are already red, that is finding number one and gets fixed before the audit stages run, or the stage reports drown in pre-existing noise — **unless the failures never reached an assertion** (connection errors, missing service), which is **suite-warden**'s problem, not this feature's. Don't open an audit by blaming a feature for an absent app server.

## Step 3: Run the chain

Same stage prompt template as new-feature (skill path, slug, spec, report path, `VERDICT:` line). Run in this order:

**`.agents/verification-chain.md` is the contract** — execution mode, model routing,
read-only graders, blocking rules, and the stage prompt template live there, shared with
`new-feature` and `fix-bug`. Read `verification_mode` and `grader_engine` from preflight and
drive stages accordingly. Claude stays Architect and patches what gets found; the graders
(`security-tenant-audit`, `test-evaluator`) run read-only on Codex and hand findings back
rather than fixing them. The chain and verdicts are identical in every mode.

1. **migration audit** (migration-safety skill, only if the feature has models/migrations): verify every revision touching its tables has a real downgrade and survives up/down/up; flag any historical destructive change with no permit file.
2. **security-audit** and **e2e-playwright** in the same turn, parallel — the only declared pair (`.agents/model-routing.json` → `concurrency.parallel_groups`), safe because security-audit is read-only and e2e-playwright is the single writer. Two writing stages never share a turn; they share a worktree (`.agents/verification-chain.md` §6).
   - security-audit scoped to the slug; on existing code expect findings, that is the point. It reports them — **this review patches them**, in Step 4.
   - e2e-playwright in gap-fill mode: run whatever exists under `tests/e2e/<slug>`, then write tests for every AC with no coverage, including the mandatory cross-tenant probe and unhappy paths.
3. **unit coverage check**: `pytest --cov=app/features/<slug> --cov-report=term-missing` to find uncovered branches; hand the gaps to **test-author** to write the missing tests against the flows in `.agents/test-map.md` (it also updates the map's status rows for this feature) rather than hand-rolling them here. Every uncovered branch in routes/service is a gap.
4. **test-evaluator**: grades the tests test-author added (and any this review changed) — an audit that closes a coverage gap with a test that asserts nothing has hardened nothing. Verdict must be `valid`.
5. **perf-guardrails** after e2e passes, when the feature has pages/API routes: run `scripts/perf_triage.py` for the priority checklist, measure the feature's routes against `.agents/perf/budgets.json` (adding them to the measure lists if absent), and remediate or hand off ceiling breaches.
5b. **page-design** when the feature has a page and it fails that skill's bar (controls before content on the first screen, undesigned empty/phone/dark states, off the shared tokens): hand it the page; it researches, plans and loops on screenshots, and its tests go back through step 4.
6. **observability** in instrument mode: add the event logging the feature is missing, especially `access_denied` warnings.
7. **ci-gate verify** last, always: everything added above must be collected and enforced or it evaporates.

### Herdr stage hygiene

When verification_mode=herdr-tabs, launch every chain stage with
python3 scripts/agent_launch.py launch ... --cwd "$PWD". The launcher binds the
new tab to the live worker workspace that owns that worktree; never run raw
herdr tab create, which can attach a worker's stage to Sauron's focused
workspace instead.

As soon as a stage's output has been read, its verdict/report has been persisted,
and the result has been handed back to this orchestrator, close its disposable
stage tab:

    python3 scripts/agent_launch.py close <pane_id>

This command refuses live agents and a worker workspace's root tab. Do not defer
stage-tab cleanup until the end of the review or leave completed Codex/Claude
stage panes for Sauron to discover later.

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

**Use the history store so the review compounds** (`scripts/finding_history.py`, `.agents/history/README.md`). A repeat audit of the same feature should not re-litigate findings a human already rejected, nor miss a fixed bug that returned. For each finding, `finding_history.py decide` first: `suppress` (log it under a `suppressed (prior verdict):` line, keep it out of the body), `recurring` (a regression — surface loudly, patch first), else triage normally. After ruling, `finding_history.py record` the verdict (`--skill review-feature`, `--ref` the branch) — this is also the accepted-vs-rejected signal the scorecard reads (`.agents/metrics/`).

## Step 5: Report honestly

Present the table, the before/after (coverage %, findings fixed, tests added, rules added to `.semgrep/`), and what remains open with your recommendation. Set the spec `status: reviewed`, then run `python3 scripts/feature_index_sweep.py` — it finds the `review.md` you just wrote in Step 4 and updates the slice's `reviewed:` line in `.agents/feature-index.md` to today's date itself (formatted consistently with every other slice, pointing at the report). Don't hand-edit the line; the sweep is what lets a future `review-feature` run — here or in a different worktree entirely — see this one is done instead of re-picking the same slice. If the review changed code, call the **merge-request** skill to write the MR (from this report and the spec), push, open it, and watch the pipeline — same as new-feature's final step, do not assemble the MR yourself. No direct commits to main.

**Record the run** (`.agents/autonomy.md` → Measure yourself): append a metrics row per stage that ran, so the scorecard sees this audit — `python scripts/skill_metrics.py record --skill <stage> --run-type chained --scope <slug> --verdict <v> --findings <n> --ref <branch>`. Finding verdicts already went to the history store in Step 4; the MR's merge/close is recorded later as an `outcome` on the same `--ref`.

## Rules

- A review that only reads code and writes prose is half a review; the deliverables are tests, rules, and patches that outlive the conversation.
- Do not refactor beyond what findings require. Reviews that turn into rewrites lose the baseline that made their verdicts meaningful.
- Pre-existing failures are reported as found, never quietly fixed and forgotten; the user should learn their feature was red.
- If the reconstructed spec reveals the feature has no coherent criteria at all, say so; that is a product conversation, not a patch.
