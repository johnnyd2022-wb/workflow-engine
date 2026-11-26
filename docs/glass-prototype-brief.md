# Glass prototype: brief for page builders

Branch `proto/glass-theme` is a **prototype that is never merged into main**. It is deployed on its own to
`test-glass.biz-e.app` and uses the same test database as test.biz-e.app. Look and structure come from the
founder's chosen mockup:
`/home/johnny/.herdr/worktrees/workflow-engine/feat-production-overview-mockups/docs/design-options/production-overview/22-glass-bar-tray.html`
Open it, read its CSS, and screenshot it if you need to.

## Hard rules
- **No schema, migration, or API response changes.** Templates, CSS, page JS and navigation only. The DB is shared.
- **Keep htmx boost working.** Page scripts stay inside `{% block scripts %}`/content and bind to the page root, so a
  second boosted visit works. Never add a run-once flag on `window` for page code.
- **Don't edit `glass.css`, `base_spa.html` or `glass_topbar.html`.** They belong to the orchestrator. Put your rules in
  your group's file `app/core/frontend/css/glass-gN.css` (already linked globally). Compliance and Sales have their own
  static folders, so you may edit their CSS there as well. If you need a shared component changed, write the request
  in the board task's log (`wb log <id> <agent> request "..."`).
- One look across all pages, built from the shared pieces:
  - `.g-panel`: content container (24px radius, near-opaque).
  - `.g-card-h`: container heading row (h2 plus a link on the right).
  - `.g-bar`: transparent glass bar for a row of actions or links. The page's main buttons sit in one bar near the
    top; "Manage …" links sit in one at the bottom.
  - `.g-btn` / `.g-btn--primary`: pill buttons. The existing `btn`, `btn-primary`, `workspace-button`, `crm-btn` are
    already restyled to match.
  - `.g-fig`: stat card. `.g-chip`: chips. `.g-cap`: caption text. `.g-pill--bad|warn|ok`: status pills.
  - `workspace-card`, `card`, `crm-card`, `customs-card` and similar are already restyled as panels.
  - Tokens (use these, never hard-coded colours): `--ink --text --muted --accent --accent-soft --ok/--warn/--bad
    (+ -soft) --panel --glass --glass-strong --solid --line --field --field-line`. Dark mode is
    `html[data-spa-theme="dark"]`. Tokens switch on their own.
- **Room to breathe:** 18px between containers, 22–24px inside panels, one primary action per view, status shown as
  words plus colour, never colour alone.
- **Phone:** nothing scrolls sideways at 320–390. Tables become stacked rows or scroll inside their own panel.
  Dialogs rise from the bottom as sheets.
- Remove page-local duplicates of the shell (old back buttons, page-level dark toggles, sidebar remnants) where the
  top bar now covers them.

## Workflow (exactly two builders at once)
1. Set up your worktree once:
   `git -C /home/johnny/workflow-engine worktree add -b glass/<you> ~/.herdr/worktrees/workflow-engine/glass-<you> proto/glass-theme && cd ~/.herdr/worktrees/workflow-engine/glass-<you> && uv sync -q --extra dev`
2. Claim a task: `wb claim <you> glass`. This prints the task, or nothing if none is free. Run
   `wb heartbeat <TASK>` at least every 30 minutes while you work.
3. Before starting each task, bring in the latest branch: `git merge --no-edit proto/glass-theme`.
4. Build every page in the task's group. Shoot screenshots (the org is already seeded; never run `seed` or `purge`):
   `UI_SHOTS_HOME=~/.cache/workflow-engine-ui-shots/glass env -u ENVIRONMENT uv run python scripts/ui_shots.py shoot ~/.cache/workflow-engine-ui-shots/glass/<you>-<n> --scenarios scripts/glass_scenarios.py gN 2>&1 | grep '^ui-shots:'`
   Read **every** PNG. List the defects, fix them, shoot again. You are done only when a full pass has no defects and
   no `console error` lines. Add routes to `GROUPS` in `scripts/glass_scenarios.py` if your group has pages it misses
   (detail pages: pick a real id from the seeded org).
5. Run the e2e files that cover your pages, plus
   `env -u ENVIRONMENT uv run pytest tests/e2e/test_pages_render.py tests/e2e/test_boosted_navigation.py -q -x`.
   Tests that pin the old look (sidebar, Home, old classes) may be updated to the glass behaviour on this branch. Say
   which tests and why in the task log. Never weaken an assertion about behaviour.
6. Before handing in, run `node --check` on changed JS, `uv run --extra dev ruff check app/`, and
   `semgrep --config .semgrep/rules/ <changed js/html> --error -q`.
7. Commit on `glass/<you>` (message `Glass GN: …`, ending with the Co-Authored-By/Claude-Session lines from your
   instructions). Then run `wb set <TASK> status=in_review branch=glass/<you>` and
   `wb log <TASK> <you> done "<pages, tests changed, screenshots dir>"`. The orchestrator merges it.
8. Claim the next task. Stop when `wb claim` returns nothing.

Never push, never touch main, never run `ui_shots.py purge`, never stop another agent's processes.
