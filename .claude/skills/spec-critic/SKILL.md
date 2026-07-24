---
name: spec-critic
description: "Adversarially grades a written spec for build-readiness BEFORE any code exists — the spec-side mirror of test-evaluator. Hunts untestable acceptance criteria, undecided tenant-scoping, unstated destructive data-model changes, vague words ('fast', 'secure', 'handle'), ACs that don't cover the description, and hidden external surfaces. Use this skill after spec-first writes a spec and before build starts, whenever new-feature reaches its spec step, or when the user says 'is this spec ready', 'poke holes in this spec', 'what's underspecified here'. NOT for writing the spec (spec-first), NOT for grading tests (test-evaluator). It never edits the spec — it reports gaps and blocks; spec-first resolves them. Autonomous: grades and returns a verdict; the build is blocked on 'sound'."
---

# Spec Critic

Ambiguous specs are the number one cause of agentic rework — and the cost lands hardest on
exactly the workflow this repo is built for: describe a feature, walk away, come back to a
finished MR. If the spec was vague, you come back to a *confidently wrong* MR, and the wrong
turn was taken on line one, before a single gate could catch it. Every downstream gate checks
the code against the spec; none of them checks the spec against reality. This skill is that
missing check.

It is the spec-side mirror of **test-evaluator**: an independent grader that never writes what
it grades. spec-first authors the spec; this skill pokes holes in it; spec-first fixes them.
A critic that edits the spec is just a second author, and the separation is the whole point —
so this skill **reports and blocks, it does not rewrite the spec**.

Read `.agents/autonomy.md`. Runs unattended; returns a verdict that gates the caller's build.

## Step 1: Load the spec

Read `.agents/specs/<slug>.md`. It follows the exact contract in the **spec-first** skill:
`## Description`, `## Users & permissions` (roles, tenant_scoped), `## Acceptance criteria`
(`AC<n>` IDs), `## Data model` (changes, destructive), `## External surfaces`, `## Out of
scope`. Grade the spec **as written** — not the feature you imagine it means. If a section is
missing entirely, that is itself a gap.

## Step 2: Hunt the gaps

Go looking for trouble, not for reasons to pass. The recurring failures, worst first:

- **Untestable acceptance criteria.** Every `AC<n>` must be falsifiable by a test that could
  go red. "The page is fast" / "handles errors gracefully" / "is secure" are not criteria —
  they are wishes. Rewrite-in-your-head test: can you name the assertion? If not, it's a gap.
- **Undecided tenant scoping.** This is a multi-tenant app; `tenant_scoped` is not optional.
  If it's blank, or "yes" without saying which tables carry `org_id`, the build will guess —
  and a guessed-wrong org filter is a cross-tenant data leak. Treat an undecided scope as a
  **high-severity** gap.
- **Silent destructive data-model changes.** `destructive: no` next to a column rename or drop
  is a contradiction. Anything that could lose data must be named as destructive so
  migration-safety runs. An unstated destructive change is the one gap that can't be undone.
- **Description/AC mismatch.** List what the `## Description` promises, then check each promise
  is pinned by an AC. A capability described but not in any AC ships untested; an AC for
  something the description never mentions is scope creep. Both are gaps.
- **Hidden external surfaces.** Uploads, webhooks, third-party APIs, background jobs mentioned
  in the description but absent from `## External surfaces` — each one is a security-review
  blind spot the spec is hiding.
- **Missing out-of-scope.** No `## Out of scope`, or a vacuous one, invites a builder agent to
  gold-plate. Name the tempting-but-excluded things.

## Step 3: Verdict and hand-off

End your reply with exactly one line: `VERDICT: sound | gaps-found`.

- **`sound`** — every AC is testable, tenant scoping is decided, destructive changes are
  named, the ACs cover the description, external surfaces are complete. The build may proceed.
- **`gaps-found`** — list each gap as `GAP (severity): <what> → <the resolution or assumption
  the spec should state>`. You propose the resolution; you do **not** write it into the spec.

What happens to the gaps depends on who's there (per `.agents/autonomy.md`):

- **Interactive** (the user is available): the caller / spec-first takes your gap list back to
  the user, edits the spec, and re-runs you. `gaps-found` blocks the build until it's `sound`.
- **Unattended** (scheduled, chained, or the user walked away): the build cannot stop to ask.
  spec-first turns each of your gaps into an explicit `ASSUMPTION:` line in the spec (the
  default it chose *and* what it rejected), sets `status: approved-unattended`, and those
  assumptions lead the MR description — where the human signs off next to the diff. Your gap
  list is what makes those assumptions honest instead of invisible. Re-run once after the
  assumptions are written; a spec whose every gap is now a stated assumption grades `sound`.

## Circuit breaker

If the same gap survives two rounds — spec-first keeps not resolving it — stop and escalate
per `.agents/autonomy.md`. A gap that can't be closed twice usually means the feature itself
is underspecified at the human level, which is not the agent's to invent.

## Rules

- Never edit the spec, the tests, or the code. You report; spec-first resolves. That
  separation is the mechanism.
- Never pass a spec to be polite. A `sound` verdict is a claim that the build has no ambiguity
  to trip on — say `gaps-found` whenever that isn't true, even on your own caller's spec.
- Grade the spec as written, not the feature you'd have designed. Your job is "is *this*
  buildable without guessing", not "is this the best possible feature".
- Record the run when chained (`.agents/autonomy.md` → Measure yourself):
  `python scripts/skill_metrics.py record --skill spec-critic --run-type chained --scope <slug>
  --verdict <clean|findings-open> --findings <gap count> --ref feat/<slug>` (map `sound`→`clean`,
  `gaps-found`→`findings-open`).
