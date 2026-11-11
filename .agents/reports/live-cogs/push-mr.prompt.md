# Push and open the MR — live-cogs 8.1a

You are working in /home/johnny/wt-live-cogs (git worktree, branch feat/live-cogs). The founder asked
Codex to push this MR. Do exactly these steps and nothing else. Don't change any code.

1. `git status --short` must be clean and `git branch --show-current` must be `feat/live-cogs`;
   stop and report if not. `git fetch origin`. Do NOT rebase or merge origin/main.
2. `git push -u origin feat/live-cogs`.
3. Open a DRAFT MR with glab, description from the file (pass it as "$(cat ...)", not a
   --description-file; it can't read every path):
   `glab mr create --draft --source-branch feat/live-cogs --target-branch main --title "Live cost engine (roadmap 8.1a)" --description "$(cat .agents/reports/live-cogs/mr-description.md)" --yes`
4. Read it back (`glab mr view feat/live-cogs` or `glab api projects/:id/merge_requests/<iid>`) and
   confirm the stored description contains "## Acceptance criteria" and "VERDICT" is NOT in it
   but "build-review round 3" IS. If the body is missing or truncated, `glab mr update <iid>
   --description "$(cat .agents/reports/live-cogs/mr-description.md)"` and read it back again.
5. In `docs/source-to-sale-plan.md`, change the line starting `  - [ ] a. **Cost engine.**` to
   `  - [x] a. **Cost engine.**` and append ` (!<iid>)` at the end of that item's last line
   (the line ending `feature.`). Commit:
   `git commit -am "Tick roadmap 8.1a (!<iid>)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -m "Claude-Session: https://claude.ai/code/session_012K4jB79TxztZobCHJU3cVj"`
   then `git push`.
6. Final message: the MR URL, its iid, and the pipeline status from `glab ci status` (don't wait
   for it to finish).
