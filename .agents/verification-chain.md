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

## 3. Graders are read-only

Every grader carries `access: read`. `agent_launch.py --check` **fails** if a grader is ever
given write access, and CI runs that check.

This is the fresh-eyes principle: a grader must not edit the code or tests it judges.
Findings come back to the orchestrator to fix. A grader that could "just fix it" is how a
weakened test gets written by the agent that was supposed to catch weakened tests.

**How strongly that is enforced depends on the mode — know which one you are in:**

| Mode | What stops a grader writing |
|---|---|
| `herdr-tabs`, Codex stage | `--sandbox read-only`. A real syscall sandbox; the write fails |
| `herdr-tabs`, Claude stage | `--permission-mode auto` **plus** `--disallowed-tools Edit Write NotebookEdit`. `auto` alone auto-*approves* — it is not read-only. The denylist withholds the edit tools, but graders keep Bash (they run semgrep, pytest, git), so a stage that shells out can still write |
| `herdr-adversarial` | Nothing mechanical. The Breaker pane is a plain interactive `codex`, launched without a sandbox flag |
| `subagents` | Nothing mechanical. In-process subagents inherit the orchestrator's permissions — `access` is not consulted at all on this path |

So `access: read` is a hard boundary only for Codex tabs. Everywhere else it is a rule the
stage is *told*, which means **the orchestrator carries the guarantee, not the launcher**:
put the read-only line from §5 in every `access: read` stage prompt, and never spawn a
grader alongside a writer (§6). Do not let "graders are read-only by construction" become a
reason to skip that — outside Codex tabs, construction is not doing the work.

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

**Append this to every `access: read` stage's prompt** — it is the only thing enforcing the
boundary outside Codex tabs (§3), and it costs one line:

```
You are read-only for this stage. Do not edit, create, or delete any file under app/,
tests/, or scripts/ — not with an edit tool, not via a shell command, not a "quick fix"
on the way past. Report findings with file:line and hand them back; the orchestrator
patches. Your report file is the one thing you write.
```

**And this to every stage that runs in a declared parallel group (§6):**

```
Another stage is running against this same worktree right now. Confine your writes to
the files this task names. Do not reformat, tidy, or opportunistically fix anything
outside them, and do not run a formatter or codemod across the tree.
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

## 6. Concurrency: one writer per worktree

Two independent reasons to keep the chain serial. The first is a budget; the second is a
correctness rule that does not bend.

**Quota.** Stage agents draw on the **same subscription quota** as the orchestrator, so
parallelism buys no capacity — it burns the window faster. Codex stages are the exception
worth leaning on: they spend a different pool.

**One writer per worktree.** Every stage — tab, pane, or in-process subagent — operates on
**the same checkout**. Two `access: write` stages in the same turn edit the same files with
no lock, no coordination, and no way to see each other. The failure is silent: both stages
report success, whichever wrote last wins, and if they happened to fix the same thing you
get duplicated or half-overwritten edits that still pass tests. *This has already happened
once* — two subagents converged on overlapping fixes to the same files. It was harmless only
by luck.

So:

- **The allowed parallel groups are declared as data**, in `.agents/model-routing.json` →
  `concurrency.parallel_groups`, and `agent_launch.py --check` fails CI if any group holds
  more than one write-access stage. Today that is exactly one group:
  `security-audit ∥ e2e-playwright` — safe because security-audit is `access: read`.
- **Never parallelise a pair the table does not declare**, and never widen a group by
  reasoning about it in prose. Change the JSON, let the checker rule on it.
- **A read stage beside a write stage is fine.** A read stage beside another read stage is
  fine. Two writers never are — not even "on different files", because neither agent can
  prove that in advance and both are free to widen their own blast radius mid-run.
- **`patched` after parallel stages means re-baseline.** When a group finishes, `git status`
  before the next stage: a stage that patched changed the tree the next stage assumes.

For the cross-pane case the same rule is stated as file ownership in
`herdr-multi-agent-collab` §6 — `files_touched` is the lock list, one writer at a time.
That skill governs two *human-visible panes*; this section governs the chain's stages, in
every mode. They are the same rule about the same worktree.

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
