---
name: skill-smith
description: "Creates and audits the skills themselves: scaffolds a new SKILL.md to this repo's house standard (frontmatter with real trigger phrases, autonomy reference, handoffs, honest verdicts), registers it correctly (symlink for founder-ops skills, entrypoint index row, takeaway export), and audits existing skills for rot — commands that no longer work, file paths that moved, skills nothing routes to. Use this skill when adding a new skill, when a skill's instructions look stale or wrong, when the user says 'create a skill for X', or on a scheduled skill-health audit. Autonomous: fixes what it can prove is wrong and opens an MR."
---

# Skill Smith

Entrypoint keeps its *index* current. Nothing keeps the *skills* current. A skill is
prose that agents execute — it rots exactly like code, but no test fails when it does.
A SKILL.md confidently instructing an agent to run `uv run workflow upgrade-db` when the
repo moved to alembic is a bug that ships silently every time that skill runs.

This skill owns the house standard: creating to it, and auditing against it.

Read `.agents/autonomy.md`. Ships via MR, doesn't ask permission to fix a broken command.

## The house standard

Every skill in `.claude/skills/` (and `.claude/agents/skills/`) must have:

1. **Frontmatter** — `name` matching the directory, and a `description` that is a
   *routing* document, not a summary. It must carry: what the skill does, the real
   trigger phrases a user would actually type, and what it is *not* for. Entrypoint and
   the harness both route on this string; a vague description is an unroutable skill.
   Founder-ops skills additionally carry `business`, `owns`, `triggers`.
2. **A first paragraph that says why the skill exists** — the failure mode it prevents.
   An agent that understands the point makes better calls in cases the steps don't cover.
3. **Numbered steps** with the actual commands, copy-pasteable, verified to run.
4. **An autonomy reference** — link `.agents/autonomy.md` rather than restating policy.
5. **A report contract** — where output goes, in what shape, with an honest verdict
   vocabulary (`clean | patched | findings-open`, `trustworthy | degraded`, etc.).
6. **Handoffs** — what feeds it (←) and what it feeds (→). An orphan skill nothing calls
   and that calls nothing is usually a skill that should have been a section of another.
7. **Rules** — the prohibitions, especially the ones an agent would rationalise around at
   3am. "Never weaken a gate to get green" belongs in every skill that could.

Anti-patterns this standard exists to kill: a description that's a title; steps with
commands nobody ran; policy restated (and now contradicting `.agents/autonomy.md`); a
verdict vocabulary where every outcome is success; instructions to "ask the user" in a
skill that runs on a cron.

## Creating a skill

1. **Check it should exist.** Read `.claude/skills/entrypoint/skill-index.md`. If an
   existing skill's description covers the ask, extend that skill. Two skills with
   overlapping triggers is worse than one big one: the router picks wrong and the user
   learns not to trust it.
2. **Scaffold** `.claude/skills/<name>/SKILL.md` to the standard above.
3. **Verify every command you wrote.** Run them. A command in a SKILL.md is an assertion
   that it works; an unrun command is a lie with a shell prompt in front of it. This is
   the step that separates this skill from a template.
4. **Back the deterministic parts with a script.** If a step is "check these ten things"
   or "group these records", that's `scripts/`, not tokens — see `scripts/preflight.py`
   and `scripts/error_scan.py` for the pattern (stdlib, `--json` for agents, human
   summary by default, exit codes that mean something).
5. **Register it:**
   - Engineering skill → it's already in `.claude/skills/`, nothing more.
   - Founder-ops skill → lives in `.claude/agents/skills/<name>/`, then
     `ln -s ../agents/skills/<name> .claude/skills/<name>`. Entrypoint's Step 0 would
     eventually catch an unregistered one, but don't make it do your job.
   - Add its row to `skill-index.md` in the right category (entrypoint's sync will
     otherwise do it on next run — same reasoning).
   - Update `.claude/agents/README.md` for founder-ops skills.
6. **Wire the handoffs both ways.** If your new skill is called by `new-feature`, say so
   in `new-feature` too. A one-directional handoff is a dangling pointer.

## Auditing skills

Run per skill, or across the roster on a scheduled sweep:

```bash
# 1. every fenced command still resolves
grep -oE '^\s*(uv run|python3?|docker|glab|herdr|pytest|alembic) [^\n]+' .claude/skills/<name>/SKILL.md

# 2. every referenced file still exists
grep -oE '(app|tests|scripts|docs|\.agents|\.claude)/[A-Za-z0-9_./-]+' .claude/skills/<name>/SKILL.md \
  | sort -u | while read -r p; do [ -e "${p%%:*}" ] || echo "MISSING: $p"; done

# 3. every file:line citation still points at what it claims
# 4. is it in the index, and does anything route to it?
python3 scripts/skill_graph.py --check          # orphans, unindexed, stale roots
python3 scripts/skill_graph.py --skill <name>   # who calls it, what it calls
```

`skill_graph.py` answers the orphan question deterministically, so don't grep for it by
hand. When it reports an orphan, **you** own the fix — entrypoint detects and routes it
here precisely because "where does this wire belong" is a design judgment, not a lookup.
Wire it into the workflow that should trigger it, in that skill's own file, and add the
skill to `ROOTS` **only** if it's genuinely user- or schedule-invoked. Padding `ROOTS` to
silence the check is the same move as deleting a failing test.

Audit checklist per skill:

- **Commands** — do they run? Do they use the current tool (`alembic upgrade head`, not
  `workflow upgrade-db`)? Do they match how the repo actually invokes them?
- **Paths and citations** — does `app/observability/tracing.py:21` still say what the
  skill claims? Line numbers drift; a wrong citation teaches agents to distrust all of
  them.
- **Policy drift** — does it restate autonomy rules that now contradict
  `.agents/autonomy.md`? Does it tell an agent to ask a human in a skill that runs
  unattended?
- **Routability** — is it in `skill-index.md`? Does its description contain phrases a
  real user would type?
- **Overlap** — do two skills claim the same trigger? Name the winner, narrow the loser.
- **Orphans** — nothing calls it, it calls nothing, and it's not a front door. Propose
  merging or retiring.

Findings go to `.agents/reports/skill-smith/<date>.md`:

```markdown
# SKILL AUDIT — <date>
skills_audited: <n>/<total>
| skill | broken commands | bad paths | policy drift | routable | verdict |
|---|---|---|---|---|---|
fixed: <what was patched>
escalated: <what needs a human call — e.g. two skills genuinely overlap>
verdict: clean | patched | findings-open
```

Fix what is provably wrong (a command that errors, a path that 404s, a missing index
row). Escalate what is a judgment call (should these two skills merge?) — that's a design
decision, not a repair.

## Rules

- **Never invent a command you haven't run.** Everything in a SKILL.md is executable
  documentation. This is the rule this skill exists to enforce, so breaking it here is
  disqualifying.
- Don't restate `.agents/autonomy.md` — link it. Copies drift and then contradict.
- Don't scaffold a skill for work one already covers. Check the index first.
- A skill that runs on a schedule may not contain "ask the user" as a step. If it needs a
  decision, it escalates per the autonomy policy's escalation ladder.
- Deleting a skill needs a human: retiring capability is a product decision. Propose it
  with evidence; don't `rm` it.
- Keep `.claude/takeaway/` out of scope — those are export copies, and the Codex-side
  breaker skill there is not this registry's to edit.

## Triggered by

- ← **entrypoint** Step 0: a stray SKILL.md outside the known homes, or a skill whose
  description won't route.
- ← **preflight** / any skill: a command inside a SKILL.md that doesn't work.
- ← **docs-truth**: drift it found that lives in a SKILL.md (out of its scope, in yours).
- ← the user: "create a skill for X".
- ← a schedule: skill rot is invisible until an agent executes the wrong instruction.
