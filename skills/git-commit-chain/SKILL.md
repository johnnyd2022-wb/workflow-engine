---
name: git-commit-chain
description: Create, validate, push, document, and monitor a clean chain of logically scoped Git commits and its GitLab merge request. Use when asked to organise changes into commits, prepare a commit chain, push a branch for review, or diagnose and repair related GitLab CI failures.
---

# Git commit chain

Use `glab` for every GitLab API, merge-request, and pipeline interaction. Use local `git` commands only for local working-tree and branch operations (including the local checkout update required by `git pull`).

1. Inspect `git status --short --branch` and the task. If the current branch is `main`, query GitLab's default-branch commit with `glab api projects/:id/repository/branches/main` and compare its `commit.id` with `git rev-parse HEAD`; when GitLab is ahead, update the local checkout with `git pull --ff-only origin main`. Stop if that cannot fast-forward.
2. Before analysing or stashing changes, create a concise, relevant branch from the updated base: `git switch -c <type>/<short-task-slug>`. Do not commit work directly to `main`.
3. Read the complete diff and group files or hunks into independently reviewable commit buckets. Match the repository's recent commit-message style; use short imperative subjects.
4. Create a safety stash with untracked files. If the branch has commits ahead of `main`, soft-reset to `main`, then pop the stash; otherwise, pop the stash directly. Never hard-reset.
5. Stage each bucket explicitly (use `git add -p` when needed), verify `git diff --cached`, commit it, and verify the resulting commit. Do not use `git add .` or `git add -A`; never commit secrets.
6. Review `git log main..HEAD --oneline`. Amend or autosquash only corrections to this branch's own unmerged commits; do not rewrite merged or another contributor's history. Get explicit approval before a force-with-lease push.
7. Run the relevant tests and `uv run semgrep scan --config=auto` (fall back to `--config=p/default` only if necessary). Do not push when validation fails unless the user explicitly accepts a known external or environment-only limitation.
8. Push the branch, using `--force-with-lease` only with explicit approval when history was rewritten. Write a suitable merge-request description for the complete chain: explain the outcome, list the logical changes, state configuration/default changes and risks, and record validation results. Create or update the MR with `glab mr create` or `glab mr update`; do not rely solely on an auto-filled description.
9. Monitor the resulting pipeline to a terminal state with `glab ci status --live` (or repeated `glab ci status` checks). Never merge, approve, enable auto-merge, or run `glab mr merge`; leave that decision to a human.
10. If the pipeline fails, inspect the failed job and its logs with `glab ci view`, `glab ci status --output json`, and `glab ci trace <job>`. Decide whether the failure is caused by this branch before changing anything. For a related implementation, test, lint, security, or dependency failure, diagnose the root cause and fix it:
    - Change production code, configuration, or dependencies—not a test merely to make it pass. A test fixture or expectation may change only when it faithfully expresses an intentional behaviour change; never remove, skip, weaken, or broaden assertions to hide a regression.
    - When a job reports missing, incompatible, vulnerable, or outdated dependencies, update the declared dependency and lockfile using the project package manager, then run the relevant install, lint, and test checks.
    - Add a focused follow-up commit for the repair, run the relevant local checks (and the full suite where available), push it, update the MR description, and return to pipeline monitoring. Prefer a new follow-up commit over rewriting a pushed branch; obtain explicit approval before any force-with-lease push.
11. If a failure is pre-existing, unrelated, or requires unavailable external infrastructure/credentials, do not mask it or change unrelated code. Record the evidence and report it as a blocker. Continue the repair-and-monitor loop only while there is a related, safe fix to make.

Report the commits, validation outcome, pushed branch, MR URL, final pipeline status, every self-healing follow-up, and any unresolved external blocker.
