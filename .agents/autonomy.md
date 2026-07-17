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
- Run the full local verification chain: pytest, ruff, semgrep, gitleaks, pip-audit,
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
- **Send external communications.** No email, no Slack, no posting, no webhooks to third
  parties. Founder-ops skills that draft comms draft only — that rule is theirs and
  unchanged by this policy.
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

## Honest reporting

The whole policy rests on reports being true. `clean` means it was checked; `skipped`
means say so and why; a failure that was worked around is a failure that gets reported.
An agent that shades a report to look successful has removed the human's only view into
an unwatched loop — which is worse than the bug it hid.
