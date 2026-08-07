---
name: worktree-sweep
description: "Finds herdr/entrypoint-cut worktrees (and plain `git worktree add` ones) whose branch's MR is already merged, and removes them after a human confirms. Backed by scripts/worktree_sweep.py -- a deterministic, no-LLM classifier that only ever calls a worktree a remove_candidate when glab confirms its MR merged, its branch is a confirmed ancestor of origin/main, and the worktree is clean (no uncommitted changes, no unpushed commits). Everything close-but-not-clean lands in needs_human instead, never removed. Use this skill when the user says 'clean up my worktrees', 'what worktrees can I remove', 'sweep merged branches', or when entrypoint's Step 4.6 hands off a cleanup ask. Also runs unattended as scripts/worktree_sweep_watch.py on a daily timer -- but that path only ever detects and notifies, it never calls --apply. Not for creating worktrees (entrypoint Step 4 owns that), not for resolving rebase conflicts (mr-conflict-watch), not for the Herdr Architect/Breaker pane protocol (herdr-multi-agent-collab)."
---

# Worktree Sweep

`/entrypoint` cuts a fresh worktree + branch per code task off `origin/main` and says, in
prose only, that once the MR merges the worktree should go. Nothing ever did that, so they
pile up. This skill is the human-in-the-loop half of the tool that does it --
`scripts/worktree_sweep.py` does the hard, provable classification work; this skill's whole
job is to show you the result and get one confirmation before anything is deleted.

Read `.agents/autonomy.md`. This is *not* an autonomous-fix skill in the usual sense --
there is no MR to review after a worktree is gone, so the human turn has to happen *before*
the deletion, not after. Never call `--apply` without that confirmation step in between,
even though the script's own checks are strict enough that you'd usually be right to trust
them blind -- the whole reason this skill exists separately from the script is the pause.

## Steps

1. **Run the report.**

   ```bash
   python3 scripts/worktree_sweep.py
   ```

   Read `scripts/worktree_sweep.py`'s module docstring once if you haven't -- it states the
   exact safety model (glab-confirmed-merged AND ancestor-of-`origin/main` AND clean AND no
   unpushed commits, or it doesn't qualify) so you're not taking the classification on faith.

2. **Present it plainly.** Three buckets, and they mean different things to the user:
   - `remove_candidates` -- branch, MR state, path. These are the ones worth acting on.
   - `needs_human` -- flag these explicitly, especially "MR merged but uncommitted changes"
     entries. That's not noise -- it's "you may want to look at this diff before it's gone",
     and it has already happened for real in this repo (three separate worktrees, all with
     genuinely merged MRs, all carrying uncommitted changes at the same time).
   - `informational` (locked, detached, no MR found) -- worth a one-line mention, not a
     bucket to act on.

3. **Confirm with the user** which `remove_candidates` to actually remove. Default to "all
   of them" as the suggestion, but let them exclude any by name -- this is the one
   interactive step and the reason this skill exists as more than a cron job.

4. **Apply only what was confirmed**, by explicit path:

   ```bash
   python3 scripts/worktree_sweep.py --apply <path> [<path> ...]
   ```

   This re-verifies each path live immediately before touching it -- if something changed
   since step 1 (a human started working in it again, a lock appeared), it's skipped, not
   forced through. The result shows `removed` / `skipped` / `failed` -- read `failed` items
   back to the user; the script never retries a failure with a force flag, and neither
   should you.

5. **Report back**: what was removed, and remind the user what's still sitting in
   `needs_human` for later. Resolving those isn't this skill's job -- a dirty worktree on a
   merged branch needs a human decision about the diff, not automation.

## What it will not do

- **Never call `--apply` without step 3's confirmation**, even when invoked from an
  unattended context. If there is no user in this conversation to confirm (chained from
  something headless), stop after steps 1-2 and report the candidates instead -- that is the
  unattended substitute per `.agents/autonomy.md`, not a license to apply on your own
  judgment.
- **Never pass a force flag.** Not to `herdr worktree remove` (`--force`), not to
  `git worktree remove` (`--force`), not to `git branch -d` (never `-D`). The script itself
  doesn't; don't work around a reported failure by reaching for git directly with a stronger
  flag -- the failure is the signal to look, not to force it through.
- **Never touches a remote branch.** Cleanup here is local-only by design (the worktree, the
  local branch ref, `git fetch --prune`) -- GitLab already deletes the remote branch on
  merge.
- **Doesn't decide `needs_human` items for the user.** A merged-but-dirty worktree is a
  human call about whether the diff matters, not something this skill resolves by picking a
  side.

## Handoffs

- **← `entrypoint`** Step 4.6 routes "clean up my worktrees" / "what can I remove" here
  instead of describing the raw commands inline.
- **← `scripts/worktree_sweep_watch.py`** (daily systemd timer, unattended) notifies when
  new `remove_candidates` appear; its call to action is "run this skill" -- the watcher
  itself never applies anything.
- **→ nothing.** This skill doesn't hand off further; a removed worktree is a closed loop.

## Report contract

Verdict vocabulary: `clean` (ran, nothing to remove), `applied` (removed N, confirmed by the
user first), `needs-human` (candidates exist but nothing was applied -- unattended context,
or the user deferred). Never report `applied` for anything that wasn't both a fresh
`remove_candidates` entry at apply-time *and* explicitly confirmed by the user.
