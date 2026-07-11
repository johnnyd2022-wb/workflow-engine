---
name: repo-conventions
description: "Owns the repo's real, evidence-based code-level conventions at .agents/conventions.md: blueprint/feature layout, repository pattern, auth/org-scope enforcement, validation style, naming. Every builder skill (new-feature, review-feature, fix-bug) reads this before writing code. Use this skill when starting any of those, when a new pattern needs documenting, or when the user asks 'how do we normally do X here' / 'what's the convention for Y'."
---

# Repo Conventions

Extracts patterns from the codebase as rules with `file:line` evidence, so builders stop
guessing and stop copying stale scaffolds. Owns `.agents/conventions.md`.

## Rule: evidence or it doesn't go in the file

Every rule in `conventions.md` cites at least one `file:line`. If you can't point at
where the pattern is used, it's not a convention yet — either it's a one-off, or it's
something you're proposing (write that under "Open items", not as a rule). Never derive
a rule from another skill's description or from a summary of the codebase; read the
actual files.

## When invoked to (re)build the file

1. Read `CLAUDE.md` for the documented architecture, then verify each claim against the
   code — CLAUDE.md can drift; the code is truth.
2. Pick the 2-3 most complete, most recently touched blueprints (`git log --stat` on
   `app/features/*` and the core blueprints is a fast way to find "best" = actively
   maintained, not just biggest). Read routes, services, repositories, models for each.
3. Extract, with citations: blueprint/directory layout, the data-access pattern (repo?
   active record? raw queries?), how auth/org-scope is actually enforced (decorator?
   middleware? both, and do they agree?), how request/response validation is done,
   naming conventions, where shared utilities live vs feature-local ones.
4. Where you find a discrepancy — a documented pattern that isn't what the code does, two
   competing idioms, a decorator that's declared but unused — **write it down as a
   discrepancy, don't silently pick a winner**. That's a judgment call for Johnny or
   whoever owns the merge. `cto-software-architect` (founder ops workspace) is the right
   escalation point if it's architectural; otherwise it's an "Open items" entry.
5. Cross-check any hard rules embedded in code comments/docstrings (e.g. a module that
   documents a required call sequence or a forbidden side effect inside a transaction) —
   these are load-bearing and belong in the file verbatim-cited, not paraphrased away.

## When invoked after a feature or bug fix ships

Append **one lesson**, not a rewrite. A lesson is something the next builder would
otherwise get wrong: a pattern this feature had to introduce, a trap it hit, a
convention it confirmed. Cite the new `file:line`. Don't restate existing rules.

## What this skill does NOT own

- Architecture decisions and their rationale (why Postgres over X, why this data model)
  → `cto-software-architect` writes ADRs; this file links to them, never duplicates the
  reasoning.
- Enforcement — `ci-gate`/semgrep enforce what can be automated; this file covers what
  can't (layout, idiom, judgment calls a linter can't catch).
- Test infrastructure conventions → owned by **test-fixtures** once built; link to it
  rather than re-describing the fixture pattern here.

## Handoffs

- → **new-feature / review-feature / fix-bug**: read `.agents/conventions.md` before
  scaffolding anything; its layout section supersedes any hardcoded scaffold shape in
  their own SKILL.md text if the two disagree (this file is evidence-based and updates
  more often).
- → **cto-software-architect**: architectural discrepancies found during extraction.
- ← **new-feature / review-feature / fix-bug**: one-lesson appends after each ship.
