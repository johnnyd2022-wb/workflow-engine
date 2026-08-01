---
name: entrypoint
description: "Top-level router across every registered skill in this repo — both the biz-e code suite (new-feature, review-feature, fix-bug, and their specialists) and the founder-ops pack (business-operator and its specialists). Self-updating on two axes: syncs a cached category index (skill-index.md) against the live .claude/skills/ roster, AND checks the wiring graph (scripts/skill_graph.py) so a skill nothing routes to gets caught instead of silently never firing. Also runs preflight once and hands its report to the front door, and — for code front doors — dispatches each into its own fresh worktree and herdr workspace cut from origin/main, so parallel code tasks don't collide. Use this when the user doesn't know which skill to reach for: 'which skill should I use', 'help', 'where do I start', 'I want to build/fix/ship X' with no named skill, or any request that could plausibly map to more than one skill. Not for requests that already clearly name their skill (e.g. 'run sales-manager') — invoke that skill directly instead."
---

# Entrypoint

One door in front of every registered skill in this repo — the engineering suite and the
founder-ops pack (Whistlebird / Biz-E), symlinked together into `.claude/skills/`. Nobody
should have to know the roster to get started. Your job is triage: sync the index, read
the request (or interview for one), name the one skill (or short chain) that answers it,
gather the context that skill will need, and invoke it — don't just print a menu and stop.

This is a router, not a decision-maker. It does not do the work of the skill it routes
to, and it does not out-rank `business-operator` on business *prioritization* calls
("what should I work on this week" is business-operator's call once you're in the
founder-ops world — entrypoint's job ends at getting you there).

The routing tables live in **`skill-index.md`** (same directory as this file) — a cached,
categorized snapshot of the roster. This file defines the procedure; the index holds the
map. Never route from memory of the index; read it after syncing it.

## Step 0: Sync the index (every run, before anything else)

The index is a cache and caches drift. Skills live in more than one place under
`.claude/`, so the scan has four tiers — three about *existence*, one about *wiring*:

```bash
# Tiers 1 + 4 in one deterministic command (~0.2s): fingerprint drift, unindexed
# skills, orphans, stale roots. Don't hand-roll a sed over the fingerprint block —
# skill-index.md has several code fences and a naive match reads the wrong one.
python3 scripts/skill_graph.py --check

# 2. Founder-ops source dir — anything here NOT symlinked into .claude/skills/
#    exists but is unregistered (invisible to the harness)
comm -23 <(ls -1 .claude/agents/skills/ | sort) <(ls -1 .claude/skills/ | sort)

# 3. Stray SKILL.md anywhere else under .claude/ — a skill someone parked outside
#    both known homes
find .claude -name SKILL.md \
  -not -path ".claude/skills/*" \
  -not -path ".claude/agents/skills/*" \
  -not -path ".claude/takeaway/*"
```

`skill_graph.py --check` exits 0 when the roster is clean and 1 with a report when it
isn't, covering: `fingerprint_drift` (roster vs index), `unindexed`, `orphans`,
`unknown_roots`. Tiers 2 and 3 stay shell because they look *outside* `.claude/skills/`,
which the graph doesn't see.

**Tier 4 is the one that catches the failure the other three can't see.** A skill can be
present, registered, and indexed, and still never fire, because nothing routes to it —
and nothing errors when that's true. That is not hypothetical: `suite-warden` and
`docs-truth` shipped as orphans and were only caught because someone asked the right
question by hand. `scripts/skill_graph.py` walks every SKILL.md, builds the reference
graph, and reports skills with no inbound edge that aren't declared roots. Existence is
cheap to verify; reachability is what decides whether the skill was worth writing.

**`.claude/takeaway/` is always excluded**: it holds export copies of skills for
sharing outside this repo (including the Codex-side `herdr-multi-agent-collab-breaker`,
which belongs to the Codex agent, not this registry). Never index or register anything
from there; duplicates in takeaway are expected, not drift.

Act on each tier:

- **Tier 2 non-empty** (founder-ops skill exists but isn't registered) → register it by
  symlinking, matching the existing pattern, then treat it as a new skill in the index
  repair below:

  ```bash
  ln -s ../agents/skills/<name> .claude/skills/<name>
  ```

- **Tier 3 non-empty** (stray skill outside both homes) → do NOT auto-register or
  auto-index it; you can't tell a real skill from a draft or a copy. Report what you
  found and where, and hand it to **skill-smith** — it owns whether a SKILL.md meets the
  house standard and belongs in the roster. Interactively, ask the user; unattended,
  leave skill-smith's finding in the report rather than registering something that might
  be a draft.

- **Tier 4 non-zero** (`--check` exited 1) → the roster has a reachability problem:
  - `orphans` — nothing routes to it. **Do not fix the wiring yourself**: where a wire
    belongs is a design judgment (does a test failure go to suite-warden or fix-bug?),
    and that is **skill-smith**'s call. Report the orphan, route it there, and carry on
    routing the user's actual ask — a wiring gap is not a reason to refuse their request.
  - `unindexed` — you fix this one; it's the index repair below.
  - `unknown_roots` — a declared root in `scripts/skill_graph.py`'s `ROOTS` no longer
    exists. Prune it (a stale root silently exempts a name from orphan detection).

  A new skill will *always* be an orphan for one run — it's added before it's wired. Say
  so plainly rather than treating it as breakage; the point is that it can't stay that
  way unnoticed.

Then compare the tier-1 output to the `## Roster fingerprint` block in
`.claude/skills/entrypoint/skill-index.md`.

- **Match** (and tiers 2–3 empty) → the index is fresh. Proceed to Step 1.
- **Drift** (skills added, removed, or renamed) → repair the index before routing:
  1. For each **new** name, read its `SKILL.md` frontmatter (`name:` + `description:` —
     the first ~10 lines are enough) and assign it to the existing category whose other
     members it most resembles. If none fits, add a new category section rather than
     forcing a bad match.
  2. For each **removed** name, delete its row(s) and, if that empties a category,
     the category.
  3. Rewrite the fingerprint block with the new sorted listing, update `last_synced`
     to today and `skill_count` to the new count.
  4. Tell the user in one line what changed ("index updated: +deploy-verifier,
     −old-skill") — then continue routing. The sync must never become the errand;
     it's a toll booth, not the destination.

A one-row description is enough for a new skill's index entry — the "ask sounds like"
phrasing can be distilled from its description's trigger sentences.

## Step 1: Get a routable ask

If the user gave a real ask ("the Xero sync is throwing 500s"), skip straight to Step 2.

If invoked bare, or with something as open as "help" / "where do I start": don't ask an
open-ended "what are you trying to do?". Present the category menu — one line per
category, drawn from the index's category headings — as a **selection** (use
AskUserQuestion where available: one question for the category, and if it's code work, a
follow-up selection for build / review / fix / ship, since those front doors genuinely
need that much to pick). Current categories:

1. **Build/fix/ship code on this repo** — features, bugs, reviews, deploys, CI, security, dependencies
2. **Run the businesses day-to-day (Whistlebird / Biz-E)** — priorities, sales, marketing, finance, planning → `business-operator`
3. **Whistlebird-specific** — distillery strategy, compliance/licensing, duty manager study
4. **Biz-E-specific** — product roadmap, architecture review, releases, customer onboarding
5. **Claude Code / harness tools** — config, keybindings, code review, scheduling

Map whatever comes back onto the index:
- A category number or name → jump to that category's front door.
- A description of actual work → match directly against the index tables.
- Still nothing usable ("I don't know") → for code work default to `repo-conventions`
  or ask what area of the app; for business work `business-operator` is built for
  exactly this.

**Then collect the handoff context.** Before invoking, ask (as selections/short
questions, not an essay prompt) for whatever the target skill's first step would
otherwise have to re-ask: for `new-feature` a one-line feature statement; for `fix-bug`
the symptom, where it was seen, and any request_id/trace; for `review-feature` which
blueprint/area; for business skills the business (Whistlebird or Biz-E) and the concrete
artifact wanted. One round of questions, not an interrogation — the skill runs its own
interview for the details it owns (e.g. spec-first).

## Step 2: Route from the index

1. **Domain first**: is this about *this codebase* (files, bugs, features, CI, deploys)
   or *running the businesses*? The index's categories 1–4 vs 5–8 rarely overlap; get
   this call right and the rest is a lookup.
2. **Most specific row wins** when the ask already names the work. "Draft a follow-up to
   Liquorland Petone" goes straight to `sales-manager`, not through `business-operator`.
   Front doors (`new-feature`/`review-feature`/`fix-bug`/`business-operator`) are for
   broad asks.
3. **Genuinely ambiguous** (spans two skills or both surfaces) → one short clarifying
   question, or name the primary skill and note the follow-on handoff so nothing drops.
4. **State the match and why in one sentence, then invoke the skill** with the context
   from Step 1 passed as its args/opening message. Routing that ends in a description
   instead of an action isn't routing.
5. **Nothing fits** → say so plainly. A genuinely new kind of request may mean a skill
   is missing — flag it, don't paper over with the closest-but-wrong skill.

## Step 3: Preflight once, then hand it down

Before invoking any **code** front door (`new-feature`, `review-feature`, `fix-bug`,
`dependency-update`, `deploy-runner`), run **preflight** — once, here, at the top:

```bash
python3 scripts/preflight.py --json
```

~3s, and it replaces every ad-hoc probe a downstream skill would otherwise make.
**Pass the report into the front door's context verbatim.** One run, one set of facts:
a router that lets each skill re-derive its own environment is a router that lets them
disagree about it.

Two things in the report change how you route:

- **`blockers` non-empty** → the environment can't do the work yet. Repair per the
  **preflight** skill's table (`uv sync --extra dev`, start the test DB, `alembic upgrade
  head`) *before* invoking the front door, rather than handing it a broken environment
  and letting it fail three steps in. If a documented command is what's broken, that's
  **docs-truth**, not a repair.
- **`decisions.verification_mode`** → `herdr-tabs` when the herdr CLI is available,
  `herdr-adversarial` when only a Codex partner pane exists, else `subagents`. Pass it
  through with `decisions.grader_engine`; the front doors read both and drive stages per
  `.agents/verification-chain.md`. Don't probe `HERDR_ENV` yourself; preflight already did.

**Every code change goes through the chain — there is no "small change" lane.** Whichever
code front door you route to, it runs the same verification chain on the same routing table
(`.agents/verification-chain.md`, `.agents/model-routing.json`): graders read-only on Codex,
build and verify on Sonnet 5, Opus 5 only for spec work. A one-line fix and a new blueprint
get the same tenant-isolation audit, because the one-line fix is where a missing `org_id`
filter is *more* likely, not less. If a request tempts you to route it somewhere lighter to
save a few minutes, that is the request most worth sending through the full chain.

Also hand down `decisions.live_server_tests` — a front door that knows the live suites
will skip won't misread `30 skipped` as a problem.

`capabilities.in_herdr` and `capabilities.herdr_cli` from this same report are what Step 4
checks next to decide whether it can build worktree isolation — don't re-probe `herdr` or
`HERDR_ENV` a second time.

## Step 4: Isolate — one fresh worktree per code task, then run now or queue

Every code front door commits somewhere. Left to the current checkout, that "somewhere"
is the one worktree this session already has open — only one code task can be in flight at
a time, and a second ask either waits or silently collides with the first one's uncommitted
files (the same "one writer per worktree" hazard `.agents/verification-chain.md` §6 names
for chain stages, just one level up, between whole front-door runs instead of within one).

The user has made the fix the standing policy for this router: **before invoking any code
front door, cut it a throwaway worktree on a fresh branch off `origin/main`.** Several asks
can then run at once, each isolated, and it is fine — expected, even — if their branches
later conflict with each other; that is `merge-request`'s rebase step to sort out at merge
time, not a reason to serialize the work up front. This supersedes `herdr-multi-agent-collab`
§6's "ask before building topology" default *for this one case*: the user already asked,
once, by requesting this behavior — that consent doesn't need re-confirming per invocation.

What happens after the worktree exists forks on one question, asked once per dispatch
(`AskUserQuestion`, "Run now" first and marked recommended):

- **Run now** — launch it live in its own herdr workspace/pane straight away (4.3).
- **Add to queue** — defer the launch to `claude-nightwatch`, the systemd-supervised
  watcher (`~/.claude/tools/claude_nightwatch.py`, unit `claude-nightwatch.service`,
  already `enabled`+`active`, survives reboots) that drains a FIFO store
  (`~/.claude/tools/agent_queue.py`) whenever quota and concurrency allow (4.4). Good for
  prepping several tasks and controlling the order they run in — queue order is insertion
  order — or for anything that doesn't need to be watched live. Works with or without
  Herdr, since the queued launch is headless and never touches a pane.

Default to "Run now" when the user hasn't signalled a preference; take "queue this",
"add it to the queue", "run these one after another", or "prep a few things" as an explicit
pick of "Add to queue".

**Applies to:** `new-feature`, `review-feature`, `fix-bug`, `dependency-update`, and the
meta-skills below that patch code and open their own MR (`docs-truth`, `suite-warden`,
`skill-smith`). `prod-sentinel` hands its finding to `fix-bug`, which gets its own worktree
there — don't double up. **Does not apply to** `deploy-runner`: it ships an already-merged
`main`, it doesn't branch off it, so there is nothing to isolate.

**Requires Herdr for "Run now" only.** If Step 3's report shows `in_herdr: false` or
`herdr_cli: false`, there is no herdr space to launch a live pane in — fall back to the
Agent tool's own `isolation: "worktree"` (same fresh-branch-off-main guarantee, no visible
pane) rather than silently skipping isolation — see 4.3. "Add to queue" has no such
requirement; a queued item never needs a pane, so it works the same with or without Herdr.

### 4.1 Name the branch

One short kebab slug per ask (the same one you'd hand the front door as its scope), prefixed
by which door it's headed to:

| Front door | Branch prefix |
|---|---|
| `new-feature` | `feat/<slug>` |
| `fix-bug` | `fix/<slug>` |
| `review-feature` | `review/<slug>` |
| `dependency-update`, `docs-truth`, `suite-warden`, `skill-smith` | `chore/<slug>` |

### 4.2 Cut the worktree

How depends on the Step-4 answer: "Run now" needs a herdr pane to launch into; "Add to
queue" does not, since `claude-nightwatch` launches queued items headless and never opens
a pane for them. Don't spend a herdr workspace slot on a worktree nothing will visibly use.

**Add to queue** — plain `git worktree add`, no herdr involved at all:

```bash
git fetch origin main                          # fresh tip; never branch off a stale local main
git worktree add "$WORKTREES_DIR/<slug>" -b <prefix>/<slug> origin/main
```

Put `$WORKTREES_DIR` next to wherever `herdr worktree create` puts its own worktrees (see
`herdr worktree list --json` for the pattern in use) so cleanup tooling still finds it.
Then skip straight to 4.4 — do not launch anything, and do not touch a herdr pane, in
this turn.

**Run now** — one command does all of it:

`herdr worktree create` builds the branch, the checkout, and a new workspace/tab/pane bound
to it, in a single call (verified live: it returns `workspace.workspace_id`,
`root_pane.pane_id`, and `worktree.path`/`worktree.branch` together — no separate `herdr
workspace create` needed):

```bash
git fetch origin main                          # fresh tip; never branch off a stale local main

herdr worktree create --cwd "$(pwd)" \
  --branch <prefix>/<slug> --base origin/main \
  --label <slug> --no-focus --json
# -> {"result": {"workspace": {"workspace_id": "wN", ...},
#                "root_pane": {"pane_id": "wN:p1", ...},
#                "worktree": {"path": "...", "branch": "<prefix>/<slug>", ...}}}
```

The new pane is a plain shell at the worktree's path with no agent running yet. Launch
Claude Code into it, wait for it to boot, then hand it the actual task — the same two-step
"launch, gate on idle, then send" sequence `herdr-multi-agent-collab` §2 uses for a partner
pane, just aimed at a fresh workspace instead of a split:

```bash
herdr pane run <root_pane.pane_id> "claude"
herdr wait agent-status <root_pane.pane_id> --status idle --timeout 30000
herdr pane run <root_pane.pane_id> "/<front-door-skill> <the ask + Step 1 handoff context>. \
You are already on branch <prefix>/<slug> in an isolated worktree at <worktree.path>, cut \
fresh from origin/main — do not create another branch and do not touch any other checkout. \
Run your own preflight first; this worktree has no venv yet, so expect a deps blocker and \
repair it per the preflight table before doing anything else."
```

Report the workspace id, branch, and worktree path to the user in one line, then return —
**do not wait on it.** That is the point: a second ask can invoke `entrypoint` again
immediately, which repeats 4.1-4.2 with a new slug, a new branch, and a new workspace,
running alongside the first rather than queuing behind it.

### 4.3 No Herdr available

No CLI, or not `HERDR_ENV=1`: there's no herdr space to put it in, but the fresh-worktree
guarantee doesn't have to depend on Herdr. Use the Agent tool's own isolation instead:

```
Agent({
  description: "<slug> — isolated <front-door> run",
  isolation: "worktree",
  prompt: "<the ask + Step 1 handoff context>. You are on a fresh worktree cut from
    origin/main — run your own preflight first, and commit on <prefix>/<slug>."
})
```

Leave it in the background (the tool's default) so this turn isn't blocked either. Say
plainly in your reply that isolation here is filesystem-only — there's no pane to watch,
just a worktree path the tool result will report.

### 4.4 Conflicts are a later problem, cleanup is a later step

Don't reconcile two isolated worktrees against each other here — that freedom from
reconciling immediately is the entire reason this exists. If two tasks touched the same
file, `merge-request` surfaces that as a rebase conflict when it opens the MR, and cleanup
is cheap at that point because only one of the two branches needs to move. Two different
real asks colliding later is not a problem to prevent at dispatch time; the same slug asked
twice, on the other hand, is worth a one-line flag before you cut a second worktree for it.

Once a branch is merged (or abandoned), the worktree should go — `herdr worktree list
--json` enumerates what's still open, and `herdr worktree remove --workspace <id>` clears
one. Entrypoint doesn't chase this proactively (it dispatches and moves on), but surface it
when the user asks "what's still running" or "clean up my worktrees".

## Step 5: Route the meta-skills when the ask is really about the tooling

Some asks look like work but are actually about the machinery. Catch these — they're the
ones that otherwise get papered over with a wrong-but-plausible front door:

| Signal | Route to |
|---|---|
| A documented command fails/hangs; "the docs say X but Y happens"; CLAUDE.md looks wrong | `docs-truth` |
| Test failures that never reached an assertion (connection errors), a flake, "are these failures real" | `suite-warden` |
| "Create a skill for X"; a SKILL.md's instructions look stale; Step 0 found a stray SKILL.md | `skill-smith` |
| "Anything broken in prod"; a scheduled error sweep | `prod-sentinel` |
| "Is my environment set up"; unexplained connection errors | `preflight` |

The failure mode this table prevents: routing "the tests are failing" to `fix-bug`, which
then hunts for a bug in code that is fine, because the real answer was "no app server is
running". Preflight's report usually settles which of the two it is before you have to
guess — check `decisions.live_server_tests` and `blockers` first.

## Keeping this honest

- **The index is the single roster source.** Whoever adds a skill to either surface
  should add its row to `skill-index.md` in the same change — but Step 0 exists
  precisely because they won't always remember. Treat an unrouted skill as a broken
  handoff the sync repairs, not an error to complain about.
- Founder-ops pack documentation lives at `.claude/agents/README.md` (roster table) and
  `.claude/agents/AGENTS.md` (behavior) — cross-check there when categorizing a new
  business skill.
- Harness/built-in skills (`code-review`, `verify`, `loop`, `schedule`, `update-config`,
  …) are not in `.claude/skills/` and not in the index; route harness asks to them by
  name (category 5 in the menu).

## What this skill does NOT do

- Doesn't replace `business-operator`'s prioritisation judgment once you're in the
  founder-ops world — it gets you to business-operator, not past it.
- Doesn't replace a front door's own chaining (`new-feature` still runs its full
  spec → build → verify → merge-request sequence, with Breaker rounds when in Herdr) —
  entrypoint chooses the front door, it doesn't re-implement what happens after.
- Doesn't invent a skill that doesn't exist. If the ask has no home, say that.
- Builds exactly one piece of Herdr topology itself — the per-code-task worktree +
  workspace dispatch in Step 4 — because the user asked for that specific structure.
  Everything else about panes is still `herdr-multi-agent-collab`'s: the handoff-file
  protocol, Architect/Breaker rounds, and tabs-mode stage routing all happen *inside* the
  dispatched workspace, once the front door is running there. Entrypoint hands off and
  does not drive them.
