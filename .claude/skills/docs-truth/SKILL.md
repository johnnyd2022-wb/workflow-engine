---
name: docs-truth
description: "Verifies that CLAUDE.md, .agents/conventions.md, and docs/ actually match the repo: runs every documented command, resolves every documented path, and checks documented facts (ports, config defaults, env vars) against the real ini files and source. Fixes proven drift and escalates judgment calls. Use this skill when a documented command fails, when someone says 'the docs say X but Y happens', after a tooling or config change that docs might not reflect, when onboarding docs are suspect, or on a scheduled docs-health run. Autonomous: patches proven-wrong docs and opens an MR."
---

# Docs Truth

CLAUDE.md is loaded into the context of every session in this repo. That makes a wrong
line in it worse than a wrong line in any other file: it doesn't just fail, it actively
instructs every agent to fail the same way, quietly, forever. There is no test for it.

This skill is that test. It executes the documentation.

Read `.agents/autonomy.md`. Fixes ship as an MR; the MR is the gate.

## Scope

| Document | Why it matters |
|---|---|
| `CLAUDE.md` | auto-loaded into every session — highest blast radius |
| `.agents/conventions.md` | every builder skill reads it before writing code |
| `.agents/autonomy.md` | the policy skills cite; contradictions here are dangerous |
| `docs/*.md` | ports, setup, operational procedure |
| `README.md` | onboarding |
| `tests/TEST_DOCUMENTATION.md` | how the suite is meant to be run |

`.claude/skills/**/SKILL.md` is **not** in scope — that's `skill-smith`'s. Don't both fix
the same file.

## The classes of drift (they need different responses)

This distinction is the whole skill. Getting it wrong means either ignoring real breakage
or "fixing" a deliberate choice:

1. **Broken** — the documented command errors, hangs, or the path doesn't exist. Provably
   wrong. **Fix it.**
2. **Stale fact** — the doc states a port/default/name that contradicts the ini or source.
   Provably wrong. **Fix it.**
3. **Dispreferred** — the command *works*, but the team uses something else. Not a bug;
   a preference. **Escalate, don't silently rewrite.** Example: `uv run workflow
   upgrade-db` exists and runs — the preference for `uv run alembic upgrade head` is a
   human call about which is canonical, not a defect for an agent to decide.
4. **Missing** — real practice nobody wrote down. **Propose an addition**, flagged as new
   content rather than a correction.

## Step 1: Extract the claims

```bash
# every fenced command in a doc
grep -nE '^\s*(uv run|python3?|docker|docker-compose|glab|herdr|pytest|alembic|ln|export) ' CLAUDE.md

# every path referenced
grep -oE '(app|tests|scripts|docs|\.agents|\.claude)/[A-Za-z0-9_./*-]+' CLAUDE.md | sort -u

# every port/number claim worth checking against config
grep -nE 'port|:[0-9]{4}|localhost:[0-9]+' CLAUDE.md docs/*.md
```

## Step 2: Execute them

Run preflight first (`python3 scripts/preflight.py --json`) — a documented command that
fails because the test DB is down is an environment problem, not doc drift, and blaming
the doc for it is the classic false positive here.

Then actually run each command, with a timeout, in a scratch dir where it could mutate
something:

```bash
timeout 90 <documented command>; echo "exit=$?"
```

**A command that hangs is broken**, not slow. Exit 124 from `timeout` is a finding.
Resolve every documented path with `test -e`. Check every documented port/default against
`app/config/*.ini` rather than trusting either the doc or your memory of it.

## Step 3: Known live findings

Verified in this repo — the reference cases for what this skill catches:

**`CLAUDE.md` documents a test command that hangs.** It says
`ENVIRONMENT=test uv run pytest tests/ -v`. From a host shell that hangs indefinitely:
`app/config/test.ini` sets `host = host.docker.internal` because the test app runs
*inside Docker*, and that name doesn't resolve from the host, so psycopg2 blocks. With
`ENVIRONMENT` unset the loader falls back to `local` (`app/utils/config_loader.py:16`),
and `local.ini` points at `localhost:8401` — **the same test database** — so the suite
runs in ~23s. Class: **broken**. `scripts/preflight.py`'s `test_db` check now detects
this exact trap and names the fix.

**`CLAUDE.md` documents `uv run workflow upgrade-db`.** The command exists and runs
(`uv run workflow --help` lists it, alongside a `migrate` group). Class: **dispreferred**,
not broken — the team's preference for `uv run alembic upgrade head` is a human call.
Escalate; do not rewrite unilaterally.

Two drifts in one file is the argument for running this skill on a schedule.

## Step 4: Fix, and prove the fix

For **broken** and **stale fact** findings: patch the doc to what you *verified*, not to
what you assume. Then run the corrected command and paste the real result into the report.
A doc fix that wasn't executed is the same defect with a new value.

For **dispreferred** and **missing**: write them to the report's escalation section with
the evidence and a recommendation. The human decides.

## Step 5: Report

`.agents/reports/docs-truth/<date>.md`:

```markdown
# DOCS TRUTH — <date>
docs_checked: CLAUDE.md, .agents/conventions.md, docs/*.md, README.md
commands_run: <n> (<n> passed, <n> broken, <n> hung)
paths_checked: <n> (<n> missing)

## Fixed (proven wrong)
- CLAUDE.md:<line> — <claim> — <evidence: exit code / error / config line> — <new text, verified by rerun>

## Escalated (judgment)
- <claim> — works but dispreferred / undocumented practice — recommendation

verdict: clean | patched | findings-open
```

## Rules

- **Never "fix" a doc from memory.** Run the command. Read the config line. The whole
  point of this skill is that it executes rather than believes — an agent rewriting docs
  from assumption is the disease, not the cure.
- Never delete a documented command because it failed once — establish *why* (environment
  vs genuinely broken) via preflight first.
- Preference is not defect. If it runs, it isn't broken; escalate instead of rewriting.
- Don't touch `SKILL.md` files (skill-smith owns those) or `.claude/agents/` business
  context (the founder owns those facts).
- Cite file:line for both the claim and the evidence, so a reviewer can check your work in
  one click. Wrong citations here would be self-refuting.

## Handoffs

- ← **preflight**: distinguishes "environment down" from "doc wrong" before you accuse a doc.
- → **skill-smith**: if the drift is in a SKILL.md, hand it over rather than fixing it here.
- → **git-commit-chain**: ships the doc fixes as an MR.
