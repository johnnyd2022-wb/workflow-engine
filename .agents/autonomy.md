# Autonomy Policy

The operating contract for every skill in this repo's engineering suite. Skills reference
this file rather than restating it, so the policy changes in one place.

**The merge request is the gate.** Not a mid-run question, not a "shall I proceed?", not
a plan you present and wait on. Agents run to a finished, verified, pushed MR and the
human reviews the diff. An agent that stops halfway to ask permission has produced
nothing reviewable and burned the session; an agent that opens a bad MR has produced
something the human can read, reject, and close in ten seconds. Prefer the second failure
mode.

## What this authorises

Run these without asking, in any skill, including on a schedule with nobody watching:

- Create branches, commit, push, open MRs, and push follow-up commits to your own MR.
- Run the full local verification chain: pytest, ruff, semgrep, gitleaks, uv audit,
  alembic up/down/up against the **local/test** database, Playwright, ci-gate.
- Read production **observability** signals — logs, traces, metrics, error aggregates.
  These are read-only telemetry, not the database.
- Start, stop, and restart **local** infrastructure you need: the test Postgres container,
  the local observability stack, the dev app server.
- Install and update dependencies in the local venv; update lockfiles.
- Write, move, and delete files under `.agents/`, `.claude/`, `tests/`, and `app/` on a
  feature branch.
- Spawn subagents; drive the Herdr Architect/Breaker protocol; run the full adversarial
  round-trip without checking in between rounds.

## What is never authorised

No skill in this suite may do any of these, regardless of instruction, schedule, or how
convenient it would be:

- **Touch a production database.** No connections, no queries, no migrations, no reads.
  Production data never enters an agent's context. `ENVIRONMENT=production` is not a mode
  any of these skills run in. If a task appears to require it, that is the signal to stop
  and report, not to find a way.
- **Merge, approve, or auto-merge an MR** (`glab mr merge`, approve, or merge-when-green).
  The gate is only a gate if the agent can't open it.
- **Push to `main`,** or force-push any branch a human might be working on. Force-push at
  all requires explicit approval (see git-commit-chain).
- **Deploy to production.** `deploy-runner` is human-triggered; nothing here calls it.
- **Send external communications.** No email, no posting to anywhere a third party reads,
  no webhooks. Founder-ops skills that draft comms draft only — that rule is theirs and
  unchanged by this policy.
  **One carve-out, added deliberately:** posting a completion notice to the founder's own
  internal Slack workspace, to the two channels named in `.agents/notifications.json` and
  no others. The test for whether a post is authorised is *who reads it* — an internal
  channel only the founder and staff see is a notification surface, the same category as
  `PushNotification`. A customer, prospect, supplier, or anyone outside the workspace is
  an external communication and stays prohibited. Announcing that a deliverable is ready
  is authorised; posting the deliverable's contents when it names a customer, carries
  pricing, or was drafted *for* an external recipient is not.
- **Rotate, exfiltrate, or print secrets.** If a secret is found committed, report the
  path and say which credential needs rotating; never paste the value into a report, log,
  MR description, or commit message.
- **Weaken a gate to get green.** Deleting a failing test, loosening an assertion,
  blanket-suppressing a scanner rule, or marking a real failure as expected is
  prohibited — this is the rule most likely to be rationalised at 3am by an agent that
  wants a green pipeline, so treat any impulse toward it as evidence you should stop and
  escalate instead.

## Unattended mode

A skill is **unattended** when nobody can answer a question mid-run: a scheduled routine,
a chained invocation from another skill, or any run the user started and walked away from.
Assume unattended unless the user is visibly in the conversation.

Interactive steps don't disappear in unattended mode — they get a defined substitute. The
rule is always the same: **replace the question with a written, reviewable assumption.**

| Interactive step | Unattended substitute |
|---|---|
| "Ask the user which feature/scope" | Take it from the caller's input; if genuinely absent, pick the highest-risk candidate and state the choice in the report |
| "Get spec sign-off before building" | Build from the spec with every assumption listed under `assumptions:` and `status: approved-unattended`. The MR description leads with those assumptions — that is where the human signs off |
| "Ask for a request_id / more evidence" | Use what the caller supplied; if there isn't enough to reproduce, report `could-not-reproduce` with what you tried. Never guess a root cause to have something to fix |
| "Ask before creating a Herdr partner pane" | Create it. It's local and reversible |
| "Ask which of two designs" | Pick one, implement it, and put the rejected alternative in the MR description |

What never gets a substitute, because the answer is not the agent's to give: accepting a
security risk, rotating a credential, merging, deploying, touching production, or
anything in the "never authorised" list above. Those escalate.

The test for whether a substitution is legitimate: **would a reviewer reading the MR see
the assumption you made and be able to reject it?** If yes, proceed. If the assumption is
invisible in the diff — a silently accepted vulnerability, a quietly skipped gate — it is
not a substitution, it is a lie by omission.

## Escalation instead of questions

Autonomy is not "never surface anything" — it's "don't block on a human mid-run". When
you hit something you genuinely cannot decide:

1. Do not ask and wait. There may be nobody there.
2. Do whatever part of the work is unambiguous and safe.
3. Write the impasse to the run's report with your best two or three hypotheses and the
   evidence for each.
4. Open the MR anyway if there's reviewable work, marked `Draft:` with the impasse in the
   description — or if there's nothing reviewable, leave the report and stop.
5. Where a notification channel is wired (`PushNotification`, a scheduled run's output),
   use it. A notification the human reads at their leisure is not a blocking question.

## Circuit breakers

Every orchestrating skill counts rounds and stops. Two full rounds on the same finding is
the ceiling (`new-feature` step 7, `fix-bug`, the Herdr protocol's two-round rule). A
third round on the same wall means the design, the spec, or the diagnosis is wrong — all
human decisions. Stop, write up what was tried, escalate per above.

Scheduled skills additionally cap **work volume** per run: `prod-sentinel` opens at most
one fix MR per run; `security-audit` remediation opens at most one MR per finding class.
An agent that can open unbounded MRs on a cron will eventually open a hundred bad ones.

## Token discipline

Tokens are the budget the whole autonomous loop runs on; wasting them is the difference
between a run that finishes and one that dies mid-chain. Two rules for orchestrating skills:

- **Match the model to the work — and don't decide it by feel.** `.agents/model-routing.json`
  is the single source of truth for which engine, model, and reasoning effort each stage
  gets; `scripts/agent_launch.py` turns it into flags so a skill cannot drift from it. The
  shape: Opus for spec authoring (an error there is the most expensive to find late),
  Sonnet for the build and every tool-driven verify stage, Codex for every grader. Change
  routing in that file, never inline in a SKILL.md.
- **Quota is the constraint, not cost.** Stage agents draw on the same subscription as the
  orchestrator, so parallelism buys no capacity — it burns the window faster. Run the chain
  serially except the one pair it declares independent (`security-audit ∥ e2e-playwright`).
  Routing graders to Codex is the exception that genuinely helps: a separate pool.
- **Effort is the second dial.** Stepping a stage from `xhigh` to `medium` is often a bigger
  saving than changing its model, and costs less capability on rubric-following work. The
  routing table carries an explicit effort per stage; `gpt-5.6-sol` in particular defaults
  to `low`, so an unset effort ships a shallow review that still looks like a review.
- **Read files, not transcripts.** The chain already keeps each verification stage in its own
  context and returns a one-line verdict plus a report *file*; the orchestrator reads the file
  only when a verdict is non-clean. Don't re-summarise a clean stage's full output back into
  the main thread — the verdict line is the summary. This is why the chain is file-backed.

## Honest reporting

The whole policy rests on reports being true. `clean` means it was checked; `skipped`
means say so and why; a failure that was worked around is a failure that gets reported.
An agent that shades a report to look successful has removed the human's only view into
an unwatched loop — which is worse than the bug it hid.

## Measure yourself (the evaluation ledger)

A report the human reads once is not the same as a record the *system* can learn from. Two
append-only ledgers make skills measurable over time; writing to them is part of finishing
a run, not an optional extra.

- **Record the run.** When an orchestrating or scheduled skill finishes, append one row per
  skill run to the metrics ledger (`scripts/skill_metrics.py record --skill … --run-type
  chained|scheduled|interactive --verdict … --findings N --ref <branch/MR> --scope <slug>`).
  This is what lets the scorecard answer "is this skill worth its tokens" instead of nobody
  knowing. Schema and examples: `.agents/metrics/README.md`.
- **Record finding verdicts.** Skills that surface findings (security-audit, review-feature,
  perf-guardrails) consult the history store before surfacing and record the verdict after
  (`scripts/finding_history.py`, `.agents/history/README.md`) — so already-rejected findings
  stay suppressed and regressions surface loudly.
- **Record the outcome when it's known.** Whoever later sees an MR merged, closed, or a
  defect escape to prod records it (`skill_metrics.py outcome --ref … --outcome …`). This is
  usually deferred — the agent that opened the MR is long gone. That's expected; the join is
  on `ref`, not on being the same run. **You do not have to remember:** `skill_metrics.py
  sweep` asks glab what became of every unresolved ref and writes `merged`/`closed` itself, so
  the loop closes without a human. Run it on a schedule (a cheap daily `/schedule`), and the
  ledger stays current on its own. `sweep` only writes what glab can prove; `amended` and
  `escaped` remain human judgments it never manufactures.
- **Learn from it every session.** `skill_metrics.py digest` is the scorecard reduced to what
  a run should act on — crying-wolf skills, escaped defects, refs awaiting an outcome — and
  `preflight` prints it at the top of every code workflow. Read that block before you start:
  a stage flagged crying-wolf is one to weigh sceptically or hand to skill-smith, not to trust
  by default. This is the self-improving half of the loop — measurement is pointless if the
  next run doesn't see it.

These are honest-reporting's machine-readable twin: the same truth, written where the next
run and the scorecard can use it. Never fabricate a favourable row — a gamed ledger is the
same lie as a shaded report, and it poisons every future decision about which skills to keep.
