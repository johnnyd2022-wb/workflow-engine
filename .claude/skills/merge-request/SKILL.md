---
name: merge-request
description: "The last mile for new-feature, review-feature, and fix-bug: writes the GitLab MR description from the spec and stage reports (ACs linked to the tests that prove them), pushes, opens the MR via glab, watches the pipeline, handles rebase conflicts, and responds to review threads. Use this skill whenever one of those three front doors reaches its final step, or whenever the user says 'open the MR', 'push this up', or asks about pipeline/review status on a branch already built and verified."
---

# Merge Request

Every front door (`new-feature`, `review-feature`, `fix-bug`) ends here. This skill's job
is to make the MR describable and reviewable purely from the artifacts the chain already
produced — a spec, a set of stage reports — so opening it is assembly, not composition
from memory. If you're inventing what the feature does while writing the MR body, stop
and re-read `.agents/specs/<slug>.md`; that's the drift this skill exists to prevent.

## Preconditions

Do not run this skill until the calling front door's chain says it's ready: unit tests
green, verification stages at `clean` or `patched` (not `findings-open`), `ci-gate`
verify mode reporting `GATE ...: pass` for every gate that applies. If any stage is still
`findings-open`, that is the front door's problem to resolve first — refuse and say why,
don't open an MR to buy time.

## 1. Write the MR description from artifacts, not narration

Source material, all of it already on disk:
- `.agents/specs/<slug>.md` — description, ACs, out-of-scope (for `fix-bug`, there is no
  spec; use its `.agents/reports/fix-bug/<date>-<slug>.md` instead)
- `.agents/reports/<slug>/*.md` — one line per stage: verdict, findings count, what was
  patched
- `.agents/reports/<slug>/rounds.md` if a patch loop ran — worth a line if anything
  survived more than one round

Template:

```markdown
## Summary
<one paragraph, from the spec's Description>

## Acceptance criteria
- AC1: <statement> — tests/test_<slug>.py::test_ac1_...
- AC2: ...

## Verification
| Stage | Verdict | Report |
|---|---|---|
| unit/integration | pass | tests/test_<slug>.py |
| security-audit | clean/patched | .agents/reports/<slug>/security.md |
| e2e-playwright | pass (3/3 flake-checked) | .agents/reports/<slug>/e2e.md |
| migration-safety | pass / skipped (no data model changes) | ... |
| observability | instrumented | .agents/reports/<slug>/observability.md |
| ci-gate | GATE lint: pass, GATE unit: pass, ... | |

## Out of scope
<from spec, if any>

## Waived stages
<state any the user explicitly waived, per new-feature's rules — never silent>
```

For `fix-bug`, swap the ACs table for: symptom, root cause, repro test (name it —
reviewers should be able to run it), fix summary, chain subset run.

## 2. Push and open

```bash
git push -u origin <branch>
glab mr create --fill --assignee johnnyd2022 \
  --title "<type>: <slug summary>" --description-file <(cat <<'EOF'
<the assembled description>
EOF
)
```
Title prefix matches the front door: `feat:` (new-feature), `refactor:`/`fix:`
(review-feature, depending on what it did), `fix:` (fix-bug). Username and assignee
convention: `johnnyd2022` (`.claude/agents/AGENTS.md`).

## 3. Watch the pipeline

```bash
glab ci status --live   # or: glab mr view --web and check manually
```

Do not report the MR as done while the pipeline is still running. If a job fails:

1. Read the failure, not just the red X — `glab ci trace <job>` for the actual log.
2. **CI-only failure** (passed locally, fails in the runner): usually an env/config
   mismatch — check the mapping comment at the top of `.gitlab-ci.yml` first (written by
   `ci-gate`'s self-discovery pass) before guessing at a new cause.
3. **Real failure**: hand back to the front door that built this (patch loop territory,
   not this skill's job to fix code).
4. Never re-run a failed job hoping it passes without understanding why, except for a
   named-flaky job already tracked as such.

## 4. Rebase conflicts

If `main` has moved and the MR shows conflicts:

```bash
git fetch origin main && git rebase origin/main
```

Resolve conflicts by re-reading both sides' intent, not by mechanically picking one; a
resolved conflict that silently drops the other side's change is a worse bug than the
conflict itself. After resolving, re-run the unit suite and `ci-gate` verify mode before
force-pushing the rebased branch — a rebase can silently break something the original
branch didn't. Never `git push --force` without confirming the remote branch has no
review comments referencing commits you're about to rewrite; if it does, prefer
`--force-with-lease` and say so.

## 5. Review threads

When a reviewer comments (`glab api projects/:id/merge_requests/:iid/discussions` or
`glab mr view --web` to read them):

- Substantive comment (bug, design concern) → treat like a `fix-bug` round: fix, push,
  reply on the thread explaining what changed, do not resolve the thread yourself — the
  reviewer does.
- Question → answer inline, no code change needed.
- Never mark a thread resolved that you didn't get explicit agreement was addressed.

## Rules

- Never write an MR description from what you remember building — from the spec and
  reports on disk. Memory drifts across a long session; files don't.
- Never mark an MR ready/remove a draft flag until pipeline is green and every stage this
  skill was handed says pass/clean/patched.
- Assignee is always `johnnyd2022` per the workspace convention unless the user says
  otherwise for this MR specifically.
- This skill does not fix code. A failing pipeline or a substantive review comment goes
  back to the front door that built the feature/fix; this skill's job is the MR
  lifecycle, not the code inside it.

## Handoffs

- ← **new-feature / review-feature / fix-bug**: final step of each, called once every
  gate is green.
- → **new-feature / review-feature / fix-bug**: real CI failures or substantive review
  comments bounce back for a patch round.
- → **release-manager** (founder ops workspace): once merged, if this MR represents a
  user-facing change worth a changelog entry, note it — release-manager owns the
  release-notes/changelog step, not this skill.
