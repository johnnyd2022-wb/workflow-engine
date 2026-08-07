---
name: herdr-multi-agent-collab
description: "Two-agent collaboration protocol for Herdr where Claude (The Architect) and Codex (The Breaker) work the same repo from side-by-side panes. Use this skill whenever you are running inside Herdr (HERDR_ENV=1) and need to hand work to the other agent, request an adversarial review, report a failing test back to the builder, wait on the other agent's status, read its output, or coordinate file edits between panes. Also trigger when the user mentions 'hand this to Codex', 'get Claude to fix it', 'cross-pane review', 'the other agent', or any Architect/Breaker handoff."
---

# Herdr Multi-Agent Collaboration Protocol

You are one of two agents sharing a repo inside Herdr, a terminal agent multiplexer. The other agent is your collaborator, not your subordinate. This skill defines who does what, how you talk to each other, and how you avoid stepping on each other's edits.

## 0. Preflight (do this before any herdr command)

1. Confirm you are inside a Herdr-managed pane:

```bash
test "${HERDR_ENV:-}" = 1 || echo "NOT IN HERDR"
```

If the check fails, tell the user you are not running inside Herdr and stop. Do not try to control a Herdr session from outside it.

2. Learn the installed CLI before trusting any syntax in this file. Herdr is pre-1.0 and moves fast, so the binary is the authority:

```bash
herdr --help
herdr pane        # prints the pane command group
herdr wait        # prints the wait command group
```

Never run bare `herdr` for discovery (it launches the TUI), and never probe a mutating command by omitting arguments (`herdr workspace create` runs with defaults).

3. Know your own address. Herdr injects it into every managed pane:

```bash
printf '%s\n' "$HERDR_WORKSPACE_ID" "$HERDR_TAB_ID" "$HERDR_PANE_ID"
```

Pane IDs look like `w1:p2` but are opaque. Always parse IDs from JSON responses. Never guess an ID from sidebar order, display numbers, or the examples in this file.

## 1. Roles: play to strengths

**Claude, The Architect.** Owns design and coherence: multi-file refactors, dependency and interface changes, file/module architecture, naming, migrations, and writing the fix when something breaks. Claude carries the most context, so anything that requires understanding how the whole system fits together goes to Claude.

**Codex, The Breaker.** Owns adversarial verification: running the test suite, tracing edge cases, fuzzing inputs, shell pipelines, regex torture tests, sandbox execution of risky commands, and reviewing diffs with the explicit goal of breaking them. Codex should assume the Architect's code is guilty until proven innocent.

Work out which role you are from your own identity (you know whether you are Claude or Codex). If the user has assigned roles differently in this session, the user's assignment wins.

Division of labor rules:

- The Architect does not merge or declare work finished until the Breaker has run it.
- The Breaker does not refactor. It reports findings with file, line, repro command, and observed vs expected behavior, then hands back.
- When the handoff `ask` is to grade tests (the **test-evaluator** checklist — falsifiability probes, assertion-diff review, tautology hunt), the Breaker pane is the natural executor: same contract as running that skill in a subagent, different engine. It returns the same `valid | weakened | gamed | inconclusive` verdict via the handoff file, and the Architect's ship stays blocked on `valid`.
- Either agent can do small self-contained work solo. Cross-pane handoffs are for changes worth verifying, not for every keystroke.

## 2. Finding your partner

List panes in your workspace and identify the partner by its `agent` field, not by position:

```bash
herdr pane list --workspace "$HERDR_WORKSPACE_ID"
```

Pane records include `agent` (e.g. `claude`, `codex`), `agent_status` (`idle`, `working`, `blocked`, `done`, `unknown`), and any label. Pick the pane whose `agent` matches your partner and save its `pane_id` for the session. If it has no label yet, give it one so humans can follow along:

```bash
herdr pane rename <partner-pane-id> "breaker-codex"
```

If no partner pane exists: ask the user when they're there; **when unattended, just create it** — a split pane is local and reversible, and blocking an autonomous run to ask permission for one defeats the purpose (`.agents/autonomy.md`). Either way, split without stealing focus, launch the agent's normal interactive executable, and wait for it to reach its prompt:

```bash
herdr pane split --current --direction right --no-focus
# read result.pane.pane_id from the JSON
herdr pane rename <new-pane-id> "breaker-codex"
herdr pane run <new-pane-id> "codex"
herdr wait agent-status <new-pane-id> --status idle --timeout 30000
```

Do not pass the task as an argv prompt and do not add non-interactive flags. Launch the plain TUI, wait for `idle`, then send the task.

## 3. Talking to each other

### 3.1 Never interrupt a working agent

`herdr pane run <id> "text"` types the text into the target pane and presses Enter. Sending it while the partner is `working` injects into an active session and can derail or corrupt its turn. Always gate on status first:

```bash
herdr pane get <partner-pane-id>          # inspect current state
herdr wait agent-status <partner-pane-id> --status idle --timeout 120000
herdr pane run <partner-pane-id> "<your message>"
```

Treat `idle` and `done` as equivalent for "safe to send" (they are the same underlying state; `done` just means the result has not been seen yet). A `blocked` partner is waiting on input, usually a permission prompt. Read its pane to see what it needs; if it is a prompt only the human should answer, escalate (section 6) rather than answering on their behalf.

If a wait times out, do not fire blindly. Run `herdr pane get` and `herdr pane read` to see what is actually happening, then decide.

### 3.2 The handoff file is the source of truth

Pane text is a lossy channel: it scrolls, wraps, and truncates. Anything longer than two sentences goes in a handoff file on disk, and the pane message just points at it.

Use `.herdr-collab/` at the repo root (add it to `.gitignore`):

- `.herdr-collab/handoff.md` is the current work order, overwritten each handoff
- `.herdr-collab/log.md` is append-only history, one dated entry per handoff, so either agent can reconstruct what has been tried

Handoff file format. Keep it exact so the other agent can parse it at a glance:

```markdown
# HANDOFF
from: architect-claude
to: breaker-codex
round: 1
task: Stress-test the token refresh changes
files_touched:
  - src/auth/token.ts
  - src/auth/session.ts
context: Replaced expiry check with clock-skew-tolerant window (see commit a1b2c3d).
ask: Run the auth suite, then attack the +-30s skew boundary and concurrent refresh.
done_when: Suite passes and you have tried at least 3 adversarial cases.
```

The pane message is then short:

```bash
herdr pane run <partner-pane-id> "HANDOFF ready in .herdr-collab/handoff.md. Read it, do the work, update the file with your findings, then reply DONE in this pane."
```

### 3.3 Reading your partner

When you need the partner's transcript or command output:

```bash
herdr pane read <partner-pane-id> --source recent-unwrapped --lines 150
```

`recent-unwrapped` joins soft-wrapped lines and is right for logs and transcripts. Use `--source visible` only for "what is on screen right now", and `--format ansi` only when color itself is evidence (e.g. a test runner's red/green). But prefer the handoff file over screen scraping whenever the partner has written one.

## 4. Workflow A: Build then Break (Architect to Breaker)

Use after any change worth verifying: new feature, refactor, dependency bump, bug fix.

1. **Land the work.** Save every file. Commit to a working branch (or at minimum ensure the tree is clean enough that `git diff` shows exactly your change). The Breaker verifies what is on disk, not what is in your head.
2. **Write the handoff.** Fill `.herdr-collab/handoff.md` per the format above. List every touched file, state what changed and why, and give the Breaker a concrete `ask` (which suite to run, which boundaries to attack) plus a `done_when`.
3. **Gate and send.** Wait for the Breaker to be `idle` or `done`, then `pane run` the short pointer message.
4. **Get out of the blast radius.** While the Breaker runs, do not edit any file in `files_touched`. Work on something disjoint or stand by. Then wait:

```bash
herdr wait agent-status <breaker-pane-id> --status working --timeout 30000
herdr wait agent-status <breaker-pane-id> --status done --timeout 600000
```

(If the human is watching that tab, completion reports `idle` instead of `done`; accept either.)

5. **Collect findings.** Read the updated handoff file first, the pane transcript second. Triage: fix real failures yourself (that is Architect work), push back with reasoning on findings you believe are false positives, and record the round in `.herdr-collab/log.md`.

## 5. Workflow B: Break then Fix (Breaker to Architect)

Use when a test fails, a build breaks, or an adversarial case lands.

1. **Pin the evidence.** Before handing off, reduce the failure to the smallest repro you can and capture it: exact command, file and line, stack trace, observed vs expected. Vague reports waste a round trip.
2. **Write the handoff.** Same format, `from: breaker-codex`. Put the repro command in `ask` so the Architect can confirm the failure in one step, and paste the trace (or a path to a saved log) in `context`.
3. **Gate and send** exactly as in Workflow A, with roles flipped.
4. **Verify the fix, don't trust it.** When the Architect replies DONE, pull the change, re-run the original repro, then widen: run the surrounding suite and probe adjacent inputs, since fixes often move bugs instead of killing them. Only then mark the round closed in the log.

## 6. Coordination and safety rules

**File ownership.** One writer per file at a time. `files_touched` in the current handoff is the lock list: the agent named in `to:` owns those files until it hands back; the other agent must not edit them, including via `sed`, formatters, or "quick fixes". If you genuinely need a locked file, message the owner and wait for an explicit release.

This is the pane-level form of a rule that governs every execution mode: **one writer per worktree** (`.agents/verification-chain.md` §6). Panes, tabs, and in-process subagents all share one checkout, and none of them can see another's uncommitted edits. Two writers converging on the same file fail *silently* — both report success and the last write wins. When you have no handoff file to act as the lock list (chain stages don't), the substitute is the one in that section: never run two write-access stages at once.

**Git is the transport for code.** Share code through the working tree and commits, never by pasting code into the partner's pane. Pane messages carry pointers and short status, nothing else.

**Focus discipline.** Always use `--no-focus` on splits and never move the user's focus. Use `--current` or an explicit pane ID for every pane command; omitting the target can hit whatever pane the human has focused.

**Ask before building topology.** Do not create workspaces, tabs, or worktrees unless the user asked for that structure. Never close panes, tabs, or sessions you did not create. Never run `herdr server stop` or kill the Herdr process; that takes down both agents and the user's session.

**Two-round circuit breaker.** Count rounds in the handoff file. If the same bug or disputed finding survives two full round trips (build-break-fix-break), stop. Write a summary of what was tried and why it failed into `.herdr-collab/log.md`, send the partner a short STOP message so it stands down too, and surface the impasse to the human in your own pane with your best two or three hypotheses. A blocked status plus a clear summary beats an infinite loop of confident wrong fixes.

**Three-round session cap — a blanket limit, not just for a stuck disagreement.** The rule above only fires when the *same* finding keeps recurring; it never triggers when every round turns up something new and real, which is the expensive case in practice — the MR-conflict-resolver build went 6 full round trips (10 findings, then 6, 7, 3, 2, 1, each genuinely new and real) before a clean PASS, burning far more usage than the fixes themselves needed to, because nothing capped the *count* of rounds, only repeats within one. Cap any review session at **3 full round trips**, full stop, regardless of whether round 3's findings are new or old:

- **Round 1 is where the Breaker should do its most thorough pass, not its first pass.** Read the whole diff adversarially in one sitting and report everything real you find — races, data loss, security, correctness — ranked by actual impact. Trickling out one or two findings per round across many rounds costs a full round trip's overhead (both agents' context, a fix cycle, a re-verification pass) per finding instead of amortizing that cost across a single batch. If round 1 was thorough, rounds 2-3 should be short — closing what round 1 found plus whatever a genuine fresh read turns up, not a second full pass reserved on purpose.
- **By the end of round 3, stop — whatever real findings remain get documented, not chased.** Write them into `.herdr-collab/log.md` as a ranked list (what's unresolved, why it matters, and its actual severity) rather than opening a round 4. Whichever agent's front door reaches `merge-request` next folds that list into the MR description's "Out of scope" / known-limitations section — the human reviewing the MR is the backstop for anything judged not worth a fourth round, exactly like any other explicit, reviewable trade-off `.agents/autonomy.md` already expects (see its "would a reviewer reading the MR see the assumption you made" test). A capped review that tells the human what it didn't chase down is honest; one that just stops silently is not.
- This is a hard cap on round *count*, independent of the two-round same-finding breaker above — even a session where round 3 still turns up something genuinely new stops there. Three rounds of real findings is a sign the diff needed a fourth round of engineering, not a sign the review process should keep running; escalate that read to the human rather than funding a longer review loop.

**Disagree out loud.** If you think your partner's finding or fix is wrong, say so in the handoff file with reasoning and evidence. Do not silently re-do each other's work; dueling edits to the same files is how repos get corrupted.

## 7. Tabs mode: one tab per stage, one engine per stage

Sections 1-6 describe **two** agents in side-by-side panes. Tabs mode is the same protocol
scaled out: each verification stage gets its own labelled Herdr tab running the engine
`.agents/model-routing.json` assigns it. preflight reports `verification_mode: herdr-tabs`
when this is available (inside Herdr, with the `herdr` CLI on PATH).

Why it exists: a stage launched as a separate process can be given **its own model,
reasoning effort, and filesystem permissions**. In-process subagents all inherit the
orchestrator's model, so a mechanical stage costs the same as a hard one. Tabs are also
watchable — the founder can scroll back through what each stage actually did instead of
seeing only a verdict line.

### 7.1 Never hand-build the command

`scripts/agent_launch.py` owns the flag construction. Routing changes in the JSON, not here:

```bash
python scripts/agent_launch.py plan                    # what runs where, and on whose quota
python scripts/agent_launch.py --check                 # routing is coherent (CI runs this)

# write the stage prompt to a file, then launch it into its own tab
python scripts/agent_launch.py launch security-audit \
    --scope inventory --prompt-file .agents/reports/inventory/security-audit.prompt.md
# -> {"pane_id": "w1:pK", "tab_id": "w1:tK", "engine": "claude", "model": "sonnet", ...}

python scripts/agent_launch.py wait w1:pK --timeout 900000
```

Read the **report file** the stage wrote, not the pane. Pane text scrolls, wraps, and
truncates; §3.2's rule applies unchanged.

### 7.2 The two gotchas that will cost you a run

**`herdr wait output --match` matches the echoed command line itself.** The command you
typed is the first thing in the pane, so a match on any word in it returns instantly and
you conclude the stage finished before it started. Gate on `agent-status`, which is what
`agent_launch.py wait` does.

**`herdr agent start` without `--tab` splits into the current tab.** It does not open a new
one. `agent_launch.py` always `tab create`s first and passes the returned ID — never guess
a tab or pane ID from sidebar order, per §0.

### 7.3 Permissions encode the fresh-eyes principle

A grader that can edit the code it grades is not an independent grader. The routing table
gives every grader `access: read`, which becomes `--permission-mode auto` (Claude) or
`--sandbox read-only` (Codex), and `agent_launch.py --check` **fails** if a grader is ever
given write access. The principle is enforced by the launcher, not by the grader's goodwill.

### 7.4 Blocking vs advisory

`blocking: true` stages hold the chain: their verdict must be green before the next stage.
`blocking: false` stages log findings and let the chain continue, surfacing what they found
in the MR description. `build-review` is advisory on purpose — a Codex quota exhaustion
should not strand an unattended overnight run, and its findings still reach the human at
the MR gate.

### 7.5 Quota, not cost, is the constraint

Tab agents draw on the same subscription as the session that spawned them. Eight tabs in
parallel do not buy capacity; they burn the window eight times faster. Keep the chain
**serial**, parallelising only the groups declared in `.agents/model-routing.json` →
`concurrency.parallel_groups` (today: `security-audit ∥ e2e-playwright`) — quota is only
half the reason, the other half being that tabs share one worktree and may not contain two
writers (`.agents/verification-chain.md` §6). Codex stages are the exception worth leaning on:
they spend a *different* pool, so routing graders there genuinely relieves pressure rather
than moving it.

## 8. Quick reference

```bash
# who am I
printf '%s\n' "$HERDR_PANE_ID"

# who else is here
herdr pane list --workspace "$HERDR_WORKSPACE_ID"

# partner state
herdr pane get <pane-id>

# safe send (gate, then message)
herdr wait agent-status <pane-id> --status idle --timeout 120000
herdr pane run <pane-id> "HANDOFF ready in .herdr-collab/handoff.md"

# wait for completion (accept idle or done)
herdr wait agent-status <pane-id> --status done --timeout 600000

# read transcript
herdr pane read <pane-id> --source recent-unwrapped --lines 150

# wait for specific output from a plain command pane
herdr wait output <pane-id> --match "test result" --timeout 120000
```

Statuses: `idle` (waiting, result seen), `done` (finished, result unseen), `working`, `blocked` (needs input), `unknown` (no detected agent yet). A wait timeout exits with status 1; inspect before retrying.
