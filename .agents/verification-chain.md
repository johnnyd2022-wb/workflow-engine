# The verification chain

The single execution contract shared by every code front door — **new-feature**,
**fix-bug**, **review-feature**, and anything `/entrypoint` routes to code work. Each front
door owns *what* it builds; this file owns *how* the work gets verified, on which engine,
and what may block a ship.

The rule that makes it worth having: **a code change is a code change**. A bug fix that
skips the tenant-isolation audit because it "felt small" ships the same class of defect a
feature would have been stopped for. Front doors differ in step 1-2 and nowhere else.

## 1. Execution mode

`preflight` decides this once and every front door reads it — never re-probe:

| `verification_mode` | How stages run |
|---|---|
| `herdr-tabs` (preferred) | One labelled Herdr tab per stage via `scripts/agent_launch.py`, each on its own engine/model/effort |
| `herdr-adversarial` | Single Codex partner pane runs stages per herdr-multi-agent-collab Workflow A |
| `subagents` | In-process subagents, all inheriting the orchestrator's model |

`grader_engine` tells you whether graders get an independent engine (`codex`) or fall back
to `claude`. On a fallback, say so in the MR description: the review happened, but not with
independent eyes.

**The chain, its order, and its verdicts are identical in all three modes.** Only execution
differs. A skill that behaves differently by mode is a bug in that skill.

## 2. Model routing

`.agents/model-routing.json` is the single source of truth; `scripts/agent_launch.py` turns
it into flags so a skill cannot drift from it. Never pick a model inline.

```bash
python scripts/agent_launch.py plan                     # the live table
python scripts/agent_launch.py launch <stage> --scope <slug> --prompt-file <path>
python scripts/agent_launch.py wait <pane_id> --timeout 900000
```

The shape, and why:

- **Opus 5 appears exactly once** — spec authoring. An ambiguous spec is the most expensive
  error in the system because every downstream gate can pass while the result is wrong.
- **Sonnet 5 runs the build and every verify stage.** These are tool-driven: semgrep finds
  the vulns, `test_perf_budgets.py` measures the budgets, pytest runs the tests. The agent
  orchestrates tools and grades output against a written rubric.
- **Codex runs every grader** — `spec-critic`, `test-evaluator`, `build-review`,
  `security-tenant-audit`. Fresh eyes, and on dual $20 plans, a separate quota pool.
- **Effort is the second dial.** Stepping `xhigh` → `medium` often saves more than changing
  model, at less capability cost on rubric-following work. `gpt-5.6-sol` defaults to `low`,
  so an unset effort ships a shallow review that still looks like a review.

## 3. Graders are read-only, by construction

Every grader carries `access: read`, which becomes `--permission-mode auto` (Claude) or
`--sandbox read-only` (Codex). `agent_launch.py --check` **fails** if a grader is ever given
write access, and CI runs that check.

This is the fresh-eyes principle enforced at the permission layer instead of trusted to the
grader's restraint: a grader physically cannot edit the code or tests it judges. Findings
come back to the orchestrator to fix. A grader that could "just fix it" is how a weakened
test gets written by the agent that was supposed to catch weakened tests.

## 4. Blocking vs advisory

`blocking: true` stages hold the chain — the verdict must be green before the next stage.
`blocking: false` stages log findings, let the chain continue, and surface what they found
in the MR description.

Only `build-review` is advisory, deliberately: a Codex quota exhaustion must not strand an
unattended overnight run, and its findings still reach the human at the MR gate.

## 5. Stage prompt

Whatever the mode, each stage gets this and nothing else — the spec and the skill, not the
orchestrator's reasoning or excuses:

```
Read and follow the skill at: <absolute path to SKILL.md>
Scope: <slug>
Spec: .agents/specs/<slug>.md          (or: the repro test, for a fix)
Branch: <branch>
Preflight: <the decisions block>
Task: <one line>
Write your report to .agents/reports/<slug>/<stage>.md and end your reply with
exactly one line: VERDICT: clean | patched | findings-open
```

Read the **report file**, not the pane transcript — pane text scrolls, wraps, and truncates.

**A `--sandbox read-only` / `access: "read"` grader cannot write that file itself** — verified
live: Codex's read-only sandbox rejects the write with `patch rejected: writing is blocked
by read-only sandbox`, and a correctly-behaving grader will recognize this and decline to
route around it (creating one via some other writable channel would be the same integrity
breach as giving it write access directly). This is not a bug to fix by loosening the
sandbox — graders are read-only *by construction* (§3) precisely so they cannot edit what
they grade, and a report file is not exempt from that boundary. The orchestrator — which
does have write access — is responsible for capturing the grader's verbatim final message
and writing the report file on its behalf. This is the same "read the report file, not the
transcript" rule from the other direction: for a read-only stage, the orchestrator's
transcript-to-file transcription *is* how the file comes to exist at all.

## 6. Concurrency

Stage agents draw on the **same subscription quota** as the orchestrator, so parallelism
buys no capacity — it burns the window faster. Run serially except the one pair the chain
declares independent (`security-audit ∥ e2e-playwright`). Codex stages are the exception
worth leaning on: they spend a different pool.

## 7. Circuit breaker

A finding that survives **two full patch rounds** stops the chain. Write what was tried and
the best two or three hypotheses, then do both: push a `Draft:` MR via merge-request with
the impasse and the failing stage's report linked, and fire a `PushNotification`. A third
round on the same wall usually means the spec or the design is wrong, which is a human
decision (`.agents/autonomy.md` → Escalation).

## 8. Record the run

Append one metrics row per stage that ran, so the scorecard can see the chain's shape:

```bash
python scripts/skill_metrics.py record --skill <stage> --run-type chained \
    --scope <slug> --verdict <clean|patched|findings-open> --findings <n> --ref <branch>
```

The MR's eventual merge/close is recorded later by `skill_metrics.py sweep`, not now.
