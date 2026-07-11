---
allowed-tools: Bash(git status:*), Bash(git diff:*), Bash(git log:*), Bash(git add:*), Bash(git commit:*), Bash(git stash:*), Bash(git stash pop:*), Bash(git stash drop:*), Bash(git reset:*), Bash(git branch:*), Bash(git show:*), Bash(git rebase:*), Bash(git push:*), Bash(git pull:*), Bash(git switch:*), Bash(git rev-parse:*), Bash(glab api:*), Bash(glab mr create:*), Bash(glab mr update:*), Bash(glab mr view:*), Bash(glab ci status:*), Bash(glab ci view:*), Bash(glab ci trace:*), Bash(glab ci get:*), Bash(uv lock:*), Bash(uv sync:*), Bash(uv run semgrep:*), Bash(uv run pytest:*)
description: Organise changes into a clean commit chain, validate, push, write an MR, then monitor and safely repair related GitLab CI failures with glab
---

## Context

- Working tree status: !`git status`
- Full diff of all changes (staged and unstaged): !`git diff HEAD`
- Commits ahead of main on this branch: !`git log main..HEAD --oneline`
- Recent commit style reference: !`git log --oneline -10`

## Your task

You are creating a clean, logically organised commit chain from the current working tree. Follow every step below in order.

---

### Step 0 — Synchronise main and create a branch

Before analysing or stashing changes, inspect the current branch with `git branch --show-current`. Use `glab api projects/:id/repository/branches/main` to retrieve the current GitLab main SHA and compare it with `git rev-parse HEAD`.

- If the current branch is `main` and the GitLab main SHA differs, run `git pull --ff-only origin main` to update the local checkout. Stop if it cannot fast-forward. `glab` performs the GitLab query; `git pull` is required to update the local repository.
- If the current branch is `main`, create a relevant branch before making any commit, for example `git switch -c chore/configure-observability-toggles`. Do not commit directly to `main`.
- If already on a non-main branch, confirm it is relevant to the task; otherwise create a new relevant branch from the synchronised main base.

Use `glab` for all GitLab API, merge-request, and pipeline interactions. Use local `git` only for local working-tree, branch, commit, and transport operations.

---

### Step 1 — Analyse and group changes

Read the full diff carefully. Group every changed file (and individual hunks where a file spans two concerns) into **logical commit buckets**. A logical boundary exists wherever:

- A change affects a different feature, subsystem, or concern than another change (e.g. a backend route fix is separate from a CSS tweak)
- A change is purely mechanical/housekeeping (dependency bumps, config, formatting) vs. substantive logic
- A change introduces a new capability vs. fixes an existing one

Name each bucket with a short imperative phrase that will become the commit message (e.g. "fix: validate org_id on execution endpoint", "feat: add batch-start HTMX partial", "chore: pin htmx to 1.9.12").

Think hard — a good grouping catches subtle coupling (e.g. a new helper function used only by one feature belongs in that feature's commit).

**Tip — commit message style to follow:**
- Look at the recent commits retrieved above and match the style (conventional commits, sentence case, etc.)
- Keep the subject line under 72 characters
- Use imperative mood ("add", "fix", "remove", not "added", "fixed")

---

### Step 2 — Safety backup

Before touching the index or history, stash everything:

```
git stash push --include-untracked -m "git-commit-chain backup <timestamp>"
```

Confirm the stash was created successfully before continuing. If the stash fails, stop and report the error.

---

### Step 3 — Check for prior commits to clean up

If there are commits ahead of `main` on this branch (from the context above):

- Those commits likely contain the same changes now in the stash, but in a messier form.
- **Soft-reset** the branch back to `main` so those commits become unstaged changes again:
  ```
  git reset --soft main
  ```
  Then pop the stash on top (the stash's changes will merge with the re-unstaged ones):
  ```
  git stash pop
  ```
  You now have everything — prior commits + new work — as unstaged changes ready to re-commit cleanly.

If there are **no** prior commits ahead of main, simply pop the stash:
```
git stash pop
```

---

### Step 3.5 — Refinement of existing work vs. genuinely new work

Before creating a commit for each bucket, ask: **is this a correction to something already committed on this branch (ahead of main), or is it new work?**

If you are actively iterating on a feature this session and discover a bug/typo/oversight in a commit you *already made earlier in the same branch* (not yet merged to main), don't stack a `fix: correct typo in previous commit` commit on top. Update the original commit instead, so the branch's history reads as if it were written correctly the first time:

- **The commit is HEAD** (the very last commit on the branch): amend it directly.
  ```
  git add <files>
  git commit --amend --no-edit        # or drop --no-edit to revise the message too
  ```
- **The commit is further back**: use a fixup commit and autosquash rather than an interactive rebase you'd have to babysit.
  ```
  git add <files>
  git commit --fixup=<sha-of-original-commit>
  GIT_SEQUENCE_EDITOR=true git rebase -i --autosquash main
  ```
  `GIT_SEQUENCE_EDITOR=true` accepts the auto-generated rebase plan without opening an editor.

This does **not** apply to:
- Work already merged into `main` — never rewrite merged history; add a new commit.
- A change that is a genuinely distinct concern from the original commit, even if related (e.g. the original commit added a feature and this change adds a *different* feature that happens to touch the same file) — that's still a new commit.
- Anything you're not confident maps to a specific prior commit — when in doubt, make a new commit rather than guess which one to amend.

Amending or rebasing a commit that's already been pushed rewrites remote history — the eventual push in Step 8 will need `--force-with-lease` and must be flagged to the user before it happens (see Step 8).

---

### Step 4 — Create the commit chain

For each bucket you identified in Step 1, in a logical dependency order (foundational/shared changes first, feature-level changes second, housekeeping last):

1. Stage only the files (or specific hunks) that belong to this commit.
2. Verify with `git diff --cached` that only the intended changes are staged.
3. Commit with the message drafted in Step 1.
4. Confirm the commit landed with `git log --oneline -1`.

Repeat until all changes are committed. Do not batch all commits into one tool call — commit them sequentially so each can be verified.

**Rules:**
- Never use `git add -A` or `git add .` — always stage specific files or paths.
- Never skip a verification step.
- If a file contains changes for two different buckets, use `git add -p` to stage individual hunks.
- Do not commit files that may contain secrets (`.env`, credential files, `*.key`, `*.pem`). Warn the user if you encounter them.

---

### Step 5 — Review the resulting chain

Run `git log main..HEAD --oneline` and display the full list of commits created. Briefly confirm each commit represents a single logical concern and that nothing was accidentally omitted.

If you spot a mistake (wrong files in a commit, a change that was missed), fix it now using `git reset --soft HEAD~1` to undo the last commit and restage correctly.

---

### Step 6 — Validation: semgrep

Run semgrep to check for newly introduced security or code-quality issues:

```
uv run semgrep scan --config=auto
```

If semgrep is not configured with `--config=auto` in this project, fall back to:

```
uv run semgrep scan --config=p/default
```

Report any findings. If semgrep finds **new** issues introduced by the commits (not pre-existing), diagnose and fix them before proceeding unless the user explicitly accepts an external or environment-only limitation.

---

### Step 7 — Validation: tests

Run the project test suite:

```
uv run pytest tests/ -v
```

If a specific test file is more relevant to the changes, run that file first for speed, then the full suite if it passes.

Report a pass/fail summary. If tests fail, diagnose and repair failures caused by this branch before proceeding. Do not remove, skip, weaken, or broaden a test merely to make it pass. Change a test fixture or expectation only when it faithfully represents an intentional behaviour change. If the failure is external, pre-existing, or needs unavailable infrastructure or credentials, report the evidence and stop unless the user explicitly accepts that limitation.

---

### Step 8 — Push and verify with glab

Only proceed if semgrep and tests both passed in Steps 6–7, or the user explicitly accepted a documented external limitation.

Push the branch:
```
git push
```

**If Step 3.5 amended or rebased any commit already on the remote**, a plain `git push` will be rejected (non-fast-forward) — that's expected. Tell the user explicitly that history was rewritten and ask for confirmation before running:
```
git push --force-with-lease
```
Never use plain `--force`. `--force-with-lease` refuses to push if the remote has commits your local branch hasn't seen (e.g. someone else pushed since your last fetch); `--force` would silently clobber them. Do not force-push without the user's explicit go-ahead — this rewrites shared branch history.

After a successful push, verify with `glab` rather than assuming the push landed as intended:
```
glab mr view                 # if this branch has an open MR, confirms head SHA and pipeline status
glab ci status                # or check the triggered pipeline directly
```
If there is no open MR for this branch, create one in Step 8.5. Never merge, approve, enable auto-merge, or run `glab mr merge`; merge decisions always belong to a human.

---

### Step 8.5 — Merge request description

Write a suitable merge-request description for the entire commit chain before creating or updating the MR. Include:

- A concise outcome-focused summary
- The logical changes represented by every commit
- Configuration defaults, operational impact, and risks
- Validation performed and its results

Use `glab mr create` or `glab mr update` with the written description. Do not rely solely on an auto-filled MR description.

---

### Step 8.6 — Monitor and repair the pipeline

Monitor the MR pipeline to a terminal state with:

```
glab ci status --live
```

If it fails, inspect the failed jobs and logs using `glab ci status --output json`, `glab ci view`, and `glab ci trace <job>`. First establish whether each failure is related to this branch.

For a related implementation, test, lint, security, or dependency failure:

1. Diagnose the root cause and fix production code, configuration, or dependencies. Never change a test merely to pass; only align fixtures or expectations with intentionally changed behaviour while preserving the assertion's protection.
2. If a job reports missing, incompatible, vulnerable, or outdated dependencies, update the declared dependency and lockfile with the project package manager. Run the relevant install, lint, and test checks.
3. Create a focused follow-up commit, run the relevant local checks and the full suite where available, push it, and update the MR description with the repair and validation.
4. Run `glab ci status --live` again. Repeat this repair-and-monitor loop until the pipeline passes or the remaining failure is demonstrably unrelated or externally blocked.

Prefer a new follow-up commit to rewriting a pushed branch. Obtain explicit user approval before any `git push --force-with-lease`.

---

### Step 9 — Final summary

Output a summary in this format:

```
Commit chain:
  1. <hash> <message>
  2. <hash> <message>
  ...

Semgrep: PASS / FINDINGS (list findings)
Tests: X passed, Y failed in Z seconds

Pushed: <branch> -> origin/<branch> (<force-with-lease used: yes/no>)
MR: <url, if one exists> — pipeline <status>
Self-healing follow-ups: <commits and outcomes, or none>
```

If a pipeline remains failed, replace the final status with the failure evidence and why it is unrelated or externally blocked. Do not merge the MR.

---

## Principles to keep in mind

**Why clean commits matter:**
- `git bisect` only works if each commit is individually correct and buildable. Mixing concerns makes bisect useless.
- Code reviewers read commits sequentially — a logical boundary per commit lets them understand intent before seeing implementation.
- Revert granularity: you can `git revert` a single feature commit without touching unrelated changes.

**On soft-reset hygiene:**
- A soft reset is non-destructive — it only moves the branch pointer, leaving all changes in the working tree.
- The stash backup means you can always recover: `git stash pop` or `git stash show -p stash@{0}`.
- Never hard-reset unless the user explicitly asks — you would lose work.

**Hunk-level staging discipline:**
- It is common for a single file to contain changes from two concerns (e.g. a shared utility file touched by both a bug fix and a new feature). Always think at the hunk level, not the file level.
- When in doubt, keep a commit smaller rather than larger. A commit that does one thing and its message describes exactly what that one thing is will never confuse a future reader.

**Amend, don't stack, when refining your own unmerged work:**
- A commit history where "add session recording" is immediately followed three commits later by "fix typo in session recording" is noise a reviewer has to mentally squash themselves. If that commit hasn't reached `main`, squash it for them via amend/fixup+autosquash (Step 3.5).
- This is about *your own* recent, unmerged work on *this* branch — never rewrite commits already on `main`, and never rewrite another contributor's commits without asking.
- Rewriting pushed history requires `--force-with-lease` and the user's explicit confirmation — treat it with the same care as any other destructive git operation.
