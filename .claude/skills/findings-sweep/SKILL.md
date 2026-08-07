---
name: findings-sweep
description: "Scheduled worker that pays down the repo's own documented debt: reads the machine-built index at .agents/findings-index.md (produced by scripts/findings_index.py, which sweeps every findings/follow-up/known-issue section in .agents/ and docs/, TODO/FIXME markers in app/tests/scripts, and open GitLab MR descriptions), takes the top items by impact — security first, cosmetics last — fixes them, has the diff graded by an independent Codex reviewer, and ships one MR via git-commit-chain. Batch size is quota-derived, not fixed: it takes more when the 5h/7d windows are quiet and stands down entirely near the ceiling. Self-healing across runs — a `Findings-Index:` trailer in a merged MR closes the items it fixed, a finding that reappears is reopened as a regression, and a human's false-positive verdict in finding_history.py permanently suppresses it. Use this skill on a schedule (daily timer), when the user says 'work the findings index', 'what debt do we owe', 'pick up the next finding', or asks what outstanding follow-ups the repo has recorded. NOT for auditing code to PRODUCE new findings (security-audit, review-feature) — this one only consumes findings that are already written down. Autonomous: opens at most one MR per run; the MR is the human gate."
---

# Findings Sweep

The gap this closes: this repo documents its debt *unusually well* and then loses it. A
`review-feature` pass ends with "→ **skill-smith**", a `security-audit` closes with
"worth a follow-up ticket for the regex's coverage gap", a spec leaves an open question.
Every one is real, already-triaged work — and none of it is ever read again, because it
sits at line 150 of a report in a directory nobody greps. **The debt is not
undocumented. It is unindexed.** `scripts/findings_index.py` indexes it; this skill works
it off.

Read `.agents/autonomy.md` first. Three constraints from it dominate here:

1. **The MR is the gate.** Run to a finished, verified, pushed MR. Never stop halfway to
   ask permission — a half-fixed finding with no MR is strictly worse than an untouched
   one, because the index then claims progress the tree cannot show.
2. **One MR per run, maximum.** An unattended skill that can open unbounded MRs on a
   timer will eventually open a pile of bad ones. Multiple items ship as one MR, or the
   surplus goes back on the list for tomorrow.
3. **Never weaken a gate to close an item.** Deleting a failing test, loosening an
   assertion, or blanket-suppressing a scanner rule to make a finding "go away" is the
   single most tempting failure mode for this skill specifically — its whole job is
   making a list get shorter. A finding you cannot honestly fix gets `wont-fix` with a
   reason, or stays open. It never gets quietly deleted.

## The division of labour, and why

`scripts/findings_index.py` finds and tracks. This skill decides and fixes. That line is
deliberate and worth keeping: **finding the items is pattern work that costs nothing, so
it runs daily for free; deciding what to do about them is judgement, which costs tokens.**
An index that is free to refresh stays current, and a current worklist is one an agent
can trust without re-deriving it. Do not re-implement the sweep in prose here — if the
index is wrong, fix the script (and add a test), don't work around it.

The script is also the **only** thing that writes item status. Never hand-edit
`.agents/findings-index.md` or `.agents/findings-index.json`; the next sweep overwrites
the markdown wholesale, and a hand-edited JSON will fail `--check`.

## Step 0 — Refresh the index and read the budget

```bash
python3 scripts/findings_index.py sweep --json     # reconcile every source, self-heal
python3 scripts/findings_index.py budget           # how many items today affords
python3 scripts/findings_index.py --check          # store integrity
```

The sweep runs first for a reason: it closes items merged since the last run (via the
`Findings-Index:` trailer), reopens anything that regressed, and drops anything a human
suppressed. **Working from a stale index means re-fixing shipped work.**

Then honour the budget, exactly:

| Budget says | Do |
|---|---|
| `0` | **Stand down.** Write the run report saying why, record nothing, open nothing. This is a success, not a failure. |
| `1`–`4` | Take that many items off the top of the worklist. |

Do not override the budget because the items look small. It is derived from both the 5h
*and* 7d windows precisely because per-item cost is not knowable up front.

## Step 1 — Pick, and verify each pick is still real

```bash
python3 scripts/findings_index.py next --json      # budget-sized, ranked
```

Ranking is `priority → attempts → age`, and the priority signal is **keyword-derived, so
it is crude**. You are expected to overrule it, in both directions:

- Something the script called P4 that is actually a tenant-isolation hole → treat as P0
  and say so in the run report.
- Something it called P0 because a security word appeared in the lead, but the finding is
  really a docs nit → drop it down and pick the next item instead.

Before touching code, **prove the finding still holds.** Open the file at
`code_refs`/`source`, and read the current code. Reports go stale; a finding written six
weeks ago may already be fixed by unrelated work. If it no longer holds:

```bash
python3 scripts/findings_index.py record --id <id> --status gone \
  --why "verified against current code at <path:line>; already fixed by <what>" --by findings-sweep
```

…and take the next item. That verification is not optional overhead — it is the step that
stops this skill "fixing" things that are not broken.

Mark what you are actually going to work on:

```bash
python3 scripts/findings_index.py record --id <id> --status in-progress --by findings-sweep
```

`in-progress` increments `attempts`. At `max_attempts_before_escalation` (3, in
`.agents/findings-index-config.json`) **stop retrying that item** — report it as needing
a human and pick the next. Three identical failed attempts at real cost is a signal, not
bad luck.

## Step 2 — Fix, at the right altitude

Fix items **in the worktree this run already owns**, in one branch. Route by size rather
than doing everything inline:

| The item is | Do |
|---|---|
| A scoped fix in code the finding already names | Fix it here, with a test that fails before and passes after. |
| A real bug with a reproduction | Hand to `fix-bug` (red-then-green repro first) — do not shortcut its discipline. |
| A dependency CVE | Hand to `dependency-update`. |
| A schema change | Hand to `migration-safety` before writing the migration. |
| Missing test coverage | Hand to `test-author`, whose batch is then graded by `test-evaluator`. |
| Stale/incorrect docs | Hand to `docs-truth`. |
| A wrong or rotted skill | Hand to `skill-smith`. |
| Architectural, rippling well past what the finding describes | **Do not start it.** Record `wont-fix` with a reason naming the scope, and say in the report that it needs a human decision. |

That last row is the one to actually respect. A finding one sentence long can describe a
week of refactoring, and an unattended agent is in the worst possible position to make
that call at 3am.

**Every fix carries a test that would have caught the finding.** No test, no fix — a
finding closed without a regression test comes back, and the index will (correctly) log
it as a regression later, which wastes a future run.

## Step 3 — Independent grading, on a separate quota pool

Never grade your own fixes. Route the diff to Codex, read-only, per
`.agents/model-routing.json`:

```bash
python3 scripts/agent_launch.py launch findings-review --scope findings-sweep \
  --prompt-file <prompt> --cwd "$PWD"
python3 scripts/agent_launch.py wait <pane_id> --timeout 900000
```

Ask it specifically: does each diff actually fix the finding it claims, is the test
falsifiable (would it go red if the fix were reverted), and does the change do anything
the finding did not ask for? Scope creep is the characteristic failure of a skill whose
job is closing a list.

Outside Herdr (`HERDR_ENV != 1`) — which is the normal case under systemd — `launch`
raises. Fall back to a subagent grader, and **say in the report which grader ran**. An
ungraded fix is not a blocker (the stage is advisory, so a Codex quota exhaustion cannot
stall an unattended run), but it must be disclosed, never silently skipped.

If the grader finds a real problem, fix it and re-grade. Cap at **2 rounds**, then ship
what is defensible and record the rest as open — the same cap
`herdr-multi-agent-collab` uses, for the same reason: rounds 3+ reliably produce
diminishing, argumentative churn.

## Step 4 — One MR, with the trailer that closes the loop

Hand off to `git-commit-chain` (or `merge-request`) to organise commits, push, and open
the MR ready for review.

**The MR description MUST carry the trailer, on its own line:**

```
Findings-Index: 09d144c1, 1ced5f93
```

This is not decoration — it is the entire feedback path. The next sweep reads that
trailer out of the merged MR and closes those items. **No trailer means the work merges
and the index never learns**, so the items sit `mr-open` forever and eventually get
picked up again. The script deliberately refuses to guess closure from title similarity,
because a wrong auto-close silently drops real work off the list.

The description should also, per finding: what was owed, where it was documented, what
changed, and which test proves it.

Then record:

```bash
python3 scripts/findings_index.py record --id <id> --status mr-open --mr '!<N>' --by findings-sweep
```

Never `done` by hand — `done` is what the *next sweep* concludes when it sees the merged
trailer. Setting it yourself asserts a merge that has not happened, and this skill is
never authorised to merge (`.agents/autonomy.md`).

## Step 5 — Run report, and tune the ladder honestly

Write `.agents/reports/findings-sweep/<date>.md`:

```markdown
# FINDINGS SWEEP: <date>
budget: <n> items (<why, quoted from the budget line>)
index: <total> tracked, <open> open  (<new> new, <closed> closed by merge, <gone>, <regressed>)
picked: <id> <title> [P0/security]
grader: codex/gpt-5.6-sol (high) | subagent fallback — <which, and why>
verdict: shipped | partial | stood-down | blocked
mr: !<N> | none (<why>)

## Per item
- `<id>` — <what was owed> → <what changed> → <test that proves it>

## Left open, and why
- `<id>` — <blocker, in one honest sentence>

## Quota observed
5h <before>% → <after>%, 7d <before>% → <after>%, for <n> item(s)
```

That last block is what makes the batch size self-correcting, and it is the founder's
explicit ask: *"look at usage for 2 items and frequency — if we can afford to pick up
more, the skill should be updated to reflect this."* So:

- Record the real cost per item every run. One observation is noise; **a trend across
  three or more runs is evidence.**
- If items consistently cost far less than the rung assumed, propose widening the ladder
  in `.agents/findings-index-config.json`. If a run blew through its window mid-item,
  propose tightening it.
- Change the **config, never the script** — the ladder is data precisely so tuning it
  needs no code change and no test rewrite.
- Ladder changes ride along in the same MR, with the observed numbers quoted as the
  justification. **Never tune it from a single run**, and never widen it in the same run
  that hit the ceiling.

## Honesty rules

- **A stood-down run is a good run.** Report `verdict: stood-down` and stop. Do not
  half-start an item to look productive.
- **`gone` requires verification against current code**, not an assumption that time has
  passed. Closing a live finding as stale is the quiet failure that loses real work.
- **Never write suppressions.** `suppressed` comes only from a human verdict already
  recorded in `finding_history.py`. You may *recommend* accepted-risk in the report; only
  a human grants it. This is `.agents/autonomy.md`, not a preference.
- **Report the grader you actually used**, including the fallback case.
- **If the index and the code disagree, the code wins** — and the index is what gets
  corrected.

## Handoffs

- **Consumes:** `.agents/findings-index.md` ← `scripts/findings_index.py` ← every skill
  that writes a report under `.agents/reports/`.
- **Calls:** `fix-bug`, `test-author`, `docs-truth`, `dependency-update`,
  `migration-safety`, `skill-smith`, `git-commit-chain` / `merge-request`.
- **Graded by:** `findings-review` (Codex, read-only) per `.agents/model-routing.json`.
- **Invoked by:** `findings-sweep.timer` (daily), or a human saying "work the findings
  index".
