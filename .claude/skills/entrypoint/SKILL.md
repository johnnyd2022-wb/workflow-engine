---
name: entrypoint
description: "Top-level router across every registered skill in this repo — both the biz-e code suite (new-feature, review-feature, fix-bug, and their specialists) and the founder-ops pack (business-operator and its specialists). Self-updating: syncs a cached category index (skill-index.md) against the live .claude/skills/ roster on every run, so new/renamed/retired skills are picked up automatically. Use this when the user doesn't know which skill to reach for: 'which skill should I use', 'help', 'where do I start', 'I want to build/fix/ship X' with no named skill, or any request that could plausibly map to more than one skill. Not for requests that already clearly name their skill (e.g. 'run sales-manager') — invoke that skill directly instead."
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
`.claude/`, so the scan has three tiers:

```bash
# 1. Registered roster — the only skills the Skill tool can actually invoke
ls -1 .claude/skills/ | sort

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
- **`decisions.verification_mode`** → `herdr-adversarial` when a Codex partner pane
  exists, else `subagents`. When it's `herdr-adversarial`, append to the handoff:

  > Running inside Herdr with a Codex partner pane — route verification through
  > herdr-multi-agent-collab (Architect/Breaker, Workflow A/B, two-round circuit breaker).

  The front doors each carry their own "If running inside Herdr" clause, so this line is
  a confirmation, not an instruction. Outside Herdr, say nothing — they default to
  subagents. Don't probe `HERDR_ENV` yourself; preflight already did.

Also hand down `decisions.live_server_tests` — a front door that knows the live suites
will skip won't misread `30 skipped` as a problem.

## Step 4: Route the meta-skills when the ask is really about the tooling

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
- Doesn't drive the Herdr panes itself — `herdr-multi-agent-collab` owns the pane
  protocol; entrypoint only flags that the session is in Herdr.
